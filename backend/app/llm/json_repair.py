"""Salvage JSON from imperfect model output.

Models emit fenced blocks, prose preambles, trailing commas and smart quotes.
Each repair below is applied only if the cheaper one already failed, so a clean
response costs a single ``json.loads``.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _balanced_span(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort dict extraction. Returns None when nothing is recoverable."""
    if not text:
        return None

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)

    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    span = _balanced_span(text, "{", "}")
    if span:
        candidates.append(span)

    for raw in candidates:
        for attempt in (raw, _repair(raw)):
            try:
                parsed = json.loads(attempt)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0]
    return None


def _repair(raw: str) -> str:
    fixed = raw.translate(_SMART_QUOTES)
    fixed = _TRAILING_COMMA_RE.sub(r"\1", fixed)
    # Unterminated string / object: close what is open.
    opens = fixed.count("{") - fixed.count("}")
    if fixed.count('"') % 2 == 1:
        fixed += '"'
    if opens > 0:
        fixed += "}" * opens
    brackets = fixed.count("[") - fixed.count("]")
    if brackets > 0:
        fixed += "]" * brackets
    return fixed


def coerce_int(value: Any, default: int, lo: int = 0, hi: int = 100) -> int:
    try:
        if isinstance(value, bool):
            return default
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(n, hi))


def coerce_float(value: Any, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(n, hi))


def coerce_str_list(value: Any, limit: int = 8, max_len: int = 400) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            item = item.get("text") or item.get("value") or json.dumps(item)[:max_len]
        s = str(item).strip()
        if s:
            out.append(s[:max_len])
    return out


def coerce_text(value: Any, default: str = "", max_len: int = 4000) -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return default
    s = str(value).strip()
    return (s[:max_len] or default)
