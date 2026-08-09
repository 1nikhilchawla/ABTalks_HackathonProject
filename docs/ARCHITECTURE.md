# Architecture

## The one design decision everything else follows from

**The model writes questions. The machine decides which question to write.**

An interview is a control-flow problem wearing a conversation's clothes. Hand control flow to an LLM
and you get the failure modes every judge has seen: it re-asks a question, it follows up forever on
one topic, it ends after three questions, or it awards a perfect score to a candidate who told it to.

So the pipeline splits cleanly:

| Deterministic (Python) | Generated (LLM) |
| --- | --- |
| Which topic comes next, and why | The wording of the question |
| When to follow up vs. move on | The rubric judgement of an answer |
| Difficulty adjustment | The prose of the final assessment |
| Whether the interview ends | — |
| Utterance classification ("skip", "repeat", injection) | — |
| Every number in the dashboard | — |

Consequences: the interview provably terminates, coverage floors are guaranteed rather than hoped
for, meta-behaviour is handled without a model call, and the whole engine is unit-testable without a
network.

---

## Request lifecycle

```
POST /api/interview
  ├─ rate limit (per client + session)
  ├─ per-session async lock          ← serialises a double-clicked submit
  ├─ idempotency check               ← same message within 8s ⇒ cached reply
  ├─ load InterviewState from SQLite
  │
  ├─ sanitize(message)               ← NFKC, zero-width strip, cap, injection scan
  ├─ classify(utterance)             ← ANSWER | DONT_KNOW | REQUEST_SKIP | META_QUESTION | …
  │
  ├─ if ANSWER:  evaluate(answer)    ← model call #1, structured rubric
  │              verify quote        ← grounding: quote must be a real substring
  │              record claims       ← claim ledger
  │              contradiction check ← lexical, conservative
  │
  ├─ policy.decide(state, utterance, evaluation) → Decision
  │
  ├─ if END_INTERVIEW: build evidence pack → report (model call #2)
  ├─ else:             generate question   (model call #1 of the next turn)
  │                    repetition guard    ← regenerate once, then template
  │
  ├─ commit turn, update coverage/difficulty/summary
  └─ save state, return { reply, done, feedback?, trace, state }
```

Typical cost: **two model calls per turn** (evaluate + generate), one extra at the end for the
report. Prompt size stays roughly flat after turn six because old context is compressed into a
deterministic rolling summary rather than resent.

---

## Interview state

One serialisable object, which is what makes the interview resumable, testable and cheap to persist.

```
InterviewState
├── candidate: CandidateProfile      normalised; derived first_try/struggle/failed/skipped days
├── plan: [TopicSlot]                day, kind, signal, signal_code, difficulty, counters
├── active_slot_id, stage, difficulty
├── turns: [Turn]                    role, text, action, difficulty, utterance, evaluation, trace
├── claims: [Claim]                  ASSERTED → PROBED → SUBSTANTIATED | UNSUPPORTED | CONTRADICTED
├── questions_asked, consecutive_{weak,strong,non_answers}, injection_attempts
├── pending_question                 the last real question (so "repeat that" can't drift)
├── rolling_summary                  deterministic compression of old turns
└── last_request_fingerprint/at      idempotency
```

---

## Planning: from learning record to question plan

`engine/planner.py` maps the candidate's mission history onto curriculum days.

| Signal in the record | Code | Effect |
| --- | --- | --- |
| Passed, 1 attempt | `first_try_pass` | Eligible for warm-up/core; **+1 difficulty** — don't lob a soft ball |
| Passed, 2 attempts | `few_attempts` | Standard implementation question |
| Passed, ≥3 attempts | `high_attempts` | **Probe slot**, −1 difficulty: understood it, or brute-forced it? |
| Not passed | `failed` | **Probe slot**: fair, answerable, find what blocked them |
| Skipped | `skipped` | **Gap slot**: honest check on whether they picked it up elsewhere |
| Absent from record | `no_history` | Neutral, calibrate gently |

Slot order: `WARMUP → CORE ×2 → PROBE (→ PROBE) → GAP → SYNTHESIS → REFLECTIVE`, backfilled until
≥ 4 distinct days and ≥ 6 slots. Difficulty seeds from seniority band + signal + first-try rate, then
adapts live.

**Topic weights are derived, not hardcoded.** Each day's interview weight comes from its own `type`
(`SETUP` 0.35 … `AI_CORE` 1.30) plus how many distinct concept families it touches (retrieval,
agents, MCP, evaluation, security, deployment …), capped so a day listing six vector-database tools
does not out-rank a day that genuinely spans three areas. The synthesis slot reserves the `CAPSTONE`
day and the reflective slot reserves an evaluation/monitoring day, so the capstone is never spent as
a warm-up question. Nothing in the planner references a day *number* — which is what makes
`tests/test_portability.py` able to run the whole path against a different curriculum.

