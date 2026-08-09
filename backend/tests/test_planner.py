"""The plan must satisfy the brief for every candidate in the roster."""

from __future__ import annotations

import pytest

from app.data.candidates import parse_candidate
from app.engine.planner import build_plan
from app.models.domain import SlotKind


def test_every_roster_candidate_gets_a_compliant_plan(roster, limits):
    assert roster, "demo roster should load"
    for entry in roster:
        candidate = parse_candidate(entry)
        plan = build_plan(candidate, limits)
        days = {s.day for s in plan}

        assert len(days) >= limits.min_distinct_days, f"{candidate.id} covered only {days}"
        assert len(plan) >= 6, f"{candidate.id} produced {len(plan)} slots"
        assert len(days) == len(plan), f"{candidate.id} planned a duplicate day"
        assert all(1 <= s.base_difficulty <= 5 for s in plan)
        assert all(s.signal for s in plan), "every slot must carry an evidence signal"


def test_plan_capacity_can_reach_the_question_floor(roster, limits):
    """Slots x (1 + follow-ups) must be able to fund the minimum question count."""
    for entry in roster:
        candidate = parse_candidate(entry)
        plan = build_plan(candidate, limits)
        capacity = len(plan) * (1 + limits.max_followups_per_topic)
        assert capacity >= limits.min_questions


def test_struggle_days_are_probed(roster, limits):
    """A candidate with a failed mission should be asked about it."""
    entry = next(c for c in roster if c["member"]["id"] == "CAND-010")  # has failures
    candidate = parse_candidate(entry)
    plan = build_plan(candidate, limits)
    probe_days = {s.day for s in plan if s.kind is SlotKind.PROBE}
    assert probe_days & set(candidate.failed_days + candidate.struggle_days)


def test_skipped_day_becomes_a_gap_check(roster, limits):
    entry = next(c for c in roster if c["member"]["id"] == "CAND-006")  # skipped 27 and 28
    candidate = parse_candidate(entry)
    plan = build_plan(candidate, limits)
    gap = [s for s in plan if s.kind is SlotKind.GAP]
    assert gap, "skipped missions should produce a gap slot"
    assert gap[0].day in candidate.skipped_days
    assert gap[0].signal_code == "skipped"


def test_first_try_candidate_is_pushed_harder(roster, limits):
    strong = parse_candidate(next(c for c in roster if c["member"]["id"] == "CAND-018"))
    weak = parse_candidate(next(c for c in roster if c["member"]["id"] == "CAND-010"))
    strong_avg = sum(s.base_difficulty for s in build_plan(strong, limits))
    weak_avg = sum(s.base_difficulty for s in build_plan(weak, limits))
    assert strong_avg > weak_avg


def test_plan_is_deterministic(roster, limits):
    candidate = parse_candidate(roster[0])
    a = [s.slot_id for s in build_plan(candidate, limits)]
    b = [s.slot_id for s in build_plan(candidate, limits)]
    assert a == b


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"member": None, "missions": "not-a-list"},
        {"member": {"name": 42}, "missions": [{"day": "seven"}], "signals": []},
        [],
        "garbage",
    ],
)
def test_broken_candidate_payloads_still_plan(payload, limits):
    candidate = parse_candidate(payload)
    plan = build_plan(candidate, limits)
    assert len({s.day for s in plan}) >= limits.min_distinct_days
