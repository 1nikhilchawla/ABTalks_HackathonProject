"""Interview planning: turn a learning record into a defensible question plan.

This is where the product stops being a chatbot. Before a single question is
asked we build an evidence-linked plan: every topic slot names the curriculum
day it came from *and* the signal in the candidate's record that earned it a
slot — "passed on attempt 4", "skipped", "first try". That plan is what powers
the "why did I get this question?" panel, and it is also what guarantees the
coverage the brief requires (>= 8 questions across >= 4 distinct days).

The plan is a starting hypothesis, not a script: the orchestrator reorders,
extends and abandons slots as the conversation goes.
"""

from __future__ import annotations

from ..config import InterviewLimits
from ..data.curriculum import Curriculum, get_curriculum
from ..models.domain import CandidateProfile, SlotKind, TopicSlot

def _spine(curriculum: Curriculum) -> list[int]:
    """Fallback topics when the candidate record says nothing usable.

    Derived from the curriculum rather than hardcoded day numbers, so a
    different cohort's JSON works without editing Python.
    """
    ranked = sorted(curriculum.all_days(), key=lambda d: (-d.interview_weight, d.day))
    return [d.day for d in ranked[:8]]


def _anchors(curriculum: Curriculum) -> tuple[list[int], list[int]]:
    """(synthesis_anchors, reflective_anchors), derived from day metadata.

    Synthesis wants the capstone or the last shipping day; the reflective slot
    wants a day about evaluation, testing or production behaviour. Reserving
    them stops the capstone being spent as a warm-up question.
    """
    days = curriculum.all_days()
    capstone = [d.day for d in days if d.type.upper() == "CAPSTONE"]
    shipping = [d.day for d in sorted(days, key=lambda d: -d.day) if d.type.upper() == "SHIP_IT"]
    # Title-level match only: plenty of build days mention "evaluate retrieval
    # quality" in an objective without being reflective days.
    reflective = [
        d.day
        for d in days
        if any(
            keyword in d.title.lower()
            for keyword in ("evaluat", "testing", "monitor", "observab", "optimis", "optimiz", "readiness")
        )
    ]
    return (capstone + shipping) or [days[-1].day] if days else [], reflective or shipping

_SIGNAL_TEXT = {
    "first_try_pass": "passed on the first attempt",
    "few_attempts": "passed after {n} attempts",
    "high_attempts": "passed only on attempt {n}",
    "failed": "did not pass after {n} attempts",
    "skipped": "skipped this mission",
    "no_history": "not recorded in the learning log",
    "capstone": "shipped the capstone",
}


def _signal_for(candidate: CandidateProfile, day: int) -> tuple[str, str]:
    """Return (signal_code, human_readable_signal)."""
    mission = candidate.mission_for(day)
    if mission is None:
        return "no_history", _SIGNAL_TEXT["no_history"]
    if mission.skipped:
        return "skipped", _SIGNAL_TEXT["skipped"]
    attempts = mission.attempts or 1
    if mission.passed is False:
        return "failed", _SIGNAL_TEXT["failed"].format(n=attempts)
    if attempts <= 1:
        return "first_try_pass", _SIGNAL_TEXT["first_try_pass"]
    if attempts >= 3:
        return "high_attempts", _SIGNAL_TEXT["high_attempts"].format(n=attempts)
    return "few_attempts", _SIGNAL_TEXT["few_attempts"].format(n=attempts)


def _difficulty_for(candidate: CandidateProfile, signal_code: str, base: int) -> int:
    band = candidate.seniority_band()
    seniority_bump = {"junior": -1, "mid": 0, "senior": 1, "principal": 1}[band]
    signal_bump = {
        "first_try_pass": 1,
        "few_attempts": 0,
        "high_attempts": -1,
        "failed": -1,
        "skipped": -1,
        "no_history": 0,
        "capstone": 0,
    }.get(signal_code, 0)
    rate_bump = 1 if candidate.first_try_rate >= 0.75 else (-1 if candidate.first_try_rate < 0.25 else 0)
    return max(1, min(base + seniority_bump + signal_bump + rate_bump, 5))


def _rank(days: list[int], candidate: CandidateProfile, curriculum: Curriculum) -> list[int]:
    """Highest interview signal first, derived from each day's own metadata."""
    def weight(day_no: int) -> float:
        day = curriculum.day(day_no)
        return day.interview_weight if day else 0.8

    return sorted(days, key=lambda d: (-weight(d), d))


