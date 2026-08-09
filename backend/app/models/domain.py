"""Internal domain model for the interview engine.

The whole interview is a single serialisable ``InterviewState`` object. That is
deliberate: it makes the engine a pure-ish function of (state, utterance), which
in turn makes it testable, resumable after a refresh, and cheap to persist.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Candidate
# --------------------------------------------------------------------------
class Mission(BaseModel):
    day: int
    title: str = ""
    passed: bool | None = None
    attempts: int | None = None
    skipped: bool = False


class Signals(BaseModel):
    commit_days: int = 0
    missions_completed: int = 0
    missions_first_try: int = 0


class CandidateProfile(BaseModel):
    """Normalised candidate. Tolerates a partial or malformed payload."""

    id: str = "UNKNOWN"
    name: str = "Candidate"
    job_role: str = "Engineer"
    years_experience: int = 0
    education: str = ""
    status: str = "UNKNOWN"
    missions: list[Mission] = Field(default_factory=list)
    signals: Signals = Field(default_factory=Signals)
    # True when the request carried no usable candidate object at all.
    is_placeholder: bool = False
    parse_notes: list[str] = Field(default_factory=list)

    # ---- derived learning signals ------------------------------------
    @property
    def passed_missions(self) -> list[Mission]:
        return [m for m in self.missions if m.passed and not m.skipped]

    @property
    def first_try_days(self) -> list[int]:
        return [m.day for m in self.passed_missions if (m.attempts or 1) <= 1]

    @property
    def struggle_days(self) -> list[int]:
        """Passed, but only after real friction."""
        return [m.day for m in self.passed_missions if (m.attempts or 1) >= 3]

    @property
    def failed_days(self) -> list[int]:
        return [m.day for m in self.missions if m.passed is False and not m.skipped]

    @property
    def skipped_days(self) -> list[int]:
        return [m.day for m in self.missions if m.skipped]

    @property
    def attempted_days(self) -> list[int]:
        return [m.day for m in self.missions if not m.skipped]

    @property
    def first_try_rate(self) -> float:
        done = max(self.signals.missions_completed, 1)
        return min(self.signals.missions_first_try / done, 1.0)

    def mission_for(self, day: int) -> Mission | None:
        for m in self.missions:
            if m.day == day:
                return m
        return None

    def seniority_band(self) -> Literal["junior", "mid", "senior", "principal"]:
        y = self.years_experience
        if y <= 1:
            return "junior"
        if y <= 6:
            return "mid"
        if y <= 14:
            return "senior"
        return "principal"


# --------------------------------------------------------------------------
# Interview control vocabulary
# --------------------------------------------------------------------------
class Stage(StrEnum):
    INTRO = "INTRO"
    WARMUP = "WARMUP"
    CORE = "CORE"
    PROBE = "PROBE"
    GAP = "GAP"
    SYNTHESIS = "SYNTHESIS"
    WRAP = "WRAP"
    COMPLETE = "COMPLETE"


class Action(StrEnum):
    ASK_NEW_TOPIC = "ASK_NEW_TOPIC"
    FOLLOW_UP = "FOLLOW_UP"
    CHALLENGE_CLAIM = "CHALLENGE_CLAIM"
    INCREASE_DIFFICULTY = "INCREASE_DIFFICULTY"
    DECREASE_DIFFICULTY = "DECREASE_DIFFICULTY"
    CLARIFY = "CLARIFY"
    GIVE_HINT = "GIVE_HINT"
    REDIRECT = "REDIRECT"
    HANDLE_META = "HANDLE_META"
    END_TOPIC = "END_TOPIC"
    END_INTERVIEW = "END_INTERVIEW"


class Utterance(StrEnum):
    """Classification of what the candidate just did."""

    ANSWER = "ANSWER"
    EMPTY = "EMPTY"
    DONT_KNOW = "DONT_KNOW"
    REQUEST_REPEAT = "REQUEST_REPEAT"
    REQUEST_SKIP = "REQUEST_SKIP"
    REQUEST_HINT = "REQUEST_HINT"
    META_QUESTION = "META_QUESTION"
    REFUSAL = "REFUSAL"
    MANIPULATION = "MANIPULATION"
    END_REQUEST = "END_REQUEST"


class SlotKind(StrEnum):
    WARMUP = "WARMUP"
    CORE = "CORE"
    PROBE = "PROBE"
    GAP = "GAP"
    SYNTHESIS = "SYNTHESIS"
    BEHAVIORAL = "BEHAVIORAL"


class ClaimStatus(StrEnum):
    ASSERTED = "ASSERTED"
    PROBED = "PROBED"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


# --------------------------------------------------------------------------
# Plan / coverage
# --------------------------------------------------------------------------
class TopicSlot(BaseModel):
    """One planned interview topic, pre-justified from candidate evidence."""

    slot_id: str
    kind: SlotKind
    day: int
    day_title: str
    module: str
    objectives: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    base_difficulty: int = 3
    signal: str = ""  # human-readable evidence, e.g. "passed on attempt 4"
    signal_code: str = ""  # machine code, e.g. "high_attempts"
    asked: bool = False
    questions_asked: int = 0
    followups_used: int = 0
    closed: bool = False


class Claim(BaseModel):
    """Something the candidate asserted. The evaluator may only cite these."""

    claim_id: str
    text: str
    topic: str
    turn_index: int
    status: ClaimStatus = ClaimStatus.ASSERTED
    evidence: list[str] = Field(default_factory=list)


class DimensionScores(BaseModel):
    technical_accuracy: int = 50
    conceptual_depth: int = 50
    specificity: int = 50
    communication: int = 50
    practical_evidence: int = 50
    relevance: int = 50

    def composite(self) -> int:
        weights = {
            "technical_accuracy": 0.26,
            "conceptual_depth": 0.24,
            "specificity": 0.18,
            "practical_evidence": 0.14,
            "communication": 0.12,
            "relevance": 0.06,
        }
        total = sum(getattr(self, k) * w for k, w in weights.items())
        return int(round(total))

    def as_dict(self) -> dict[str, int]:
        return self.model_dump()


class AnswerEvaluation(BaseModel):
    scores: DimensionScores = Field(default_factory=DimensionScores)
    verdict: Literal["strong", "adequate", "weak", "non_answer"] = "adequate"
    rationale: str = ""
    evidence_quote: str = ""
    missing_points: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    followup_hook: str = ""
    confidence: float = 0.5
    source: str = "heuristic"  # which provider produced this

    @property
    def composite(self) -> int:
        return self.scores.composite()


class Turn(BaseModel):
    index: int
    role: Literal["interviewer", "candidate", "system"]
    text: str
    timestamp: float = Field(default_factory=time.time)
    slot_id: str | None = None
    day: int | None = None
    action: Action | None = None
    difficulty: int | None = None
    utterance: Utterance | None = None
    evaluation: AnswerEvaluation | None = None
    trace: dict[str, Any] | None = None


class Decision(BaseModel):
    """Structured internal decision — the non-chain-of-thought reasoning record."""

    intent: Action
    topic: str
    day: int | None = None
    slot_id: str | None = None
    difficulty: int = 3
    reason_code: str = "default"
    question_type: str = "technical_depth"
    confidence: float = 0.6
    evidence: list[str] = Field(default_factory=list)
    source: str = "policy"


class InterviewState(BaseModel):
    """Everything needed to resume an interview from cold storage."""

    session_id: str
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    candidate: CandidateProfile = Field(default_factory=CandidateProfile)
    persona: str = "principal"
    mode: str = "cohort_review"

    stage: Stage = Stage.INTRO
    plan: list[TopicSlot] = Field(default_factory=list)
    active_slot_id: str | None = None

    turns: list[Turn] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)

    questions_asked: int = 0
    difficulty: int = 3
    consecutive_non_answers: int = 0
    consecutive_weak: int = 0
    consecutive_strong: int = 0
    injection_attempts: int = 0
    #: Times the interview followed the candidate onto a topic they raised.
    #: Budgeted like every other adaptive path — see topics.MAX_JUMPS_PER_INTERVIEW.
    volunteered_jumps: int = 0
    done: bool = False

    # The last real question asked. Meta replies ("can you repeat that?") must
    # restate this, not the meta turn that preceded them.
    pending_question: str = ""
    rolling_summary: str = ""
    feedback: dict[str, Any] | None = None
    report: dict[str, Any] | None = None

    # dedupe / idempotency
    last_request_fingerprint: str | None = None
    last_request_at: float = 0.0
    last_response_payload: dict[str, Any] | None = None

    degraded: bool = False
    provider_in_use: str = "heuristic"

    # ---- helpers ------------------------------------------------------
    def slot(self, slot_id: str | None) -> TopicSlot | None:
        if slot_id is None:
            return None
        for s in self.plan:
            if s.slot_id == slot_id:
                return s
        return None

    @property
    def active_slot(self) -> TopicSlot | None:
        return self.slot(self.active_slot_id)

    def covered_days(self) -> list[int]:
        return sorted({s.day for s in self.plan if s.questions_asked > 0})

    def answered_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "candidate" and t.evaluation is not None]

    def interviewer_questions(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "interviewer" and t.action != Action.HANDLE_META]

    def recent(self, n: int = 6) -> list[Turn]:
        return self.turns[-n:]

    def add_turn(self, turn: Turn) -> Turn:
        turn.index = len(self.turns)
        self.turns.append(turn)
        self.updated_at = time.time()
        return turn
