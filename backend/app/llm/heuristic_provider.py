"""Offline rubric engine — the last link in the fallback chain.

This is *not* a pretend LLM. It is a deterministic, rule-based interviewer that
scores answers from measurable linguistic and technical features and composes
questions from the curriculum's own objectives. Everything it produces is
tagged ``source="heuristic"`` and the UI labels it "offline rubric engine", so
a judge is never shown rule output dressed up as model output.

Why it exists: an interview must not die because a key is missing, a quota is
hit, or conference wifi drops mid-demo. Graceful degradation beats a stack
trace, and having a scoring baseline that does not depend on the model is also
how we sanity-check the model.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from ..data.curriculum import get_curriculum, tokenize
from .base import LLMResult

# --- feature lexicons ------------------------------------------------------
_VAGUE = {
    "basically", "stuff", "things", "etc", "somehow", "kind", "sort", "whatever",
    "something", "various", "generally", "usually", "normally", "simple", "easy",
}
_HEDGE = {"maybe", "probably", "guess", "think", "might", "possibly", "perhaps", "unsure"}
_EVIDENCE = {
    "i", "we", "built", "implemented", "wrote", "deployed", "debugged", "measured",
    "benchmarked", "profiled", "shipped", "tested", "fixed", "refactored", "migrated",
}
_REASONING = {
    "because", "so", "therefore", "trade", "tradeoff", "instead", "whereas", "however",
    "compared", "versus", "reason", "why", "decided", "chose", "alternative",
}
_BUZZ = {
    "leverage", "synergy", "cutting", "edge", "state", "art", "robust", "scalable",
    "seamless", "powerful", "revolutionary", "best", "practice", "optimize",
}
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|k|m|gb|mb|tokens?|dims?|x)?\b", re.I)
#: Phrases that state a preference. Harmless alone — damning when the answer
#: carries no reason, comparison or number to back them up.
_CHOICE_RE = re.compile(
    r"\b(chose|choose|picked|pick|went with|opted|decided on|seemed like|"
    r"preferred|is also good|the right choice|worked fine|worked well|our use case)\b",
    re.I,
)
_DONT_KNOW = re.compile(
    r"^\s*(i\s+)?(don'?t|do not|dont)\s+know|^\s*no idea|^\s*not sure|^\s*never (used|did|heard)",
    re.I,
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", text.lower())


class HeuristicProvider:
    """Deterministic provider. Same seed + same input ⇒ same output."""

    name = "heuristic"
    model = "rubric-v1"

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int = 900,
        temperature: float = 0.4,
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        ctx = context or {}
        if schema_name == "answer_evaluation":
            data = self._evaluate(ctx)
        elif schema_name == "interview_question":
            data = self._question(ctx)
        elif schema_name == "final_report":
            data = self._report(ctx)
        else:
            data = {}
        return LLMResult(
            data=data, provider=self.name, model=self.model, latency_ms=1, input_tokens=0,
            output_tokens=0,
        )

    async def aclose(self) -> None:  # pragma: no cover - nothing to close
        return None

    # ------------------------------------------------------------------
    # Answer evaluation
    # ------------------------------------------------------------------
    def _evaluate(self, ctx: dict[str, Any]) -> dict[str, Any]:
        answer: str = ctx.get("answer", "") or ""
        day_no: int | None = ctx.get("day")
        question: str = ctx.get("question", "") or ""

        toks = _tokens(answer)
        words = len(toks)
        unique = len(set(toks))

        if words == 0:
            return self._non_answer("Empty response.")
        if _DONT_KNOW.match(answer.strip()) and words < 25:
            return self._non_answer("Candidate stated they do not know this.")

        curriculum = get_curriculum()
        day = curriculum.day(day_no) if day_no else None
        domain_terms: set[str] = set()
        if day:
            domain_terms = set(tokenize(day.searchable_text()))
        else:
            domain_terms = set(curriculum.vocabulary)

        # Domain overlap is measured on normalised terms so "chunks"/"ChromaDB"
        # count against the day's "chunk"/"vector" vocabulary.
        answer_terms = set(tokenize(answer))
        overlap = answer_terms & domain_terms

        vague_hits = sum(1 for t in toks if t in _VAGUE)
        hedge_hits = sum(1 for t in toks if t in _HEDGE)
        evidence_hits = sum(1 for t in toks if t in _EVIDENCE)
        reasoning_hits = sum(1 for t in toks if t in _REASONING)
        buzz_hits = sum(1 for t in toks if t in _BUZZ)
        numbers = len(_NUMBER_RE.findall(answer))
        # Compare on normalised terms, not raw words: "chunks" in the answer
        # must count as a hit on "chunk" in the question.
        question_terms = set(tokenize(question))
        on_topic = len(question_terms & answer_terms) / max(len(question_terms), 1)

        # Naming a tool is not the same as justifying it. "We went with Chroma,
        # it worked fine" scores well on domain overlap while containing no
        # engineering reasoning at all, so state a preference without a because,
        # a comparison or a number and the depth score pays for it.
        unjustified_choice = (
            bool(_CHOICE_RE.search(answer))
            and reasoning_hits == 0
            and numbers == 0
            and words > 18
        )
        choice_penalty = 15 if unjustified_choice else 0

        technical = _clamp(35 + len(overlap) * 7 + numbers * 3 - vague_hits * 6)
        conceptual = _clamp(
            30 + reasoning_hits * 9 + len(overlap) * 4 - hedge_hits * 4 - choice_penalty
        )
        specificity = _clamp(
            28 + numbers * 9 + len(overlap) * 5 - vague_hits * 9 - buzz_hits * 4
            - (choice_penalty // 2)
        )

        # Communication measures *structure*, not volume. An earlier version
        # scaled off length and pinned every real answer to 84-100, which made
        # the dimension worthless — one axis of the radar was always maxed.
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if s.strip()]
        sentence_count = max(len(sentences), 1)
        avg_sentence = words / sentence_count
        run_ons = sum(1 for s in sentences if len(s.split()) > 35)
        structure_hits = min(reasoning_hits + _sequence_markers(answer), 5)
        type_token = unique / max(words, 1)
        communication = _clamp(
            52
            + structure_hits * 5              # signposting: "first", "because", "so"
            + (type_token - 0.62) * 55        # vocabulary spread around a natural centre
            # Very short or run-on sentences both hurt, but a rambler who is
            # still comprehensible should not score zero.
            - min(abs(avg_sentence - 18) * 1.1, 25)
            - run_ons * 9
            - vague_hits * 4
            - hedge_hits * 3
            - (18 if words < 15 else 0)
        )
        practical = _clamp(30 + evidence_hits * 8 + numbers * 5 - buzz_hits * 5)
        relevance = _clamp(35 + on_topic * 120 + len(overlap) * 3)

        scores = {
            "technical_accuracy": technical,
            "conceptual_depth": conceptual,
            "specificity": specificity,
            "communication": communication,
            "practical_evidence": practical,
            "relevance": relevance,
        }
        composite = sum(scores.values()) / len(scores)

        flags: list[str] = []
        if vague_hits >= 3:
            flags.append("vague_language")
        if buzz_hits >= 3 and numbers == 0:
            flags.append("buzzword_heavy")
        if words > 260:
            flags.append("rambling")
        if words < 15:
            flags.append("too_short")
        if numbers == 0 and words > 40:
            flags.append("no_concrete_metrics")
        if unjustified_choice:
            flags.append("vague_language")
        # Only call drift when the answer misses BOTH the question's wording and
        # the day's subject matter — otherwise a correct answer phrased in the
        # candidate's own vocabulary gets wrongly redirected.
        if on_topic < 0.08 and len(overlap) < 3 and words > 20:
            flags.append("possibly_off_topic")

        verdict = "strong" if composite >= 72 else "adequate" if composite >= 52 else "weak"

        claims = self._extract_claims(answer, domain_terms)
        missing = []
        if day:
            for obj in day.objectives:
                obj_terms = set(tokenize(obj))
                if obj_terms and len(obj_terms & answer_terms) / len(obj_terms) < 0.12:
                    missing.append(obj)
        rationale = (
            f"Rubric engine: {len(overlap)} on-topic technical terms, {numbers} concrete "
            f"figures, {reasoning_hits} reasoning connectives, {vague_hits} vague markers "
            f"across {words} words."
        )
        hook = claims[0] if claims else (missing[0] if missing else "the mechanism behind that answer")

        return {
            "scores": scores,
            "verdict": verdict,
            "rationale": rationale,
            "evidence_quote": _first_sentence(answer),
            "missing_points": missing[:3],
            "claims": claims[:4],
            "flags": flags,
            "followup_hook": hook,
            "confidence": 0.45,
        }

    @staticmethod
    def _non_answer(reason: str) -> dict[str, Any]:
        return {
            "scores": {
                "technical_accuracy": 0, "conceptual_depth": 0, "specificity": 0,
                "communication": 10, "practical_evidence": 0, "relevance": 0,
            },
            "verdict": "non_answer",
            "rationale": reason,
            "evidence_quote": "",
            "missing_points": [],
            "claims": [],
            "flags": ["non_answer"],
            "followup_hook": "",
            "confidence": 0.9,
        }

    @staticmethod
    def _extract_claims(answer: str, domain_terms: set[str]) -> list[str]:
        claims: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
            s = sentence.strip()
            if len(s) < 18:
                continue
            toks = set(_tokens(s))
            if toks & _EVIDENCE and toks & domain_terms:
                claims.append(s[:220])
        return claims

    # ------------------------------------------------------------------
    # Question generation
    # ------------------------------------------------------------------
    _OPENERS = {
        "ASK_NEW_TOPIC": [
            "Let's move to {title}. {objective_q}",
            "Next area: {title}. {objective_q}",
            "Switching to {title}. {objective_q}",
        ],
        "FOLLOW_UP": [
            "You said \"{hook}\" — walk me through the mechanism, step by step.",
            "Stay with \"{hook}\" for a moment. What breaks first if the volume grows tenfold?",
            "On \"{hook}\": what alternative did you rule out, and what made you rule it out?",
        ],
        "CHALLENGE_CLAIM": [
            "You said \"{hook}\". How did you verify that, rather than assuming it?",
            "About \"{hook}\" — what evidence would have proved you wrong?",
        ],
        "INCREASE_DIFFICULTY": [
            "Harder version: in {title}, where does the standard approach stop working, and what do you do then?",
            "Take {title} to production scale — what is the first bottleneck and how do you measure it?",
        ],
        "DECREASE_DIFFICULTY": [
            "Let's go back to fundamentals. In plain terms, what problem does {title} solve, and why?",
            "Simpler question on {title}: {objective_q}",
        ],
        "CLARIFY": [
            "I want to make sure I follow. Can you restate the key step in one or two sentences?",
        ],
        "GIVE_HINT": [
            "Hint: think about {tool} and what it does for you here. With that in mind — {objective_q}",
        ],
        "REDIRECT": [
            "That drifted from what I asked. Back to {title}: {objective_q}",
        ],
    }

    # Curriculum objectives are imperative phrases ("Build a query router…"),
    # so frames are chosen to stay grammatical when the verb is spliced in.
    _ACTION_FRAMES = [
        "How did you {obj}?",
        "Walk me through how you {obj} — what did you actually build?",
        "What went wrong the first time you tried to {obj}?",
    ]
    _CONCEPT_FRAMES = [
        "In your own words, {obj_rest} — what does that actually mean in a running system?",
        "Explain {obj_rest} the way you would to a new engineer on your team.",
    ]
    _CONCEPT_VERBS = ("understand", "learn", "identify", "analyze", "analyse", "compare", "select")

    def _frame_objective(self, objective: str, rng: random.Random) -> str:
        text = objective.strip().rstrip(".")
        if not text:
            return "Tell me what you built there."
        first, _, rest = text.partition(" ")
        verb = first.lower()
        if verb in self._CONCEPT_VERBS and rest:
            return rng.choice(self._CONCEPT_FRAMES).format(obj_rest=rest[0].lower() + rest[1:])
        obj = verb + (" " + rest if rest else "")
        return rng.choice(self._ACTION_FRAMES).format(obj=obj)

    def _question(self, ctx: dict[str, Any]) -> dict[str, Any]:
        action = str(ctx.get("action", "ASK_NEW_TOPIC"))
        day_no = ctx.get("day")
        hook = ctx.get("hook") or "that"
        day = get_curriculum().day(day_no) if day_no else None
        title = day.title if day else "your cohort work"
        tools = list(day.tools) if day and day.tools else ["the tooling you used"]
        objectives = list(day.objectives) if day and day.objectives else [
            "explain the system you built"
        ]

        seed = hashlib.sha256(
            f"{ctx.get('session_id','')}|{action}|{day_no}|{ctx.get('turn',0)}".encode()
        ).hexdigest()
        rng = random.Random(int(seed[:12], 16))

        # Prefer the retrieval-selected objective (least covered so far); fall
        # back to a seeded random one only when retrieval had nothing to say.
        objective = ctx.get("objective") or rng.choice(objectives)
        objective_q = self._frame_objective(str(objective), rng)

        template = rng.choice(self._OPENERS.get(action, self._OPENERS["ASK_NEW_TOPIC"]))
        question = template.format(
            title=title, objective_q=objective_q, hook=_shorten(hook), tool=rng.choice(tools)
        )
        return {"question": question, "acknowledgement": "", "internal_note": "rubric-composed"}

    # ------------------------------------------------------------------
    # Final report
    # ------------------------------------------------------------------
    def _report(self, ctx: dict[str, Any]) -> dict[str, Any]:
        per_topic: list[dict[str, Any]] = ctx.get("per_topic") or []
        name = ctx.get("name", "The candidate")
        overall = int(ctx.get("overall", 0))
        ranked = sorted(per_topic, key=lambda t: t.get("score", 0), reverse=True)
        strong = [t for t in ranked if t.get("score", 0) >= 65][:3]
        weak = [t for t in ranked if t.get("score", 0) < 55][-3:]
        dim = ctx.get("dimension_averages") or {}
        worst_dim = min(dim, key=dim.get) if dim else "specificity"
        best_dim = max(dim, key=dim.get) if dim else "communication"

        summary = (
            f"{name} scored {overall}/100 across {len(per_topic)} curriculum areas. "
            f"Strongest dimension was {best_dim.replace('_', ' ')}; weakest was "
            f"{worst_dim.replace('_', ' ')}. "
            + (
                f"Best-evidenced area: {strong[0]['topic']}. " if strong else ""
            )
            + (f"Least-evidenced area: {weak[0]['topic']}." if weak else "")
        )
        # Never invent a strength. If nothing scored well, say so — a report that
        # praises a candidate the behaviour notes contradict is worse than blunt.
        if strong:
            strengths = [f"{t['topic']} — scored {t['score']}/100 with usable specifics" for t in strong]
        elif ranked:
            best = ranked[0]
            strengths = [
                f"Relatively strongest area was {best['topic']} at {best['score']}/100, "
                "though it still stayed at description level"
            ]
        else:
            strengths = ["Not enough scored answers to identify a strength"]
        gaps = [
            f"{t['topic']} — {t['score']}/100; answers stayed at description level" for t in weak
        ] or [f"Raise {worst_dim.replace('_', ' ')} across the board"]
        nxt = [
            f"Rebuild the {weak[0]['topic']} exercise and write down the numbers you observe"
            if weak
            else "Re-run your capstone and record concrete latency and cost numbers",
            f"Practise answering with metrics — your weakest dimension was {worst_dim.replace('_',' ')}",
            "Record a 5-minute walkthrough of your capstone architecture and its trade-offs",
        ]
        return {
            "summary": summary,
            "strengths": strengths,
            "gaps": gaps,
            "next": nxt,
            "headline_observation": (
                "Scores below come from the offline rubric engine (no model call), "
                "so they reflect measurable answer features rather than semantic judgement."
            ),
        }


_SEQUENCE_RE = re.compile(
    r"\b(first|firstly|then|next|after that|finally|initially|once|second|third|"
    r"step \d|the problem was|what i did|the result|the fix was)\b",
    re.I,
)


def _sequence_markers(text: str) -> int:
    """Narrative signposting — the strongest cheap signal of a structured answer."""
    return len(_SEQUENCE_RE.findall(text or ""))


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(round(value), hi)))


def _first_sentence(text: str, limit: int = 220) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return (parts[0] if parts else text)[:limit]


def _shorten(hook: str, max_words: int = 12) -> str:
    """Quote-sized fragment — a whole paragraph inside quotes reads badly."""
    words = (hook or "").strip().rstrip(".").split()
    if len(words) <= max_words:
        return " ".join(words) or "that"
    return " ".join(words[:max_words]) + "…"
