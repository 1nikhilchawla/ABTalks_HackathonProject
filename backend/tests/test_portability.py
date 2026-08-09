"""The engine must not be welded to one curriculum.

Nothing in the planner, policy or evaluator may reference a specific day
number. This suite proves it by running the whole planning path against a
completely different 14-day platform-engineering curriculum.
"""

from __future__ import annotations

import json

import pytest

from app.config import APP_ROOT, InterviewLimits
from app.data.candidates import parse_candidate
from app.data.curriculum import _parse
from app.engine.planner import build_plan
from app.models.domain import SlotKind

ALT_PATH = APP_ROOT / "data" / "curriculum.platform.json"


@pytest.fixture(scope="module")
def alt_curriculum():
    return _parse(json.loads(ALT_PATH.read_text(encoding="utf-8")))


ALT_CANDIDATE = {
    "member": {
        "id": "PLAT-001",
        "name": "Rosa Lindqvist",
        "jobRole": "Platform Engineer",
        "yearsExperience": 6,
        "education": "BS Computer Engineering",
        "status": "COMPLETED",
    },
    "missions": [
        {"day": 1, "title": "Toolchain & Shell Setup", "passed": True, "attempts": 1},
        {"day": 4, "title": "Terraform Core Concepts", "passed": True, "attempts": 1},
        {"day": 5, "title": "Remote State & Locking", "passed": True, "attempts": 4},
        {"day": 6, "title": "Secrets Management", "skipped": True},
        {"day": 9, "title": "CI Pipelines", "passed": True, "attempts": 2},
        {"day": 10, "title": "Progressive Delivery", "passed": False, "attempts": 3},
        {"day": 12, "title": "Observability & Incident Response", "passed": True, "attempts": 2},
        {"day": 14, "title": "Capstone", "passed": True, "attempts": 1},
    ],
    "signals": {"commitDays": 12, "missionsCompleted": 13, "missionsFirstTry": 6},
}


def test_alternate_curriculum_loads(alt_curriculum):
    assert len(alt_curriculum.days) == 14
    assert alt_curriculum.day(14).type == "CAPSTONE"


def test_weights_are_derived_not_hardcoded(alt_curriculum):
    """A setup day must rank below a shipping day in any curriculum."""
    setup = alt_curriculum.day(1).interview_weight
    shipping = alt_curriculum.day(10).interview_weight
    capstone = alt_curriculum.day(14).interview_weight
    assert setup < shipping
    assert setup < capstone


def test_plan_on_a_different_curriculum_still_meets_the_brief(alt_curriculum):
    limits = InterviewLimits()
    candidate = parse_candidate(ALT_CANDIDATE)
    plan = build_plan(candidate, limits, curriculum=alt_curriculum)

    days = {s.day for s in plan}
    assert len(days) >= limits.min_distinct_days
    assert days <= set(alt_curriculum.days), "planner invented a day that does not exist"
    assert all(s.day_title for s in plan)


def test_signals_map_correctly_on_a_different_curriculum(alt_curriculum):
    candidate = parse_candidate(ALT_CANDIDATE)
    plan = build_plan(candidate, InterviewLimits(), curriculum=alt_curriculum)
    by_day = {s.day: s for s in plan}

    if 5 in by_day:
        assert by_day[5].signal_code == "high_attempts"  # passed on attempt 4
    if 6 in by_day:
        assert by_day[6].kind is SlotKind.GAP and by_day[6].signal_code == "skipped"
    if 10 in by_day:
        assert by_day[10].signal_code == "failed"


def test_capstone_is_reserved_for_synthesis(alt_curriculum):
    plan = build_plan(parse_candidate(ALT_CANDIDATE), InterviewLimits(), curriculum=alt_curriculum)
    capstone_slots = [s for s in plan if s.day == 14]
    if capstone_slots:
        assert capstone_slots[0].kind is SlotKind.SYNTHESIS, "capstone spent as a warm-up"


def test_retrieval_works_on_the_alternate_curriculum(alt_curriculum):
    hits = alt_curriculum.search("we rolled back a canary deploy when latency spiked", top_k=1)
    assert hits and hits[0][0].day in (10, 12, 11)

    ranked = alt_curriculum.rank_objectives(10, "I set up a canary deployment with Argo Rollouts")
    assert len(ranked) == len(alt_curriculum.day(10).objectives)
    assert ranked[0][1] <= ranked[-1][1]
