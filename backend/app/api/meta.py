"""Supporting endpoints for the UI. None of these are required by the spec."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..data.candidates import demo_candidates, parse_candidate
from ..data.curriculum import get_curriculum
from ..engine.cohort import aggregate
from ..engine.orchestrator import public_state
from ..engine.planner import build_plan
from ..engine.prompts import PERSONAS
from .deps import get_services

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    services = get_services()
    return {
        "status": "ok",
        "llm": services.router.health(),
        "sessions": services.store.stats(),
        "limits": {
            "minQuestions": services.settings.limits.min_questions,
            "maxQuestions": services.settings.limits.max_questions,
            "minDistinctDays": services.settings.limits.min_distinct_days,
        },
    }


@router.get("/candidates")
async def candidates() -> dict[str, Any]:
    roster = demo_candidates()
    return {
        "candidates": [
            {
                "id": c.get("member", {}).get("id"),
                "name": c.get("member", {}).get("name"),
                "role": c.get("member", {}).get("jobRole"),
                "years": c.get("member", {}).get("yearsExperience"),
                "signals": c.get("signals", {}),
                "missionCount": len(c.get("missions", [])),
                "raw": c,
            }
            for c in roster
        ]
    }


@router.get("/curriculum")
async def curriculum() -> dict[str, Any]:
    cur = get_curriculum()
    return {
        "cohort": cur.cohort,
        "modules": cur.modules,
        "days": [d.as_dict() for d in cur.all_days()],
    }


@router.get("/personas")
async def personas() -> dict[str, Any]:
    return {
        "personas": [
            {"id": key, "label": value["label"], "style": value["style"]}
            for key, value in PERSONAS.items()
        ]
    }


@router.post("/preview-plan")
async def preview_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Show the question plan before the interview starts — the 'why' preview."""
    services = get_services()
    candidate = parse_candidate(payload.get("candidate"))
    plan = build_plan(candidate, services.settings.limits)
    return {
        "candidate": {
            "name": candidate.name,
            "role": candidate.job_role,
            "firstTryDays": candidate.first_try_days,
            "struggleDays": candidate.struggle_days,
            "failedDays": candidate.failed_days,
            "skippedDays": candidate.skipped_days,
            "firstTryRate": round(candidate.first_try_rate, 2),
            "parseNotes": candidate.parse_notes,
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
            }
            for s in plan
        ],
    }


@router.get("/cohort/insights")
async def cohort_insights(limit: int = 200) -> dict[str, Any]:
    """Which curriculum days the cohort cannot defend, ranked.

    Computed from finished interviews in Python — no model call, nothing
    generated. This is the artefact cohort staff need, and it is why the
    individual report is not the whole product.
    """
    services = get_services()
    states = services.store.completed_states(limit=max(1, min(limit, 500)))
    return aggregate(states)


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Session recovery after a refresh or a dropped connection."""
    services = get_services()
    state = services.store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session not found or expired")
    return {
        "state": public_state(state, services.settings.limits),
        "transcript": [
            {
                "role": t.role,
                "text": t.text,
                "day": t.day,
                "action": t.action.value if t.action else None,
                "difficulty": t.difficulty,
                "trace": t.trace,
                "evaluation": (
                    {
                        "verdict": t.evaluation.verdict,
                        "composite": t.evaluation.composite,
                        "dimensions": t.evaluation.scores.as_dict(),
                        "flags": t.evaluation.flags,
                        "rationale": t.evaluation.rationale,
                    }
                    if t.evaluation
                    else None
                ),
            }
            for t in state.turns
        ],
        "done": state.done,
        "feedback": state.feedback,
        "report": state.report,
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    services = get_services()
    services.store.delete(session_id)
    return {"deleted": session_id}
