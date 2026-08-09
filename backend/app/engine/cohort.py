"""Cohort-level aggregation.

The individual report helps one learner. This is the artefact the people who
*run* the cohort actually need: which curriculum days nobody can defend under
questioning, ranked, with the weakest real answer attached to each.

It is computed from finished interviews only, entirely in Python — no model
call, nothing generated. A day appears here because people scored badly on it,
not because a model decided it looked weak.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..data.curriculum import get_curriculum
from ..models.domain import InterviewState
from .reporter import build_evidence

#: Below this many interviews a day's mean is noise, not a finding.
MIN_SAMPLES_FOR_RANKING = 2


def aggregate(states: list[InterviewState]) -> dict[str, Any]:
    curriculum = get_curriculum()
    completed = [s for s in states if s.done]

    by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)
    signal_counts: dict[str, int] = defaultdict(int)
    flag_counts: dict[str, int] = defaultdict(int)
    overall_scores: list[int] = []
    injection_attempts = 0

    for state in completed:
        evidence = build_evidence(state)
        overall_scores.append(evidence["overall"])
        injection_attempts += state.injection_attempts

        quotes_by_turn = {q["turn"]: q["text"] for q in evidence["quotes"]}
        for topic in evidence["per_topic"]:
            weakest_quote = _weakest_quote(state, topic["slotId"], quotes_by_turn)
            by_day[topic["day"]].append(
                {
                    "candidate": state.candidate.name,
                    "score": topic["score"],
                    "signal": topic["signal"],
                    "signalCode": topic["signalCode"],
                    "flags": topic["flags"],
                    "quote": weakest_quote,
                }
            )
            signal_counts[topic["signalCode"]] += 1
            for flag in topic["flags"]:
                flag_counts[flag] += 1

    days: list[dict[str, Any]] = []
    for day_no, rows in by_day.items():
        info = curriculum.day(day_no)
        scores = [r["score"] for r in rows]
        worst = min(rows, key=lambda r: r["score"])
        days.append(
            {
                "day": day_no,
                "title": info.title if info else f"Day {day_no}",
                "module": info.module_title if info else "",
                "interviews": len(rows),
                "meanScore": int(sum(scores) / len(scores)),
                "minScore": min(scores),
                "maxScore": max(scores),
                "belowBar": sum(1 for s in scores if s < 55),
                "weakestQuote": worst["quote"],
                "weakestCandidate": worst["candidate"],
                "commonFlags": sorted({f for r in rows for f in r["flags"]})[:4],
            }
        )

    days.sort(key=lambda d: (d["meanScore"], -d["interviews"]))
    ranked = [d for d in days if d["interviews"] >= MIN_SAMPLES_FOR_RANKING]

    return {
        "interviews": len(completed),
        "meanOverall": int(sum(overall_scores) / len(overall_scores)) if overall_scores else 0,
        "daysCovered": len(days),
        "days": days,
        "weakestDays": ranked[:5],
        "strongestDays": list(reversed(ranked[-3:])) if ranked else [],
        "signalMix": dict(sorted(signal_counts.items(), key=lambda kv: -kv[1])),
        "commonFlags": dict(sorted(flag_counts.items(), key=lambda kv: -kv[1])[:6]),
        "injectionAttempts": injection_attempts,
        "minSamplesForRanking": MIN_SAMPLES_FOR_RANKING,
    }


def _weakest_quote(
    state: InterviewState, slot_id: str, quotes_by_turn: dict[int, str]
) -> str:
    """The verbatim moment that best explains a low score for this topic."""
    turns = [
        t
        for t in state.answered_turns()
        if t.slot_id == slot_id and t.evaluation is not None
    ]
    if not turns:
        return ""
    worst = min(turns, key=lambda t: t.evaluation.composite)  # type: ignore[union-attr]
    return quotes_by_turn.get(worst.index) or worst.text[:220]
