# Edge-case matrix

Every row is handled in code and, where marked, asserted by a test. The rule throughout: **fail
gracefully, never crash, never silently drop the candidate's work.**

## Candidate behaviour

| Case | Handling | Test |
| --- | --- | --- |
| "I don't know" | One rescue attempt at lower difficulty on the same topic, then move on. Never scored as a wrong answer twice. | `test_policy.py` |
| "Can you repeat that?" | Restated verbatim from `pending_question`. **No model call** — cannot drift. Serviced even mid-disengagement. | `test_policy.py`, `test_api.py` |
| "Skip this" | Moves to the next planned topic; question budget untouched. | `test_api.py` |
| "Give me a hint" | One concrete hint that narrows without answering, then a focused re-ask. | `test_policy.py` |
| Empty / whitespace / "ok" | Classified `EMPTY`, met with a clarify prompt, not scored. | `test_api.py` |
| One-word answers | Length curve penalises thinness but short-and-correct is not marked weak. | `test_reliability.py` |
| 100,000-character answer | Capped at 6,000 chars with a truncation marker; `rambling` flag applies. | `test_api.py` |
| Rambling | `rambling` flag; specificity and communication scores drop. | — |
| Silence (no message field) | Treated as empty; interview waits, does not advance. | `test_api.py` |
| Contradicts an earlier answer | Conservative lexical check flags `contradicts_earlier`; the claim moves to `CONTRADICTED` in the ledger. False accusations are worse than misses, so the bar is deliberately high. | `test_api.py` |
| Memorised-sounding answer | `memorised_sounding` / `buzzword_heavy` flags trigger `CHALLENGE_CLAIM`. | `test_policy.py` |
| Asks the interviewer a question | Answered honestly and deterministically (identity, scoring method, questions remaining, score-so-far), then the outstanding question is restated. | `test_api.py` |
| Tries to manipulate the interviewer | Detected, counted, answered in character, reported as behaviour. Score unaffected, interview continues. | `test_api.py`, `test_security.py` |
| Refuses to answer | Moves on; ends only if the coverage floor is already met. | `test_policy.py` |
| Answers a different question | `possibly_off_topic` ⇒ `REDIRECT` that names the drift and restates the ask. | — |
| Asks to end early | Declined before question 3 with a reason; honoured after. | `test_policy.py` |
| Answers everything perfectly | Coverage floor forces depth instead of an early finish — still ≥ 8 questions. | `test_api.py` |
| Answers nothing at all | Still terminates and still produces a report naming the disengagement. | `test_api.py` |
| Answers about a *different* planned topic | Retrieval detects it and the interviewer follows them there (`candidate_volunteered_topic`) instead of dragging them back, and the answer is re-scored against the day it was actually about. | `test_retrieval.py` |
| Answers about a topic that is **not** on their plan | No jump. The argmax runs over the whole curriculum and only fires if the winner is planned — otherwise the interviewer would redirect to the nearest planned neighbour and appear to mishear them. | `test_retrieval.py` |
| Rambles onto another topic to dodge a hard one | Waffle can't clear the BM25 floor for a specific day; that needs the day's real vocabulary. | `test_retrieval.py` |
| Keeps steering onto their favourite topic | Capped at two jumps per interview — following the candidate is a moment, not a mode. | `test_retrieval.py` |
| Names a tool without justifying it ("we went with Chroma, it worked fine") | Detected as an unjustified preference: depth and specificity are penalised even though the domain vocabulary is right. | `test_calibration.py` |

## Model and provider failures

| Case | Handling | Test |
| --- | --- | --- |
| Timeout | Retry with jittered backoff, then next provider, then offline rubric engine. | `test_reliability.py` |
| 5xx | Same ladder; failure counted toward the circuit breaker. | `test_reliability.py` |
| 429 rate limit | Honours `Retry-After`, capped at 6s, then falls through. | `test_reliability.py` |
| 401/403 | No retry — a bad key will not fix itself. Immediate fallback. | `test_providers.py` |
| Malformed JSON | Repair ladder: fenced block → balanced braces → trailing commas / smart quotes / unterminated strings. | `test_security.py` |
| Empty response | Treated as a provider failure; question falls back to a curriculum-grounded template. | `test_reliability.py` |
| Out-of-range scores (`900`, `-40`) | Clamped to 0–100. | `test_reliability.py` |
| Invalid verdict / invented flags | Verdict re-derived from the composite; unknown flags discarded. | `test_reliability.py` |
| `non_answer` verdict with 95s | Incoherent — the verdict wins, scores forced down. | `test_reliability.py` |
| Fabricated evidence quote | Verified against the answer; dropped and flagged if absent. | `test_reliability.py` |
| Hallucinated technology in the report | Vocabulary check flags it; surfaced in the grounding panel. | `test_security.py` |
| Repeated question | Token-overlap guard ⇒ one regeneration at higher temperature ⇒ template. | — |
| Provider persistently down | Circuit breaker opens after 4 failures, 30s cooldown, half-open retry. | `test_reliability.py` |
| Provider client raises something unexpected | Caught, logged, contained; the turn still completes. | `test_reliability.py` |
| Infinite interview | Bounded by question budget, turn budget, and per-topic follow-up caps. | `test_policy.py` |