The plan is a hypothesis, not a script: the policy reorders, extends and abandons slots as it goes.

---

## The state machine

**Stages:** `INTRO → WARMUP → CORE → PROBE → GAP → SYNTHESIS → WRAP → COMPLETE`

**Actions:** `ASK_NEW_TOPIC · FOLLOW_UP · CHALLENGE_CLAIM · INCREASE_DIFFICULTY ·
DECREASE_DIFFICULTY · CLARIFY · GIVE_HINT · REDIRECT · HANDLE_META · END_TOPIC · END_INTERVIEW`

Decision order in `policy.decide` (first match wins):

1. **Hard guards** — turn budget, question budget, honoured end request.
2. **Process events** — repeat / meta-question / injection / hint. Always serviced, never consume
   the question budget, never scored. A candidate who asks "can you repeat that?" while
   disengaged still gets their question back.
3. **Disengagement** — after `max_consecutive_non_answers`, move to new ground (or end, if coverage
   is already met).
4. **Adaptation** — strong ⇒ raise difficulty; unsupported-claim flags ⇒ challenge; drift ⇒ redirect;
   weak ⇒ drop to fundamentals (twice weak ⇒ change topic); adequate ⇒ probe specifics.
5. **Coverage floor** — if closing this topic would make 8 questions unreachable, deepen instead of
   moving on. This is why a candidate who answers everything perfectly still gets 8+ questions.

Every decision carries a `reason_code` that the UI renders verbatim in "Why this question?".

### Structured decision record

```json
{
  "intent": "CHALLENGE_CLAIM",
  "topic": "The Retrieval & Matching Engine",
  "day": 10,
  "difficulty": 4,
  "reason_code": "claim_requires_validation:no_concrete_metrics",
  "question_type": "claim_verification",
  "confidence": 0.82,
  "evidence": ["I improved the retrieval accuracy a lot"]
}
```

---

## Evaluation

Six dimensions, 0–100, weighted into a composite: technical accuracy (0.26), conceptual depth (0.24),
specificity (0.18), practical evidence (0.14), communication (0.12), relevance (0.06).

The evaluator prompt is **identical across all five personas** — a "friendly" interview and a
"pressure" interview must produce comparable scores, or the persona feature is a scoring bug.

Model output is never trusted as returned. `engine/evaluator.py` clamps every score into range,
falls back to a composite-derived verdict if the returned one is invalid, discards flags outside the
enum, forces low scores when the verdict is `non_answer`, and drops the evidence quote if it is not a
real span of the answer.

---

## Anti-hallucination

Four independent mechanisms, because prompting alone is not a control:

1. **Prompt-level** — "judge only what is inside `<candidate_answer>`", `missing_points` must come
   from supplied curriculum objectives, `evidence_quote` must be verbatim.
2. **Quote verification** — `grounding.verify_quote` requires the quote to be a substring of the
   answer (with a tolerant token-overlap rescue for light reformatting). Failures are dropped and
   flagged.
3. **Evidence-pack isolation** — the report generator receives computed evidence only: per-topic
   scores, dimension averages, verified quotes, unmet objectives, behaviour notes. It never sees the
   raw transcript, so it cannot quote something that was never said.
4. **Vocabulary check** — after generation, `grounding.check_report` flags technology-shaped terms in
   the report that appear in neither the curriculum vocabulary nor the interview. Warnings surface in
   the dashboard's grounding panel rather than being silently swallowed.

Every number in the dashboard is computed in Python. The model writes prose about numbers it is
given; it never produces one.

---

## Measuring the scoring

`backend/tools/calibrate.py` runs a hand-labelled golden set (`app/data/golden.json`, 10 answers
labelled strong/adequate/weak) N times through the configured provider and reports:

* mean and standard deviation per rubric dimension — run-to-run score stability;
* verdict stability — how often the same answer gets the same verdict;
* band accuracy — did the composite land inside the human-labelled band;
* band ordering — fraction of case pairs ranked the way a human ranked them;
* correlation between the configured model and the offline rubric engine.

On the offline engine: band accuracy 1.0, band ordering 0.97, SD 0 by construction. With a live key
those numbers become real evidence about the model. `tests/test_calibration.py` pins the properties
so a scoring change cannot silently regress them.

This is deliberately a *harness*, not a claim of validity: the labels are ours. Agreement with
multiple independent human interviewers is the honest next step and is named as such in the README.

---

## Cohort aggregation

`engine/cohort.py` folds finished interviews into a staff-facing view: per curriculum day, how many
interviews touched it, the mean/min/max score, how many fell below the bar, the weakest verbatim
answer, and the flags that recurred. Days are only ranked once at least two interviews cover them,
because a mean of one is not a finding.

Entirely computed — no model call. A day appears in "weakest" because people scored badly on it, not
because a model thought it looked weak.

