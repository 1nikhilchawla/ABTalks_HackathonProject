"""Retrieval-driven topic tracking.

Two live uses of the BM25 curriculum index, both inside the interview loop:

1. **Objective targeting** — pick the objective for a day that the candidate has
   said *least* about so far, so a second question on a topic explores new
   ground instead of restating the first.
2. **Volunteered-topic detection** — score every answer against the whole
   curriculum. When a candidate answers a retrieval question by talking about
   MCP, a real interviewer follows them there. This finds that, and the policy
   can pull the matching planned slot forward.

Both are guarded by margin thresholds: retrieval that fires on weak evidence
would make the interview feel erratic rather than attentive.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.curriculum import Day, get_curriculum
from ..models.domain import InterviewState, TopicSlot

#: Minimum absolute BM25 score before a match counts as *substantive* content
#: about that day. This is also the anti-evasion guard: a candidate rambling to
#: dodge a hard question does not accidentally produce six points of BM25
#: against a specific curriculum day, because that requires the day's actual
#: technical vocabulary. The rubric scores cannot do this job — they are
#: computed against the *current* day, so an answer about another topic scores
#: low on every dimension by construction.
MIN_SIGNAL = 6.0
#: How much better the volunteered day must score than the current topic.
MARGIN = 1.7
#: Following the candidate is a moment, not a mode. Every other adaptive path
#: is budgeted (two follow-ups per topic, fourteen questions); without a cap
#: here the plan gets reordered on almost every turn and the interview stops
#: feeling deliberate.
MAX_JUMPS_PER_INTERVIEW = 2


@dataclass(frozen=True)
class VolunteeredTopic:
    day: Day
    slot: TopicSlot
    score: float
    active_score: float

    @property
    def margin(self) -> float:
        return self.score / max(self.active_score, 0.01)


def answers_for_day(state: InterviewState, day: int) -> str:
    """Everything the candidate has said while this day was the active topic."""
    return " ".join(
        turn.text for turn in state.turns if turn.role == "candidate" and turn.day == day
    )


def target_objective(state: InterviewState, day: int) -> str | None:
    """The objective this candidate has covered least on the given day."""
    covered = answers_for_day(state, day)
    curriculum = get_curriculum()
    if not covered.strip():
        ranked = curriculum.rank_objectives(day, "")
        return ranked[0][0] if ranked else None
    return curriculum.least_covered_objective(day, covered)


def detect_volunteered_topic(state: InterviewState, answer: str) -> VolunteeredTopic | None:
    """Did this answer drift onto another *planned* topic worth following?

    The argmax is taken over the **whole curriculum**, not just the plan, and
    only fires if the global winner happens to be a planned slot.

    That distinction is the difference between a delightful behaviour and an
    embarrassing one. Searching only planned slots means an answer entirely
    about MCP — a day that may not be on this candidate's plan at all — still
    returns *something*: the best planned day, which clears the floor on a few
    incidental shared terms. The interviewer then announces "let's move to the
    capstone" about an answer that was not about the capstone. Retrieval was
    right; restricting the argmax made the conclusion wrong.
    """
    active = state.active_slot
    if active is None or len(answer.split()) < 15:
        return None
    if state.volunteered_jumps >= MAX_JUMPS_PER_INTERVIEW:
        return None

    curriculum = get_curriculum()
    followable = {
        slot.day: slot
        for slot in state.plan
        if not slot.closed and slot.questions_asked == 0 and slot.day != active.day
    }
    if not followable:
        return None

    # Global argmax first. If the answer is really about a day we are not going
    # to ask about, the honest response is to say nothing and let the normal
    # drift handling apply — not to jump to the nearest planned neighbour.
    global_best = curriculum.best_day_for(answer)
    if global_best is None or global_best.day not in followable:
        return None

    score = curriculum.score_day(global_best.day, answer)
    active_score = curriculum.score_day(active.day, answer)
    if score < MIN_SIGNAL or score < active_score * MARGIN:
        return None

    return VolunteeredTopic(
        day=global_best,
        slot=followable[global_best.day],
        score=score,
        active_score=active_score,
    )
