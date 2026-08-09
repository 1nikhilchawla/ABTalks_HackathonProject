"""Tolerant parsing of the candidate payload.

The spec says the candidate object "will follow the provided candidate.json
schema". Real graders send truncated, renamed or partially-typed objects, so
this parser never raises: it extracts what it can, records what it could not,
and marks the profile as a placeholder when nothing usable arrived.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import get_settings
from ..models.domain import CandidateProfile, Mission, Signals

_MAX_MISSIONS = 60
_MAX_STR = 200


def _s(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()[:_MAX_STR]
    return str(value)[:_MAX_STR]


def _i(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _camel_or_snake(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_candidate(payload: Any) -> CandidateProfile:
    notes: list[str] = []

    if payload is None:
        return CandidateProfile(
            is_placeholder=True,
            parse_notes=["no candidate object supplied; running an unprofiled interview"],
        )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
            notes.append("candidate arrived as a JSON string and was decoded")
        except json.JSONDecodeError:
            return CandidateProfile(
                name=_s(payload, "Candidate") or "Candidate",
                is_placeholder=True,
                parse_notes=["candidate was an undecodable string"],
            )

    if isinstance(payload, list):
        # Multiple candidates: take the first, note the ambiguity.
        if not payload:
            return CandidateProfile(is_placeholder=True, parse_notes=["empty candidate list"])
        notes.append(f"received {len(payload)} candidates; used the first")
        payload = payload[0]

    if not isinstance(payload, dict):
        return CandidateProfile(is_placeholder=True, parse_notes=["candidate was not an object"])

    # Accept either {member:{...}} or a flat object.
    member = payload.get("member")
    if not isinstance(member, dict):
        member = payload
        if "member" in payload:
            notes.append("'member' was not an object; read fields from the root")

    profile = CandidateProfile(
        id=_s(_camel_or_snake(member, "id", "candidateId", "candidate_id"), "UNKNOWN") or "UNKNOWN",
        name=_s(_camel_or_snake(member, "name", "fullName", "full_name"), "Candidate") or "Candidate",
        job_role=_s(_camel_or_snake(member, "jobRole", "job_role", "role", "title"), "Engineer")
        or "Engineer",
        years_experience=max(
            0, min(_i(_camel_or_snake(member, "yearsExperience", "years_experience", "yoe"), 0), 60)
        ),
        education=_s(_camel_or_snake(member, "education", "degree"), ""),
        status=_s(_camel_or_snake(member, "status"), "UNKNOWN") or "UNKNOWN",
    )

    raw_missions = _camel_or_snake(payload, "missions", "completedMissions", default=[])
    missions: list[Mission] = []
    if isinstance(raw_missions, list):
        for entry in raw_missions[:_MAX_MISSIONS]:
            if not isinstance(entry, dict):
                continue
            day = _i(_camel_or_snake(entry, "day", "dayNumber", "day_number"), -1)
            if day < 0:
                continue
            passed_raw = _camel_or_snake(entry, "passed", "completed")
            skipped = bool(_camel_or_snake(entry, "skipped", default=False))
            missions.append(
                Mission(
                    day=day,
                    title=_s(_camel_or_snake(entry, "title", "name"), ""),
                    passed=None if passed_raw is None else bool(passed_raw),
                    attempts=(
                        None
                        if _camel_or_snake(entry, "attempts") is None
                        else max(1, min(_i(entry.get("attempts"), 1), 99))
                    ),
                    skipped=skipped,
                )
            )
    else:
        notes.append("'missions' was not a list; treated as empty")

    # De-duplicate by day, keeping the most informative record.
    by_day: dict[int, Mission] = {}
    for m in missions:
        prior = by_day.get(m.day)
        if prior is None or (prior.passed is None and m.passed is not None):
            by_day[m.day] = m
    if len(by_day) != len(missions):
        notes.append("duplicate mission days collapsed")
    profile.missions = [by_day[d] for d in sorted(by_day)]

    raw_signals = _camel_or_snake(payload, "signals", default={}) or {}
    if isinstance(raw_signals, dict):
        profile.signals = Signals(
            commit_days=max(0, min(_i(_camel_or_snake(raw_signals, "commitDays", "commit_days"), 0), 365)),
            missions_completed=max(
                0, min(_i(_camel_or_snake(raw_signals, "missionsCompleted", "missions_completed"), 0), 400)
            ),
            missions_first_try=max(
                0, min(_i(_camel_or_snake(raw_signals, "missionsFirstTry", "missions_first_try"), 0), 400)
            ),
        )
    else:
        notes.append("'signals' was not an object; defaults used")

    if profile.signals.missions_first_try > profile.signals.missions_completed:
        notes.append("missionsFirstTry exceeded missionsCompleted; clamped")
        profile.signals.missions_first_try = profile.signals.missions_completed

    if not profile.missions:
        notes.append("no mission history; interview will cover the core curriculum spine")

    profile.is_placeholder = not profile.missions and profile.name == "Candidate"
    profile.parse_notes = notes
    return profile


@lru_cache(maxsize=1)
def demo_candidates() -> list[dict[str, Any]]:
    """The bundled synthetic roster, used by the UI's candidate picker."""
    try:
        raw = json.loads(get_settings().candidates_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("candidates")
    return items if isinstance(items, list) else []