def _make_slot(
    *,
    index: int,
    kind: SlotKind,
    day: int,
    candidate: CandidateProfile,
    curriculum: Curriculum,
    base_difficulty: int,
) -> TopicSlot | None:
    info = curriculum.day(day)
    if info is None:
        return None
    signal_code, signal_text = _signal_for(candidate, day)

    # Don't mislabel a slot. A candidate who never struggled has nothing to
    # probe, and a day they didn't skip isn't a gap check — those fall back to
    # ordinary core questions rather than carrying a label the record
    # contradicts.
    if kind is SlotKind.PROBE and signal_code in ("first_try_pass", "no_history"):
        kind = SlotKind.CORE
    elif kind is SlotKind.GAP and signal_code != "skipped":
        kind = SlotKind.CORE

    return TopicSlot(
        slot_id=f"S{index}-D{day}",
        kind=kind,
        day=day,
        day_title=info.title,
        module=info.module_title,
        objectives=list(info.objectives),
        tools=list(info.tools),
        base_difficulty=_difficulty_for(candidate, signal_code, base_difficulty),
        signal=signal_text,
        signal_code=signal_code,
    )


def build_plan(
    candidate: CandidateProfile,
    limits: InterviewLimits,
    curriculum: Curriculum | None = None,
) -> list[TopicSlot]:
    """Compose the topic plan. Deterministic for a given candidate."""
    curriculum = curriculum or get_curriculum()
    known_days = set(curriculum.days)

    strong = _rank([d for d in candidate.first_try_days if d in known_days], candidate, curriculum)
    struggled = _rank([d for d in candidate.struggle_days if d in known_days], candidate, curriculum)
    failed = _rank([d for d in candidate.failed_days if d in known_days], candidate, curriculum)
    skipped = _rank([d for d in candidate.skipped_days if d in known_days], candidate, curriculum)
    attempted = _rank([d for d in candidate.attempted_days if d in known_days], candidate, curriculum)

    spine = _spine(curriculum)
    synthesis_anchors, reflective_anchors = _anchors(curriculum)
    # Held back so the capstone is not spent as a warm-up question.
    reserved = set(synthesis_anchors[:1]) | set(reflective_anchors[:1])

    used: set[int] = set()
    plan: list[TopicSlot] = []
    idx = 0

    def take(pools: list[list[int]], kind: SlotKind, difficulty: int, honour_reserved: bool = True) -> bool:
        nonlocal idx
        # First pass respects the reservation; second pass ignores it rather
        # than leaving a slot empty.
        for avoid in ((reserved if honour_reserved else set()), set()):
            for pool in pools:
                for day in pool:
                    if day in used or day in avoid:
                        continue
                    slot = _make_slot(
                        index=idx, kind=kind, day=day, candidate=candidate,
                        curriculum=curriculum, base_difficulty=difficulty,
                    )
                    if slot is None:
                        continue
                    used.add(day)
                    plan.append(slot)
                    idx += 1
                    return True
        return False

    # 1. Warm-up on ground they own — calibrates their baseline honestly.
    take([strong, attempted, spine], SlotKind.WARMUP, 2)

    # 2-3. Core depth on the highest-signal work they actually completed.
    take([[d for d in attempted if d not in strong], strong, spine], SlotKind.CORE, 3)
    take([attempted, strong, spine], SlotKind.CORE, 3)

    # 4. Probe where the log says they fought for it — the most informative slot.
    take([failed, struggled, attempted, spine], SlotKind.PROBE, 2)

    # 5. Second probe when the record shows a lot of friction.
    if len(struggled) + len(failed) >= 2:
        take([failed, struggled], SlotKind.PROBE, 2)

    # 6. Honest gap check on something they skipped.
    take([skipped], SlotKind.GAP, 2)

    # 7. Synthesis: cross-day system reasoning, anchored on the capstone.
    take([synthesis_anchors, attempted, spine], SlotKind.SYNTHESIS, 4, honour_reserved=False)

    # 8. Reflective slot on evaluation/production behaviour, not invented scenarios.
    take([reflective_anchors, attempted, spine], SlotKind.BEHAVIORAL, 3, honour_reserved=False)

    # Backfill until the coverage floor is provably met.
    fallback_pool = _rank([d for d in known_days if d not in used], candidate, curriculum)
    while len({s.day for s in plan}) < limits.min_distinct_days or len(plan) < 6:
        if not take([attempted, fallback_pool, spine], SlotKind.CORE, 3, honour_reserved=False):
            break

    return plan


def plan_headline(candidate: CandidateProfile, plan: list[TopicSlot]) -> str:
    """One line explaining, in the candidate's terms, why this plan exists."""
    if not plan:
        return "No curriculum data available; running a general AI-engineering interview."
    days = sorted({s.day for s in plan})
    probes = [s for s in plan if s.kind in (SlotKind.PROBE, SlotKind.GAP)]
    bits = [f"{len(plan)} topics across days {', '.join(str(d) for d in days)}"]
    if probes:
        bits.append(
            "including "
            + ", ".join(f"day {s.day} ({s.signal})" for s in probes[:2])
        )
    return "Planned " + "; ".join(bits) + "."
