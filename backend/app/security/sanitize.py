"""Untrusted-input handling.

Everything the candidate types — and every field of the candidate object — is
attacker-controlled. Two defences are layered here:

1.  *Structural*: candidate text is never concatenated into a system prompt. It
    is delivered inside an XML-ish envelope in a user-role message, and every
    prompt states that envelope contents are data.
2.  *Detective*: obvious instruction-injection is scored and reported, so the
    orchestrator can respond in-character ("that isn't how this works") and the
    UI can show that the attempt was caught rather than silently obeyed.

Detection is heuristic and deliberately non-blocking: a false positive must not
end an interview, so a hit only annotates the turn.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_INPUT_CHARS = 6000

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("override_instructions", re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b[^.\n]{0,20}\b(instruction|prompt|rule|direction)", re.I)),
    ("role_hijack", re.compile(r"\b(you are now|act as|pretend to be|from now on you)\b", re.I)),
    ("score_manipulation", re.compile(r"\b(give|award|assign|set)\b[^.\n]{0,30}\b(perfect|full|maximum|100|10/10|highest)\b[^.\n]{0,20}\b(score|mark|rating|grade)", re.I)),
    ("score_manipulation", re.compile(r"\b(pass|hire|approve)\s+me\b|\brate me\s+(100|10/10|perfect)", re.I)),
    # Note the required exfiltration verb: candidates legitimately discuss
    # "the system prompt I wrote", and flagging that would be a false accusation.
    ("system_prompt_exfil", re.compile(r"\b(show|print|reveal|repeat|output|tell)\b[^.\n]{0,20}\b(your|the)\b[^.\n]{0,20}\b(system prompt|initial instructions|instructions|rules)\b", re.I)),
    ("system_prompt_exfil", re.compile(r"\byour (system prompt|initial instructions)\b", re.I)),
    ("fake_authority", re.compile(r"\b(as the (admin|developer|system)|developer mode|admin override|sudo mode)\b", re.I)),
    ("delimiter_break", re.compile(r"</?(system|assistant|instructions|candidate_answer)>", re.I)),
    ("end_interview_forgery", re.compile(r"\b(interview (is )?(over|complete|finished)[,.]? (give|output|return))\b", re.I)),
)

_CONTROL_CHARS = {ord(c): None for c in map(chr, range(0, 32)) if c not in "\n\t\r"}
_ZERO_WIDTH = re.compile(r"[​-‏  ‪-‮﻿]")


@dataclass(frozen=True)
class SanitizedInput:
    text: str
    original_length: int
    truncated: bool
    injection_hits: tuple[str, ...]
    is_empty: bool

    @property
    def injection_detected(self) -> bool:
        return bool(self.injection_hits)


def sanitize(raw: str | None, max_chars: int = MAX_INPUT_CHARS) -> SanitizedInput:
    if raw is None:
        return SanitizedInput("", 0, False, (), True)

    text = str(raw)
    original_length = len(text)

    # Normalise first so homoglyph/zero-width tricks cannot hide keywords.
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.translate(_CONTROL_CHARS)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = text.strip()

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …[truncated]"
        truncated = True

    hits: list[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(text) and name not in hits:
            hits.append(name)

    return SanitizedInput(
        text=text,
        original_length=original_length,
        truncated=truncated,
        injection_hits=tuple(hits),
        is_empty=not text,
    )


def envelope(text: str, tag: str = "candidate_answer") -> str:
    """Wrap untrusted text so the model can see exactly where data begins/ends."""
    safe = text.replace(f"</{tag}>", f"<​/{tag}>")
    return f"<{tag}>\n{safe}\n</{tag}>"


def scrub_for_log(text: str, limit: int = 160) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat[:limit] + ("…" if len(flat) > limit else "")
