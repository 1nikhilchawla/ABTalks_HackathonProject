"""JSON schemas for every structured model call.

These are the contract between the engine and whatever model is behind the
router. Keeping them in one file makes it obvious that the model is never asked
for free-form prose that we then have to guess at.
"""

from __future__ import annotations

from typing import Any

_SCORE = {"type": "integer", "minimum": 0, "maximum": 100}

ANSWER_EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "description": "0-100 per dimension.",
            "properties": {
                "technical_accuracy": _SCORE,
                "conceptual_depth": _SCORE,
                "specificity": _SCORE,
                "communication": _SCORE,
                "practical_evidence": _SCORE,
                "relevance": _SCORE,
            },
            "required": [
                "technical_accuracy", "conceptual_depth", "specificity",
                "communication", "practical_evidence", "relevance",
            ],
        },
        "verdict": {"type": "string", "enum": ["strong", "adequate", "weak", "non_answer"]},
        "rationale": {
            "type": "string",
            "description": "Two sentences max, referring only to what the candidate actually said.",
        },
        "evidence_quote": {
            "type": "string",
            "description": "A verbatim span from the answer that justifies the verdict. Empty if none.",
        },
        "missing_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Curriculum-grounded points the answer omitted.",
        },
        "claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Factual claims the candidate made about their own work.",
        },
        "flags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "vague_language", "buzzword_heavy", "rambling", "too_short",
                    "no_concrete_metrics", "possibly_off_topic", "memorised_sounding",
                    "contradicts_earlier", "overclaiming", "non_answer",
                ],
            },
        },
        "followup_hook": {
            "type": "string",
            "description": "The single most interesting thing to probe next, in the candidate's own words.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["scores", "verdict", "rationale", "flags", "followup_hook", "confidence"],
}


INTERVIEW_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "acknowledgement": {
            "type": "string",
            "description": "At most one short sentence reacting to the previous answer. May be empty.",
        },
        "question": {
            "type": "string",
            "description": "The question to ask. One question only. No preamble, no numbering.",
        },
        "internal_note": {
            "type": "string",
            "description": "One short line on what this question is testing. Not shown verbatim to the candidate.",
        },
    },
    "required": ["question", "acknowledgement", "internal_note"],
}


FINAL_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "3-5 sentences. Specific to this interview. No generic praise.",
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "next": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete, doable preparation actions tied to named curriculum days.",
        },
        "headline_observation": {
            "type": "string",
            "description": "The one sentence a hiring manager would remember about this candidate.",
        },
    },
    "required": ["summary", "strengths", "gaps", "next", "headline_observation"],
}