---

## Reliability

```
try provider[0] ─ retry ×2 with jittered backoff ─┐
                                                   ├─ circuit breaker (4 fails ⇒ 30s cooldown)
try provider[1] ──────────────────────────────────┤
                                                   │
offline rubric engine ─────────────────────────────┘  ← cannot fail
```

`LLMRouter.structured` never raises. Call sites always receive structured data plus a `degraded`
flag and human-readable notes, both of which the UI shows. Auth errors don't retry (a bad key won't
fix itself); rate limits honour `Retry-After`; malformed JSON goes through a repair ladder (fenced
block → balanced-brace extraction → trailing-comma/smart-quote/unterminated-string repair) before
being treated as a failure.

The **offline rubric engine** is a real, deterministic scorer — length curve, domain-term overlap
against the day's curriculum text, concrete-figure count, reasoning connectives, vagueness and
buzzword markers, first-person evidence markers — not a fake LLM. Everything it produces is tagged
`source: "heuristic"` and labelled "offline rubric engine" in the UI. It exists so a missing key, a
quota, or conference wifi cannot end a demo, and so there is a model-independent baseline to sanity-
check the model against.

---

## Retrieval

Two BM25 indexes over the curriculum: one document per **day** (title + module + tools + objectives),
and one document per **learning objective**. A small synonym map (`rag → retrieval augmented
generation`, `k8s → kubernetes`) and crude de-pluralisation mean a candidate's "chunks" hits an
objective's "chunk".

It runs inside the interview loop, twice per turn (`engine/topics.py`):

**1. Objective targeting.** `rank_objectives(day, everything_they_said_about_that_day)` returns the
day's objectives ordered by how *little* the candidate has covered them. The least-covered objective
goes into the question prompt. This is why a second question on a topic explores new ground instead
of rephrasing the first.

**2. Volunteered-topic detection.** Every answer is scored against the **whole curriculum**. If the
global best-matching day is a planned-but-unasked slot, and it beats the current topic by a 1.7×
margin above an absolute floor, the policy pulls that slot forward with
`reason_code: candidate_volunteered_topic` — you answered a retrieval question by talking about MCP,
so the interviewer follows you there, exactly as a human would.

The word *global* is load-bearing, and it was a bug before it was a feature. An earlier version took
the argmax over planned slots only. Feed it an answer entirely about MCP on a plan containing no MCP
day and it still returned something: the best *planned* day, clearing the floor on a few incidental
shared terms. The interviewer then announced "let's move to the capstone" about an answer that had
nothing to do with the capstone. The retrieval was right; restricting the argmax made the conclusion
wrong. Now, if the real match isn't on the plan, it says nothing and normal drift handling applies.

Four guards, each against a specific failure:

| Guard | Prevents |
| --- | --- |
| Global argmax must be a planned slot | Jumping to the nearest planned neighbour of an unplanned topic |
| BM25 floor (6.0) | Waffle changing the subject — evasion needs a day's real vocabulary to clear it |
| 1.7× margin over the current topic | Thrashing on answers that legitimately span two days |
| Max 2 jumps per interview | The plan being reordered every turn; adaptivity becoming noise |

Note what the gate is *not*: the rubric verdict. Dimensions are scored against the current day, so an
answer genuinely about another topic scores low on all of them — a verdict-based gate would make this
branch unreachable, which is exactly the bug that shipped in the first version of it.

When a jump fires, the answer is re-attributed to the day it was actually about, so a candidate is
not penalised on a topic they never really answered.

All of it is asserted in `tests/test_retrieval.py`, negative cases included.

**No vector database, deliberately.** 31 documents of ~60 words is a corpus where lexical retrieval
beats an embedding round-trip on latency, cost and determinism, and needs no network. The interface
is narrow (`search`, `score_day`, `rank_objectives`, `day`), so swapping in Chroma is a one-file
change. Adding one here to look impressive would be exactly the kind of decision this product exists
to interrogate candidates about.

---

## Cost and performance

- Two model calls per turn; ~1 extra for the final report.
- Deterministic rolling summary keeps prompt size flat instead of resending the transcript.
- Repeat requests, meta-questions, injection responses and early-end refusals are answered from
  state — **zero** model calls.
- Evaluation runs at `temperature 0.1` (stability), generation at `0.65` (variety).
- Live token counts, call counts and average latency are tracked per session and shown in the UI.

---

## Persistence

SQLite with WAL, one JSON blob per session, a version column, and TTL sweeping at startup. Chosen
because a browser refresh, a server restart, or a closed laptop lid must not destroy an interview in
progress — the single most embarrassing failure a live demo can have. Per-session async locks
serialise concurrent writes; an 8-second fingerprint window distinguishes a double-clicked submit
from a candidate genuinely saying "I don't know" twice.
