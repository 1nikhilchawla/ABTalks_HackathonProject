"""Wire contract for POST /api/interview.

Shape is fixed by the hackathon technical specification:

    request  -> { sessionId, candidate?, message? }
    response -> { reply, done, feedback? }

Everything else we return (``trace``, ``state``) is additive and optional, so a
grader that only reads ``reply``/``done``/``feedback`` sees exactly the spec.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InterviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str = Field(alias="sessionId", min_length=1, max_length=200)
    candidate: dict[str, Any] | None = None
    message: str | None = None

    @field_validator("session_id")
    @classmethod
    def _clean_session_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("sessionId must not be blank")
        return v


class Feedback(BaseModel):
    """The exact final-feedback object required by the spec."""

    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next: list[str] = Field(default_factory=list)


class InterviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reply: str
    done: bool = False
    feedback: Feedback | None = None

    # --- additive, spec-compatible extras used by our own UI --------------
    trace: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    report: dict[str, Any] | None = None

    def spec_only(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"reply": self.reply, "done": self.done}
        if self.feedback is not None:
            payload["feedback"] = self.feedback.model_dump()
        return payload
