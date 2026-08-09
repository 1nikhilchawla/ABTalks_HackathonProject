# Deploying

The image is already built and health-checked. Pick whichever platform you have an account on.

---

## Render (free tier)

```bash
git push origin main
```

In Render: **New → Blueprint →** point at the repo **→ Apply**. `render.yaml` declares the service and
the health check.

Add `ANTHROPIC_API_KEY` in the dashboard (it is deliberately `sync: false` in the blueprint so the key
never lands in git). Without it the deploy still works — it runs the offline rubric engine and labels
itself accordingly.

**Free-tier caveats, both real:**

- **No disk.** Render rejects `disk:` on free plans, so storage is ephemeral: sessions are lost when
  the instance sleeps or redeploys. Everything still works; nothing survives a restart. For
  durability, switch to `plan: starter` and uncomment the disk block in `render.yaml`.
- **Sleeps after 15 minutes idle.** The first request then takes ~50 seconds. Warm it up before
  anyone looks at it.

## Fly.io

```bash
fly launch --no-deploy --copy-config
```

```bash
fly volumes create cohortiq_data --size 1 && fly secrets set ANTHROPIC_API_KEY=sk-ant-... && fly deploy
```

Fly does support volumes, so `fly.toml` mounts one at `/data` and sessions survive restarts.

## Anywhere else

```bash
docker build -t cohortiq . && docker run -p 8000:8000 -v cohortiq_data:/data -e ANTHROPIC_API_KEY=sk-ant-... cohortiq
```

---

## After deploying — verify, don't assume

```bash
curl -s https://YOUR-URL/api/health | python -m json.tool
```

Three things in that output:

| Field | Want | Meaning if wrong |
| --- | --- | --- |
| `status` | `ok` | App did not start |
| `llm.live` | `true` | No API key reached the process — it is on the offline rubric engine |
| `sessions.durable` | `true` | Falls back to an in-memory store; `false` means the path was unwritable |

Note `durable: true` only says SQLite is writing to disk. On a platform without a mounted volume
(Render free tier) that disk is still ephemeral.

Then run one full interview on the deployed URL and open **Cohort insights**, so anyone visiting later
sees populated data rather than an empty state.

Finally, put the URL at the top of the README. A link nobody can find is the same as no link.

---

## Pre-push checklist

```bash
rm -rf data backend/data frontend/tsconfig.tsbuildinfo
```

- [ ] `data/sessions.db*` is **not** in the archive. It is gitignored, but the server recreates it on
      every run, so delete it last if you are zipping a working directory.
- [ ] `.env` is not committed. `.env.example` is.
- [ ] `frontend/dist` rebuilt from current source (`npm run build`) if you are serving it locally.
- [ ] `python -m pytest tests -q` passes on a clean checkout.
- [ ] README test count matches reality.
- [ ] Deployed URL is at the top of the README.
- [ ] Fresh-clone install followed verbatim on a second machine, including the Python 3.11+ check.
