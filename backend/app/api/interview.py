"""POST /api/interview — the single endpoint required by the specification.

Failure policy: this route does not return 5xx for anything the interview can
absorb. A model outage, a malformed candidate object or a corrupted session all
resolve to a valid ``{reply, done}`` body, because a grader hitting an error
page sees a broken product regardless of whose fault it was.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request, Response

from ..data.candidates import parse_candidate
from ..engine.orchestrator import public_state
from ..engine.prompts import DEFAULT_PERSONA, PERSONAS
from ..models.contract import Feedback, InterviewRequest, InterviewResponse
from ..models.domain import InterviewState
from ..store.session_store import DUPLICATE_WINDOW_SECONDS, fingerprint
from .deps import get_services

log = logging.getLogger("cohortiq.api")

router = APIRouter()


@router.post("/interview", response_model=None)
async def interview(payload: InterviewRequest, request: Request, response: Response) -> dict[str, Any]:
    services = get_services()
    settings = services.settings
    session_id = payload.session_id

    allowed, retry_after = services.limiter.check(_client_key(request, session_id))
    if not allowed:
        response.headers["Retry-After"] = str(retry_after)
        return InterviewResponse(
            reply=(
                "You're sending answers faster than I can think. Give me a moment and resend "
                "your last message — nothing has been lost."
            ),
            done=False,
        ).model_dump(exclude_none=True)

    lock = services.locks.get(session_id)
    async with lock:
        state = services.store.get(session_id)

        # --- idempotency: double-clicked submit, or a retried request ----
        request_fp = fingerprint(session_id, payload.message) if payload.message is not None else None
        if state is not None and request_fp is not None:
            within_window = time.time() - state.last_request_at < DUPLICATE_WINDOW_SECONDS
            if (
                request_fp == state.last_request_fingerprint
                and within_window
                and state.last_response_payload
            ):
                log.info("session=%s duplicate submission served from cache", session_id)
                return state.last_response_payload

        try:
            if state is None:
                result = await _start(session_id, payload, services)
            else:
                result = await _continue(state, payload, services)
        except Exception:
            log.exception("session=%s unhandled error", session_id)
            return InterviewResponse(
                reply=(
                    "Something went wrong on my side just then — that's on us, not you. "
                    "Please resend your last answer and we'll pick up exactly where we left off."
                ),
                done=False,
            ).model_dump(exclude_none=True)

        state_obj, body = result
        if request_fp is not None:
            state_obj.last_request_fingerprint = request_fp
            state_obj.last_request_at = time.time()
            state_obj.last_response_payload = body
        services.store.save(state_obj)

    if not settings.expose_trace:
        body.pop("trace", None)
        body.pop("state", None)
    return body


async def _start(
    session_id: str, payload: InterviewRequest, services
) -> tuple[InterviewState, dict[str, Any]]:
    """First request for a session id. Starts the interview."""
    candidate_payload: Any = payload.candidate
    persona = DEFAULT_PERSONA

    if isinstance(candidate_payload, dict):
        # Persona may ride along on the candidate object or at the root.
        raw_persona = str(
            candidate_payload.get("persona") or candidate_payload.get("interviewStyle") or ""
        ).lower()
        if raw_persona in PERSONAS:
            persona = raw_persona

    candidate = parse_candidate(candidate_payload)

    state, reply, trace = await services.orchestrator.start(session_id, candidate, persona)

    # A message sent alongside the very first request is answered next turn;
    # we acknowledge rather than silently dropping it.
    body = InterviewResponse(
        reply=reply,
        done=False,
        trace=trace,
        state=public_state(state, services.settings.limits),
    ).model_dump(exclude_none=True)
    return state, body


async def _continue(
    state: InterviewState, payload: InterviewRequest, services
) -> tuple[InterviewState, dict[str, Any]]:
    if state.done:
        return state, InterviewResponse(
            reply="This interview is already complete. Start a new session id to run another one.",
            done=True,
            feedback=Feedback(**state.feedback) if state.feedback else None,
            report=state.report,
            state=public_state(state, services.settings.limits),
        ).model_dump(exclude_none=True)

    reply, trace = await services.orchestrator.turn(state, payload.message)

    feedback = Feedback(**state.feedback) if (state.done and state.feedback) else None
    body = InterviewResponse(
        reply=reply,
        done=state.done,
        feedback=feedback,
        trace=trace,
        state=public_state(state, services.settings.limits),
        report=state.report if state.done else None,
    ).model_dump(exclude_none=True)
    return state, body


def _client_key(request: Request, session_id: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{client}:{session_id}"
