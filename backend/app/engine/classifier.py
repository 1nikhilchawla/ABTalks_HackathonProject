"""Classify what the candidate just did, before spending a model call on it.

Meta-behaviour ("repeat that", "skip", "can I ask you something") is cheap to
recognise with rules and expensive to get wrong with a model — a mis-scored
"can you repeat the question?" poisons the whole evaluation. So rules decide
the category, and the model is only asked to judge genuine answers.
"""

from __future__ import annotations

import re

from ..models.domain import Utterance
from ..security.sanitize import SanitizedInput

_PATTERNS: tuple[tuple[Utterance, re.Pattern[str]], ...] = (
    (Utterance.END_REQUEST, re.compile(r"\b(end|stop|finish|quit|terminate)\s+(the\s+)?interview\b|\bi'?m done\b|\bthat'?s enough\b", re.I)),
    (Utterance.REQUEST_REPEAT, re.compile(r"\b(repeat|say that again|come again|what was the question|didn'?t catch|missed that|pardon)\b", re.I)),
    (Utterance.REQUEST_SKIP, re.compile(r"\b(skip|pass|move on|next question|can we move)\b", re.I)),
    (Utterance.REQUEST_HINT, re.compile(r"\b(hint|nudge|point me|give me a clue|any pointers|help me out)\b", re.I)),
    (Utterance.REFUSAL, re.compile(r"\b(i (won'?t|refuse|prefer not)|not answering|none of your business|why should i)\b", re.I)),
    (Utterance.DONT_KNOW, re.compile(r"^\s*(i\s+)?(don'?t|do not|dont)\s+know\b|^\s*no idea\b|^\s*not sure\b|^\s*never (used|heard of|done)\b|^\s*n/?a\.?\s*$|^\s*pass\.?\s*$", re.I)),
)

# A trailing question mark alone is not a meta-question — candidates think out
# loud. We require a second-person address to the interviewer.
_META_QUESTION = re.compile(
    # No trailing \b: several alternatives end on a word stem ("scor") on
    # purpose, so that scoring/scored/scores all match.
    r"\b(?:"
    r"what do you (?:think|mean)"
    r"|can you (?:explain|tell me|clarify) (?:what|why|how)"
    r"|are you (?:an? )?(?:ai|bot|human|model|real person)"
    r"|who are you"
    r"|how (?:are|do) you (?:scor|evaluat|grad|judg|mark|assess)"
    r"|why (?:are|did) you ask"
    r"|what (?:company|role|job|position) is this"
    r"|how (?:many|much|long) (?:questions|more|left|is left)"
    r"|(?:what'?s|what is|what was) (?:my|the) (?:score|rating|result)"
    r"|how (?:am i doing|did i do)"
    r")",
    re.I,
)

_MIN_ANSWER_WORDS = 3


def classify(inp: SanitizedInput) -> Utterance:
    if inp.is_empty:
        return Utterance.EMPTY

    text = inp.text
    words = len(text.split())

    if inp.injection_detected:
        return Utterance.MANIPULATION

    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            # A long message that merely contains "skip" mid-sentence is still
            # an answer; short ones are the real signal.
            if kind in (Utterance.REQUEST_SKIP, Utterance.REQUEST_HINT, Utterance.REQUEST_REPEAT) and words > 25:
                continue
            if kind is Utterance.DONT_KNOW and words > 30:
                continue
            return kind

    if _META_QUESTION.search(text) and words <= 40:
        return Utterance.META_QUESTION

    if words < _MIN_ANSWER_WORDS:
        # "yes", "ok", "sure" — technically text, practically a non-answer.
        if re.fullmatch(r"[\W_]*(ok(ay)?|yes|no|sure|right|yeah|hmm+|\.{1,3})[\W_]*", text, re.I):
            return Utterance.EMPTY

    return Utterance.ANSWER


def is_non_answer(kind: Utterance) -> bool:
    return kind is not Utterance.ANSWER