## Candidate data

| Case | Handling | Test |
| --- | --- | --- |
| No candidate object | Unprofiled interview on the canonical curriculum spine; greeting says so. | `test_api.py` |
| `{}` / `null` / a bare string / a list | Parsed defensively, notes recorded, interview proceeds. | `test_planner.py` |
| Flat object without `member` | Fields read from the root. | `test_planner.py` |
| `missions` not a list | Treated as empty, note recorded. | `test_planner.py` |
| Duplicate mission days | Collapsed, keeping the most informative record. | `test_planner.py` |
| Day numbers outside 1–31 | Ignored; planner only uses days present in the curriculum. | `test_planner.py` |
| `missionsFirstTry > missionsCompleted` | Clamped, note recorded. | `test_planner.py` |
| Negative years of experience | Clamped to 0. | `test_api.py` |
| Injection text inside profile fields | Never reaches a system prompt; delimited as data. | `test_api.py` |
| Multiple candidates in one payload | First used, ambiguity recorded in `parseNotes`. | `test_planner.py` |
| Candidate with no completed missions | Falls back to the curriculum spine. | `test_planner.py` |

## Curriculum data

| Case | Handling |
| --- | --- |
| Missing or corrupt `curriculum.json` | Loader returns an empty curriculum instead of failing startup; the engine degrades to generic topics. |
| Day referenced by a mission but absent from the curriculum | Skipped during planning. |
| Module day-ranges that don't cover a day | Day is labelled "Unassigned"; nothing breaks. |
| A completely different curriculum | Works. Weights derive from each day's `type` and concept density; no day number is hardcoded. Asserted against a 14-day platform-engineering cohort in `test_portability.py`. |
| A curriculum with no `CAPSTONE` day | Synthesis anchor falls back to the last `SHIP_IT` day, then to the final day. |

## Scoring integrity

| Case | Handling | Test |
| --- | --- | --- |
| A rubric dimension stops discriminating | `test_rubric_engine.py` fails if any dimension returns one value across the corpus — this caught `communication` pinned at 84–100. | `test_rubric_engine.py` |
| Scoring regresses against human labels | Calibration harness gates band accuracy ≥ 0.8 and band ordering ≥ 0.85 on a hand-labelled golden set. | `test_calibration.py` |
| Score varies run to run | `tools/calibrate.py` reports per-dimension standard deviation and verdict stability, and names which provider produced them. | — |
| A regex silently stops matching (mangled `\b` → `\x08`) | A test walks every compiled pattern in the app. Regexes fail *open*, so this bug class is invisible without a guard. | `test_calibration.py` |

## Cohort aggregation

| Case | Handling | Test |
| --- | --- | --- |
| No finished interviews | Endpoint returns zeroed structure; UI shows an empty state, not an error. | `test_cohort.py` |
| One interview covering a day | Included in the per-day list but excluded from the ranking — a mean of one is not a finding. | `test_cohort.py` |
| Corrupt session row during aggregation | Skipped; the dashboard still renders. | — |
| DB unwritable at startup | Falls back to an in-memory store, logs the reason, and reports `durable: false` on `/api/health` rather than refusing to boot. | — |

## Client and transport

| Case | Handling | Test |
| --- | --- | --- |
| Refresh mid-interview | Session id in `localStorage`; state reloaded from SQLite; transcript restored. | `test_api.py` |
| Server restart mid-interview | State is on disk, not in memory. | — |
| Browser closed and reopened | Same recovery path, within the 24h TTL. | — |
| Network loss | Draft answer preserved in `localStorage`; offline banner; retry resends the same message. | — |
| Double-clicked submit | Per-session lock + 8s fingerprint window ⇒ cached reply, no duplicate turn. | `test_api.py` |
| Genuine repeat of the same answer later | Outside the window ⇒ treated as a real answer. | `test_api.py` |
| Slow response | 90s client timeout, retries, and an explicit "your answer is safe" message. | — |
| Rate limited | 200 with an in-character reply and `Retry-After`, not a raw 429 body. | — |
| Malformed request body | Returns the spec shape (`reply`, `done: false`) rather than a 422 blob. | `test_api.py` |
| Message for an unknown session | Starts a fresh unprofiled interview instead of erroring. | `test_api.py` |
| Posting to a completed session | Returns the stored feedback, `done: true`, idempotently. | `test_api.py` |
| Corrupt session row | Logged, dropped, interview restarts cleanly rather than 500ing. | — |
| Front-end render crash | Error boundary with a "reload and resume" path; state is server-side. | — |
| Dictation unsupported / mic denied / no speech | Button hidden when unsupported; every failure falls back to typing with an explanatory message. | — |
