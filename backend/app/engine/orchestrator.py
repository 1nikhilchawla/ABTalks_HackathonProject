"""The interview orchestrator — one turn of the loop.

Pipeline per candidate message:

    sanitize -> classify -> (evaluate) -> update state -> decide -> render -> persist

Deliberate design choices:

* Non-answers never reach the evaluator, so "can you repeat that?" cannot be
  scored as a weak answer.
* "Repeat the question" is answered from state, not from a model call — it is
  free, instant, and cannot drift.
* The rolling summary is computed from evaluations rather than by asking a
  model to summarise the transcript, which keeps prompt size flat as the
  interview grows without spending a call per turn.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import Settings, get_settings
from ..data.curriculum import get_curriculum
from ..llm.router import LLMRouter
from ..models.contract import Feedback
from ..models.domain import (
    Action,
    AnswerEvaluation,
    CandidateProfile,
    Decision,
    InterviewState,
    Stage,
    Turn,
    Utterance,
)
from ..security.sanitize import sanitize
from . import evaluator as ev
from . import policy, prompts, questioner, reporter, topics
from .classifier import classify
from .planner import build_plan, plan_headline

log = logging.getLogger("cohortiq.orchestrator")

_REASON_TEXT = {
    "opening_topic": "This opens the interview on ground your learning record says you own.",
    "no_active_topic": "Starting a new topic — nothing was in progress.",
    "strong_answer_raise_difficulty": "Your last answer was strong, so the difficulty went up.",
    "weak_answer_probe_fundamentals": "Your last answer was thin, so this drops to fundamentals on the same topic.",
    "dont_know_probe_fundamentals": "You said you didn't know, so this is a more basic entry point into the same area.",
    "dont_know_topic_exhausted": "Two attempts on that topic didn't land, so we moved on.",
    "adequate_answer_probe_specifics": "Your answer described the outcome but not the mechanism, so this probes the specifics.",
    "coverage_floor_requires_depth": "The interview needs more depth to meet its coverage floor, so this goes deeper rather than moving on.",
    "coverage_floor_not_met_extending": "The planned topics ran out before the coverage floor, so the interview extended this one.",
    "topic_covered_move_on": "That topic is covered; moving to the next planned area.",
    "two_weak_answers_change_topic": "Two weak answers in a row on one topic — changing area rather than grinding.",
    "weak_answer_topic_exhausted": "Follow-up budget for that topic is used up.",
    "non_answer_after_evaluation": "That didn't contain an answer, so the interview moved on.",
    "answer_drifted_from_question": "Your answer moved away from what was asked, so this redirects.",
    "candidate_requested_skip": "You asked to skip, so the interview moved to the next topic.",
    "candidate_refused_topic": "You declined that one, so the interview moved on.",
    "candidate_asked_for_repeat": "You asked for the question again.",
    "candidate_requested_hint": "You asked for a hint.",
    "candidate_asked_interviewer_a_question": "You asked the interviewer something, so this answers it and returns to the interview.",
    "prompt_injection_detected": "That message tried to instruct the interviewer rather than answer it. It was logged and ignored.",
    "empty_response": "Nothing usable arrived, so the question was restated.",
    "moving_on_after_repeated_non_answers": "Several turns in a row had no answer, so the interview moved to new ground.",
    "candidate_volunteered_topic": "Your answer was mostly about another topic on the plan, "
    "so the interview followed you there instead of pulling you back.",
    "early_end_request_declined": "It's too early to end — a few more questions are needed for a fair assessment.",
}


def _why(decision: Decision, state: InterviewState) -> str:
    base = _REASON_TEXT.get(decision.reason_code.split(":")[0], "")
    if decision.reason_code.startswith("claim_requires_validation"):
        base = "You made a claim that hasn't been backed with evidence yet, so this challenges it."
    slot = state.slot(decision.slot_id)
    bits = [b for b in [base] if b]
    if decision.intent is Action.ASK_NEW_TOPIC and slot:
        bits.append(
            f"Topic chosen from Day {slot.day} ({slot.day_title}) because your record shows you {slot.signal}."
        )
    elif slot and decision.intent in (Action.FOLLOW_UP, Action.CHALLENGE_CLAIM):
        if decision.evidence and decision.evidence[0]:
            bits.append(f"It builds on: \"{decision.evidence[0][:140]}\".")
    return " ".join(bits) or "Continuing the interview."


class Orchestrator:
    def __init__(self, router: LLMRouter, settings: Settings | None = None) -> None:
        self.router = router
        self.settings = settings or get_settings()
        self.limits = self.settings.limits

    # ------------------------------------------------------------------
    # Session start
    # ------------------------------------------------------------------
    async def start(
        self, session_id: str, candidate: CandidateProfile, persona: str = prompts.DEFAULT_PERSONA
    ) -> tuple[InterviewState, str, dict[str, Any]]:
        state = InterviewState(
            session_id=session_id,
            candidate=candidate,
            persona=persona if persona in prompts.PERSONAS else prompts.DEFAULT_PERSONA,
        )
        state.plan = build_plan(candidate, self.limits)
        state.difficulty = state.plan[0].base_difficulty if state.plan else 3
        state.provider_in_use = self.router.primary_name

        decision = policy.decide(state, self.limits, utterance=None, evaluation=None)
        question, note, notes = await questioner.generate_question(
            router=self.router, state=state, decision=decision
        )

        greeting = self._greeting(state)
        spoken = f"{greeting}\n\n{question}"
        self._commit_question(state, decision, spoken, note, notes)
        # A repeat request must restate the question, not the whole greeting.
        state.pending_question = question
        trace = self._trace(state, decision, None, notes, extra={"planHeadline": plan_headline(candidate, state.plan)})
        return state, spoken, trace

    def _greeting(self, state: InterviewState) -> str:
        c = state.candidate
        label = prompts.persona_label(state.persona)
        if c.is_placeholder:
            return (
                f"Hi — I'm your interviewer for this session ({label}). I don't have your cohort "
                "record, so we'll cover the core of the programme and I'll calibrate as we go. "
                "Answer as you would in a real interview; there are no trick questions."
            )
        days = ", ".join(str(d) for d in sorted({s.day for s in state.plan})[:6])
        return (
            f"Hi {c.name.split()[0]} — thanks for making time. I'm your interviewer for this "
            f"session ({label}), and I've read your cohort record: "
            f"{c.signals.missions_completed} missions completed, "
            f"{c.signals.missions_first_try} first try. "
            f"We'll go through roughly {self.limits.min_questions} questions across days {days}, "
            "and I'll follow up on whatever is interesting. Let's start."
        )

    # ------------------------------------------------------------------
    # One conversational turn
    # ------------------------------------------------------------------
    async def turn(self, state: InterviewState, message: str | None) -> tuple[str, dict[str, Any]]:
        started = time.perf_counter()
        clean = sanitize(message, self.limits.max_answer_chars)
        utterance = classify(clean)

        if clean.injection_detected:
            state.injection_attempts += 1
            log.warning(
                "session=%s injection patterns=%s", state.session_id, list(clean.injection_hits)
            )

        last_question = self._last_question(state)
        evaluation: AnswerEvaluation | None = None
        notes: list[str] = []

        candidate_turn = state.add_turn(
            Turn(
                index=0,
                role="candidate",
                text=clean.text,
                slot_id=state.active_slot_id,
                day=state.active_slot.day if state.active_slot else None,
                utterance=utterance,
            )
        )

        if utterance is Utterance.ANSWER:
            state.consecutive_non_answers = 0
            evaluation, notes = await ev.evaluate_answer(
                router=self.router,
                state=state,
                question=last_question,
                answer=clean.text,
                difficulty=state.difficulty,
            )
            candidate_turn.evaluation = evaluation
            ev.resolve_claim_outcome(state, evaluation)
            ev.record_claims(state, evaluation, candidate_turn.index)
            self._update_streaks(state, evaluation)
        else:
            state.consecutive_non_answers += 1
            if clean.truncated:
                notes.append("answer truncated at the input limit")

        # Retrieval: did this answer belong to a different planned day?
        volunteered = (
            topics.detect_volunteered_topic(state, clean.text) if evaluation is not None else None
        )
        if volunteered is not None:
            notes.append(
                f"retrieval: answer matched day {volunteered.day.day} "
                f"({volunteered.score:.1f} vs {volunteered.active_score:.1f} for the current topic)"
            )

        decision = policy.decide(
            state,
            self.limits,
            utterance,
            evaluation,
            volunteered=volunteered.slot if volunteered else None,
        )

        if decision.reason_code == "candidate_volunteered_topic" and volunteered is not None:
            state.volunteered_jumps += 1
            # Score the answer against the topic it was actually about. Leaving
            # it attributed to the topic it drifted from would put an unfair low
            # score on a day the candidate never really answered.
            candidate_turn.slot_id = volunteered.slot.slot_id
            candidate_turn.day = volunteered.day.day
            notes.append(
                f"answer re-attributed to day {volunteered.day.day} (it was about that topic)"
            )

        if decision.intent is Action.END_INTERVIEW:
            reply, trace = await self._finish(state, decision, evaluation, notes)
            trace["latencyMs"] = int((time.perf_counter() - started) * 1000)
            return reply, trace

        spoken, note, gen_notes = await self._render(state, decision, evaluation, last_question)
        notes.extend(gen_notes)
        self._commit_question(state, decision, spoken, note, notes)
        self._refresh_summary(state)

        trace = self._trace(state, decision, evaluation, notes)
        trace["latencyMs"] = int((time.perf_counter() - started) * 1000)
        return spoken, trace

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    async def _render(
        self,
        state: InterviewState,
        decision: Decision,
        evaluation: AnswerEvaluation | None,
        last_question: str,
    ) -> tuple[str, str, list[str]]:
        # Process turns are answered from state: free, instant, and immune to
        # a model deciding to invent a new question instead of repeating one.
        pending = state.pending_question or last_question

        # The pending question may already carry its own framing, so re-asks are
        # separated by a paragraph break rather than glued on with a preamble.
        if decision.reason_code == "candidate_asked_for_repeat" and pending:
            return (
                f"Of course.\n\n{pending}",
                "verbatim repeat from state",
                ["repeat served from state (no model call)"],
            )

        if decision.reason_code == "prompt_injection_detected":
            return (
                "That message is trying to instruct me rather than answer the question. I'll note "
                "it and carry on — it has no effect on your score."
                + (f"\n\n{pending}" if pending else ""),
                "injection acknowledged, not obeyed",
                ["injection handled without a model call"],
            )

        if decision.reason_code == "candidate_asked_interviewer_a_question":
            return (
                self._meta_reply(state, pending),
                "meta question answered from state",
                ["meta question handled without a model call"],
            )

        if decision.reason_code == "early_end_request_declined" and pending:
            return (
                "We're only a few questions in — let's get through a couple more so the feedback "
                "is worth something.\n\n" + pending,
                "early end declined",
                ["handled without a model call"],
            )

        hook = ""
        if evaluation:
            hook = evaluation.followup_hook or evaluation.evidence_quote
        if decision.intent in (Action.FOLLOW_UP, Action.CHALLENGE_CLAIM) and hook:
            ev.mark_claim_probed(state, hook)

        return await questioner.generate_question(
            router=self.router, state=state, decision=decision, hook=hook
        )

    # ------------------------------------------------------------------
    # State bookkeeping
    # ------------------------------------------------------------------
    def _commit_question(
        self,
        state: InterviewState,
        decision: Decision,
        spoken: str,
        note: str,
        notes: list[str],
    ) -> None:
        slot = state.slot(decision.slot_id)
        counts_as_question = decision.intent not in (
            Action.HANDLE_META,
            Action.CLARIFY,
            Action.GIVE_HINT,
        )

        if slot is not None:
            if decision.intent is Action.ASK_NEW_TOPIC:
                previous = state.active_slot
                if previous and previous.slot_id != slot.slot_id:
                    previous.closed = True
                state.active_slot_id = slot.slot_id
                slot.asked = True
            elif decision.intent in (
                Action.FOLLOW_UP,
                Action.CHALLENGE_CLAIM,
                Action.INCREASE_DIFFICULTY,
                Action.DECREASE_DIFFICULTY,
                Action.REDIRECT,
            ):
                slot.followups_used += 1
            if counts_as_question:
                slot.questions_asked += 1

        if counts_as_question:
            state.questions_asked += 1
            state.pending_question = spoken
        if decision.intent is Action.ASK_NEW_TOPIC:
            # Fresh ground: a candidate who stalled on one topic starts even here.
            state.consecutive_non_answers = 0
            state.consecutive_weak = 0
        state.difficulty = max(1, min(decision.difficulty, 5))
        state.stage = policy.stage_for(state.active_slot) if not state.done else Stage.COMPLETE
        state.provider_in_use = self.router.primary_name
        state.degraded = state.degraded or any("fell back" in n or "exhausted" in n for n in notes)

        state.add_turn(
            Turn(
                index=0,
                role="interviewer",
                text=spoken,
                slot_id=decision.slot_id,
                day=decision.day,
                action=decision.intent,
                difficulty=decision.difficulty,
                trace={
                    "reasonCode": decision.reason_code,
                    "why": _why(decision, state),
                    "questionType": decision.question_type,
                    "internalNote": note,
                },
            )
        )

    @staticmethod
    def _update_streaks(state: InterviewState, evaluation: AnswerEvaluation) -> None:
        if evaluation.verdict == "strong":
            state.consecutive_strong += 1
            state.consecutive_weak = 0
        elif evaluation.verdict in ("weak", "non_answer"):
            state.consecutive_weak += 1
            state.consecutive_strong = 0
        else:
            state.consecutive_strong = 0
            state.consecutive_weak = 0

    def _refresh_summary(self, state: InterviewState) -> None:
        """Compress old context deterministically instead of resending it.

        Prompt size stays roughly constant after ~6 turns, which is what keeps
        a 14-question interview affordable.
        """
        if len(state.turns) < 8:
            return
        lines: list[str] = []
        for slot in state.plan:
            if slot.questions_asked == 0:
                continue
            scores = [
                t.evaluation.composite
                for t in state.answered_turns()
                if t.slot_id == slot.slot_id and t.evaluation
            ]
            if not scores:
                continue
            avg = int(sum(scores) / len(scores))
            verdict = "strong" if avg >= 72 else "adequate" if avg >= 52 else "weak"
            lines.append(f"Day {slot.day} {slot.day_title}: {verdict} ({avg}/100, {len(scores)} answers)")
        if state.claims:
            unresolved = [c.text[:60] for c in state.claims if c.status.value == "ASSERTED"][:3]
            if unresolved:
                lines.append("Unverified claims: " + "; ".join(unresolved))
        state.rolling_summary = "\n".join(lines[-8:])

    @staticmethod
    def _last_question(state: InterviewState) -> str:
        for turn in reversed(state.turns):
            if turn.role == "interviewer":
                return turn.text
        return ""

    def _meta_reply(self, state: InterviewState, pending: str) -> str:
        """Answer a question the candidate asked the interviewer, honestly.

        Deterministic because these answers are factual claims about the system
        itself — exactly the place where a model improvising would be worst.
        """
        last = ""
        for turn in reversed(state.turns):
            if turn.role == "candidate":
                last = turn.text.lower()
                break

        remaining = max(self.limits.min_questions - state.questions_asked, 0)
        if any(k in last for k in ("are you an ai", "are you a bot", "are you human", "who are you", "a real person")):
            answer = (
                "I'm an AI interviewer. I've read your cohort learning record and I'm choosing "
                "questions from it as we go — nothing here is pre-scripted."
            )
        elif any(k in last for k in ("scor", "evaluat", "grad", "mark", "judge")):
            answer = (
                "I score each answer on six dimensions — technical accuracy, conceptual depth, "
                "specificity, communication, practical evidence and relevance — and you'll see the "
                "full breakdown with the reasoning at the end."
            )
        elif any(k in last for k in ("how many", "how long", "how much longer", "left")):
            answer = (
                f"You've answered {state.questions_asked} so far; expect at least "
                f"{remaining or 'a few'} more, depending on how the follow-ups go."
            )
        elif any(k in last for k in ("my score", "how am i doing", "how did i do")):
            answer = (
                "I hold scores back until the end so they don't change how you answer. You'll get "
                "the whole breakdown in a moment."
            )
        elif any(k in last for k in ("company", "role", "job", "position")):
            answer = (
                "This is a practice interview against your cohort curriculum, not a specific "
                "vacancy — so answer as you would for the AI engineering role you're targeting."
            )
        else:
            answer = "Fair question — I'll come back to that at the end so we keep your time for the interview."
        return f"{answer}\n\n{pending}" if pending else answer

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------
    async def _finish(
        self,
        state: InterviewState,
        decision: Decision,
        evaluation: AnswerEvaluation | None,
        notes: list[str],
    ) -> tuple[str, dict[str, Any]]:
        feedback, report, report_notes = await reporter.generate_report(
            router=self.router, state=state
        )
        notes.extend(report_notes)

        state.done = True
        state.stage = Stage.COMPLETE
        state.feedback = feedback.model_dump()
        state.report = report

        closing = (
            f"That's the interview — thanks, {state.candidate.name.split()[0]}. "
            f"You answered {state.questions_asked} questions across "
            f"{len(state.covered_days())} curriculum days. "
            "Your written assessment is on screen now."
        )
        state.add_turn(
            Turn(
                index=0,
                role="interviewer",
                text=closing,
                action=Action.END_INTERVIEW,
                trace={"reasonCode": decision.reason_code, "why": _why(decision, state)},
            )
        )
        trace = self._trace(state, decision, evaluation, notes)
        trace["final"] = True
        return closing, trace

    # ------------------------------------------------------------------
    # Trace for the UI
    # ------------------------------------------------------------------
    def _trace(
        self,
        state: InterviewState,
        decision: Decision,
        evaluation: AnswerEvaluation | None,
        notes: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        slot = state.active_slot
        curriculum = get_curriculum()
        day = curriculum.day(slot.day) if slot else None
        trace: dict[str, Any] = {
            "decision": {
                "intent": decision.intent.value,
                "topic": decision.topic,
                "day": decision.day,
                "difficulty": decision.difficulty,
                "reasonCode": decision.reason_code,
                "questionType": decision.question_type,
                "confidence": round(decision.confidence, 2),
                "evidence": decision.evidence,
            },
            "why": _why(decision, state),
            "stage": state.stage.value,
            "difficulty": state.difficulty,
            "questionsAsked": state.questions_asked,
            "coverage": {
                "daysCovered": state.covered_days(),
                "minDays": self.limits.min_distinct_days,
                "minQuestions": self.limits.min_questions,
                "maxQuestions": self.limits.max_questions,
            },
            "currentTopic": (
                {
                    "day": slot.day,
                    "title": slot.day_title,
                    "module": slot.module,
                    "kind": slot.kind.value,
                    "signal": slot.signal,
                    "signalCode": slot.signal_code,
                    "objectives": list(day.objectives)[:3] if day else [],
                }
                if slot
                else None
            ),
            "provider": {
                "primary": self.router.primary_name,
                "live": self.router.is_live(),
                "degraded": state.degraded,
                "notes": notes[-6:],
            },
            "usage": self.router.usage.snapshot(),
            "injectionAttempts": state.injection_attempts,
        }
        if evaluation is not None:
            trace["evaluation"] = {
                "verdict": evaluation.verdict,
                "composite": evaluation.composite,
                "dimensions": evaluation.scores.as_dict(),
                "rationale": evaluation.rationale,
                "flags": evaluation.flags,
                "evidenceQuote": evaluation.evidence_quote,
                "missingPoints": evaluation.missing_points,
                "source": evaluation.source,
            }
        if extra:
            trace.update(extra)
        return trace


def public_state(state: InterviewState, limits) -> dict[str, Any]:
    """Compact state for the UI's status rail."""
    return {
        "sessionId": state.session_id,
        "stage": state.stage.value,
        "persona": state.persona,
        "personaLabel": prompts.persona_label(state.persona),
        "difficulty": state.difficulty,
        "questionsAsked": state.questions_asked,
        "minQuestions": limits.min_questions,
        "maxQuestions": limits.max_questions,
        "daysCovered": state.covered_days(),
        "minDays": limits.min_distinct_days,
        "done": state.done,
        "degraded": state.degraded,
        "candidate": {
            "name": state.candidate.name,
            "role": state.candidate.job_role,
            "years": state.candidate.years_experience,
            "isPlaceholder": state.candidate.is_placeholder,
            "parseNotes": state.candidate.parse_notes,
        },
        "plan": [
            {
                "slotId": s.slot_id,
                "day": s.day,
                "title": s.day_title,
                "module": s.module,
                "kind": s.kind.value,
                "signal": s.signal,
                "signalCode": s.signal_code,
                "difficulty": s.base_difficulty,
                "questionsAsked": s.questions_asked,
                "closed": s.closed,
                "active": s.slot_id == state.active_slot_id,
            }
            for s in state.plan
        ],
        "claims": [
            {"text": c.text, "status": c.status.value, "topic": c.topic} for c in state.claims
        ],
        "scores": [
            {
                "turn": t.index,
                "day": t.day,
                "composite": t.evaluation.composite if t.evaluation else None,
                "verdict": t.evaluation.verdict if t.evaluation else None,
            }
            for t in state.answered_turns()
        ],
    }
