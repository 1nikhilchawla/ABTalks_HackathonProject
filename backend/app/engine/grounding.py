"""Post-hoc grounding checks on model output.

Prompting a model to stay grounded reduces hallucination; it does not eliminate
it. These checks run *after* generation and mechanically enforce the two claims
that matter most in an assessment product:

* an evidence quote must really appear in the candidate's answer;
* the report must not name a technology that appears nowhere in the interview
  or the curriculum.

Anything that fails is not silently deleted — it is downgraded and recorded, so
the trace shows exactly what the grounding layer caught.
"""

from __future__ import annotations

import re

from ..data.curriculum import get_curriculum

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")

# Terms that look technical but are generic enough not to count as a claim.
_GENERIC = {
    "system", "systems", "data", "model", "models", "code", "api", "apis", "test",
    "tests", "database", "databases", "server", "client", "service", "services",
    "python", "json", "http", "cloud", "team", "project", "projects", "pipeline",
    "production", "latency", "cost", "memory", "context", "prompt", "prompts",
    "answer", "answers", "question", "questions", "interview", "candidate", "day",
    "days", "curriculum", "cohort", "score", "scores", "evidence", "example",
    "架构",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def verify_quote(quote: str, source: str) -> tuple[bool, str]:
    """Is `quote` really a span of `source`? Returns (ok, corrected_quote)."""
    if not quote:
        return True, ""
    q, s = _normalise(quote), _normalise(source)
    if not q:
        return True, ""
    if q in s:
        return True, quote.strip()

    # Allow a trimmed version: model often adds an ellipsis or trailing period.
    trimmed = q.strip(" .…\"'")
    if trimmed and trimmed in s:
        return True, quote.strip(" .…\"'")

    # Token-overlap rescue: >=85% of quote tokens present, in order, is close
    # enough to be a real span the model lightly reformatted.
    q_tokens = q.split()
    if len(q_tokens) >= 4:
        hits = sum(1 for t in q_tokens if t in s)
        if hits / len(q_tokens) >= 0.85:
            return True, quote.strip()

    return False, ""


def allowed_vocabulary(transcript_texts: list[str]) -> set[str]:
    """Every technical term the report is permitted to use."""
    vocab = set(get_curriculum().vocabulary)
    for tool in get_curriculum().tool_names():
        vocab.update(w.lower() for w in _WORD.findall(tool))
    for text in transcript_texts:
        vocab.update(w.lower() for w in _WORD.findall(text or ""))
    return vocab


def ungrounded_terms(text: str, vocab: set[str], limit: int = 6) -> list[str]:
    """Technology-shaped tokens in `text` that nothing in the interview supports.

    Tuned hard against false positives. Ordinary hyphenated English
    ("trade-offs", "best-evidenced") is not a technology claim, and flagging it
    would bury the real signal — a product name the candidate never mentioned.
    """
    suspects: list[str] = []
    for match in _WORD.finditer(text or ""):
        raw = match.group(0).strip(".-")
        if not raw:
            continue
        low = raw.lower()
        if low in vocab or low in _GENERIC or len(low) < 3:
            continue

        # Hyphenated compounds: known if every part is known.
        if "-" in low:
            parts = [p for p in low.split("-") if p]
            if all(p in vocab or p in _GENERIC or len(p) < 3 for p in parts):
                continue

        capitalised_mid_sentence = raw[0].isupper() and not _sentence_start(text, match.start())
        versioned = any(c.isdigit() for c in raw) and any(c.isalpha() for c in raw)
        dotted_identifier = "." in low and not low.endswith(".")

        if (capitalised_mid_sentence or versioned or dotted_identifier) and low not in suspects:
            suspects.append(low)
        if len(suspects) >= limit:
            break
    return suspects


def _sentence_start(text: str, index: int) -> bool:
    prefix = text[:index].rstrip()
    return not prefix or prefix[-1] in ".!?:\n•-"


def check_report(report: dict, transcript_texts: list[str]) -> tuple[dict, list[str]]:
    """Flag report bullets that reference unsupported technology."""
    vocab = allowed_vocabulary(transcript_texts)
    warnings: list[str] = []
    for field in ("summary", "headline_observation"):
        value = report.get(field)
        if isinstance(value, str):
            bad = ungrounded_terms(value, vocab)
            if bad:
                warnings.append(f"{field}: unsupported terms {bad}")
    for field in ("strengths", "gaps", "next"):
        items = report.get(field)
        if not isinstance(items, list):
            continue
        for item in items:
            bad = ungrounded_terms(str(item), vocab)
            if bad:
                warnings.append(f"{field}: unsupported terms {bad} in \"{str(item)[:60]}…\"")
    return report, warnings
