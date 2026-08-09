# Deploying, and recording the backup video

Two things a judge values that this repo cannot generate for itself: **a URL they can open after you
leave**, and **a video that survives your laptop dying on stage**. Both are below, each about fifteen
minutes.

---

## 1. Get a URL

The image is already built and health-checked. Pick whichever platform you have an account on.

### Render (free tier, easiest)

```bash
git push origin main
```

Then in Render: **New → Blueprint →** point at the repo **→ Apply**. `render.yaml` declares the
service, the health check, and a 1 GB disk mounted at `/data` so interviews survive a restart.

Add `ANTHROPIC_API_KEY` in the dashboard (it is deliberately `sync: false` in the blueprint so the key
never lands in git). Without it the deploy still works — it runs the offline rubric engine and labels
itself accordingly.

### Fly.io

```bash
fly launch --no-deploy --copy-config
```

```bash
fly volumes create cohortiq_data --size 1 && fly secrets set ANTHROPIC_API_KEY=sk-ant-... && fly deploy
```

### Anywhere else

```bash
docker build -t cohortiq . && docker run -p 8000:8000 -v cohortiq_data:/data -e ANTHROPIC_API_KEY=sk-ant-... cohortiq
```

### After deploying — verify, don't assume

```bash
curl -s https://YOUR-URL/api/health | python -m json.tool
```

Check three things in that output: `status: ok`, `llm.live: true` (the key is wired), and
`sessions.durable: true` (the disk is mounted — if this is `false` the app fell back to an in-memory
store and interviews will not survive a restart).

Then run one full interview on the deployed URL and open **Cohort insights**, so a judge who visits
later sees populated data rather than an empty state.

Finally, put the URL at the top of the README. A link nobody can find is the same as no link.

---

## 2. Record the backup video

**Record this before you need it.** The single most expensive failure available to you is a demo about
graceful degradation that dies on stage.

Three minutes, one take, no narration edits:

| Time | Show |
| --- | --- |
| 0:00–0:20 | **Compare** — Diane vs Tyler, side by side. Let it sit for four seconds before you speak. |
| 0:20–0:35 | Start Diane's interview; the full-screen plan reveal. |
| 0:35–1:00 | One strong answer from the topic-keyed sheet. Point at the rubric rail and the difficulty indicator moving. |
| 1:00–1:15 | Click **Why this question?** |
| 1:15–1:35 | Paste the injection string. Score does not move; interview continues. |
| 1:35–1:50 | Finish the interview; the report, then the **Replay** tab. |
| 1:50–2:20 | **Cohort insights** — weakest days with real quotes. |
| 2:20–2:45 | Terminal: `python -m pytest tests -q` → 143 passed, and `python -m tools.calibrate --runs 5`. |
| 2:45–3:00 | Optional: kill the server, restart, refresh, keep answering. |

Tooling: OBS, Loom, or on Windows `Win+Alt+R`. Upload unlisted to YouTube or Loom, and link it in the
README next to the deployed URL.

---

## Pre-submission checklist

Run through this immediately before zipping or pushing.

```bash
rm -rf data backend/data frontend/tsconfig.tsbuildinfo
```

- [ ] `data/sessions.db*` is **not** in the archive. It is gitignored, but zipping a working directory
      ignores `.gitignore` — the file is recreated every time the server runs, so delete it last.
- [ ] `.env` is not in the archive. `.env.example` is.
- [ ] `frontend/dist` rebuilt from current source (`npm run build`).
- [ ] `python -m pytest tests -q` passes on a clean checkout.
- [ ] README test count matches reality.
- [ ] Deployed URL and video link are both at the top of the README.
- [ ] Fresh-clone install followed verbatim on a second machine, including the Python 3.11+ check.
