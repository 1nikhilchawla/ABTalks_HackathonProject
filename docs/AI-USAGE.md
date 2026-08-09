# AI usage disclosure

**Short version:** effectively all of the code in this repository was written by an AI assistant
(Claude Opus 5, via Claude Code) working from human direction. The human set the goals, supplied the
brief and datasets, commissioned adversarial reviews, made the product decisions, and rejected or
redirected work. The AI designed the architecture, wrote the implementation and the tests, ran them,
found and fixed its own bugs, and wrote the documentation.

This file records that honestly, including the parts the AI got wrong.

---

## Tooling

| | |
| --- | --- |
| Assistant | Claude Opus 5 |
| Interface | Claude Code (agentic CLI — reads/writes files, runs shell commands, drives a browser) |
| Runtime for the product itself | **No AI provider at all by default.** The shipped app runs on a deterministic offline rubric engine; the LLM provider layer is optional |

The distinction matters and is easy to blur: AI wrote the software, but the software does not require
an AI API to run. See the README for what that trades away.

---

## Division of labour

**Human (repository owner):**

- Supplied the hackathon brief, `curriculum.json`, `candidates.json`, and the technical spec.
- Commissioned two independent adversarial code reviews and pasted the findings back in full.
- Made every product decision: remove the demo script and pitch from the repo; run keyless with no
  API key; deploy to Render free tier.
- Ran the deployment, holds the credentials, owns the GitHub repository.

**AI:**

- Architecture, database schema, API contract, prompt design, state machine.
- All application code: ~6,000 lines Python, ~3,300 lines TypeScript/React.
- All 143 tests (~1,500 lines) — including the ones that later caught its own mistakes.
- All documentation, including this file.
- Verification: ran the test suite, drove the app end to end through a real browser and via HTTP,
  simulated a clean `git clone` and rebuilt from it.

**Not done by AI:** deployment, credential handling, the GitHub push authorisation, and the two
external reviews.

---

## How the work actually went

### 1. Initial build

One long brief (product requirements + hackathon brief + a standing-instructions file about rigour).
The AI proposed the core design decision that the rest of the project follows from — *the model
writes the questions, a deterministic state machine decides which question to write* — then built
backend, frontend, and 89 tests. It ran the suite, found four real bugs in its own code from the test
output, and fixed them before reporting.

### 2. First external review → 73/100

A reviewer read the source, ran the suite and drove the app. Findings the AI accepted and fixed:

| Finding | What was actually wrong |
| --- | --- |
| **BM25 was dead code** | A working retrieval index was implemented, documented in the architecture diagram, and defended in the demo script — but never called. The docs described a component that did not run. |
| **`communication` scored 84–100 for every answer** | The formula keyed off length, so one radar axis was always maxed and carried no information. |
| **No score calibration** | The product's core output had never been measured. |
| **31 hardcoded day weights** | Welded the planner to one curriculum. |

Rather than delete the retrieval claim, the AI wired BM25 into two live behaviours (objective
targeting; following a candidate onto a topic they raised), rebuilt the communication metric around
structure, added a calibration harness with a hand-labelled golden set, and derived the day weights
from curriculum metadata so a second curriculum works untouched.

### 3. Second external review → 79/100

The reviewer verified the fixes and found a **new bug in the new feature**: the volunteered-topic
argmax searched only planned slots, so an answer about a topic that was not on the plan got
redirected to the nearest planned neighbour — the interviewer announcing *"let's move to the
capstone"* about an answer that had nothing to do with the capstone. Fixed by taking the argmax over
the whole curriculum and firing only when the global winner is a planned slot, plus a per-interview
jump budget the reviewer also asked for.

### 4. Pre-push audit

Before the first push the AI simulated a clean `git clone` — copying only files git would track — and
caught a repository-breaking mistake of its own: `.gitignore` contained an unanchored `data/`, which
git matches at **any** depth, silently excluding `backend/app/data/` (the curriculum, the candidate
roster, the golden set, and two source modules). A fresh clone would not have started. Fixed with a
leading slash and a comment explaining why the slash is load-bearing.

### 5. Post-push changes

Render rejected the blueprint (`disks are not supported for free tier`); config fixed and pushed. The
owner then asked to remove the demo/pitch material and to run keyless permanently; both done, with
the offline engine promoted from "degraded fallback" to documented default.

---

## Mistakes the AI made, for the record

Listed because a disclosure that only describes successes is not a disclosure.

1. **Shipped dead code described as architecture** (BM25). Caught by external review, not by the AI.
2. **A scoring dimension with no discriminating power**, undetected until someone plotted the outputs.
3. **An unreachable code path.** The first version of volunteered-topic detection gated on the rubric
   verdict — but rubric scores are computed against the *current* topic, so an answer about another
   topic always scores badly. The branch could never fire. Caught by the AI when testing it live.
4. **The wrong-day argmax**, above. Caught by external review.
5. **A `.gitignore` pattern that would have shipped a broken repo.** Caught by the AI's own clone
   simulation.
6. **Mangled regex escapes, twice** — shell heredocs turned `\b` into a literal backspace, so two
   patterns silently never matched. Regexes fail *open*, so nothing errored. After the second
   occurrence the AI added a test that walks every compiled pattern in the app looking for the same
   corruption.

The pattern worth noting: the AI caught the bugs that produced observable wrong behaviour, and missed
the ones where something merely *did not happen* — dead code, a flat metric, an unreachable branch.
External review found those.

---

## Verification performed

None of the claims in the README rest on the AI asserting them:

- `python -m pytest tests -q` → 143 passed, run after every substantive change.
- Full interviews driven end to end through the real FastAPI app and through the browser, checking
  the brief's floor (≥ 8 questions, ≥ 4 curriculum days, structured feedback).
- Clean-clone simulation: `npm ci`, `npm run build`, boot, full interview, cohort aggregation.
- Adversarial paths exercised live: prompt injection, "I don't know", skip, repeat, meta-questions,
  empty and 100k-character inputs, double submission, refresh and server restart mid-interview.
- Provider failure paths tested against a mock transport, so retries, circuit breaking and fallback
  are covered without an API key.

## What remains unverified

- **The Docker build has never been executed** — the CLI was installed but the daemon was not running.
  Path logic was checked statically only.
- **No live-model run.** Every observed behaviour came from the offline rubric engine. The
  Anthropic/OpenAI/Groq providers are covered by mock-transport tests, never by a real API call.
- **Scoring has no external validity evidence.** The calibration harness measures agreement with
  labels written by the AI itself, on ten cases. The tool prints that caveat in its own output.

---

## Reproducing the code without the AI

Everything needed is in the repository: no generated artefact is checked in that cannot be rebuilt
from source (`frontend/dist` is gitignored and built by `npm run build` or the Dockerfile's first
stage). The test suite is the specification — it encodes the coverage floors, the termination
guarantees, the injection handling and the scoring properties, and it runs offline in about 13
seconds.
