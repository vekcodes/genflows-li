# Deploying the whole app to Vercel

This project now runs **fully on Vercel** — the Vite SPA *and* the FastAPI backend as a Python
serverless function — with no always-on box required. Three things made that possible:

| Blocker (old) | Fix (now) |
|---|---|
| Default LLM was the Claude **CLI** (subprocess, OAuth login) — impossible in a function | `BRAIN_LLM_PROVIDER=anthropic` + your **API key**. The CLI path still works locally. |
| Background **threads + APScheduler** (generation, scrape worker, weekly cron) die when a function freezes | `BRAIN_SERVERLESS=true` (auto-set on Vercel) runs that work **in-request**; periodic jobs become `/cron/*` endpoints driven by **Vercel Cron**. |
| **SQLite file** is wiped on every cold start | Point `BRAIN_DATABASE_URL` at hosted **Postgres** (Neon/Supabase free tier). One-shot migration script copies your existing 681 videos over. |
| YouTube **IP-blocks** datacenter scraping | Already solved — set `BRAIN_SCRAPE_PROVIDER=apify` + `BRAIN_APIFY_TOKEN` (your Apify backend). |

## Files that make it work
- `api/index.py` — Vercel Python entrypoint; imports the FastAPI `app`, forces serverless mode.
- `requirements.txt` (repo root) — the function's deps (no uvicorn/whisper/pytrends).
- `vercel.json` — builds the SPA, rewrites API paths to the function, declares the 3 cron jobs.
- `app/api/cron.py` — `/cron/scrape-tick`, `/cron/weekly-content`, `/cron/daily-rescore`.
- `backend/scripts/migrate_db.py` — copy SQLite → Postgres (preserves ids).

## Step-by-step

### 1. Create a Postgres DB (free)
Sign up at **neon.tech** (or supabase.com), create a database, copy the connection string. It
looks like `postgresql://user:pass@host/dbname?sslmode=require`.

### 2. Migrate your existing brain into it (run locally, once)
```powershell
cd "C:\Genflows\Yt script writer\backend"
.\.venv\Scripts\pip install psycopg2-binary
.\.venv\Scripts\python.exe scripts\migrate_db.py `
    --source "sqlite:///./brain.db" `
    --target "postgresql://USER:PASS@HOST/dbname?sslmode=require" --wipe
```
You should see `video: 681 rows`, `comment: 9927 rows`, etc., then `sequences advanced`.

### 3. Push to GitHub and import into Vercel
Vercel auto-detects Vite. In **Project Settings → Environment Variables**, add:

| Key | Value |
|---|---|
| `BRAIN_DATABASE_URL` | your Postgres connection string |
| `BRAIN_LLM_PROVIDER` | `anthropic` |
| `BRAIN_ANTHROPIC_API_KEY` | your Claude API key |
| `BRAIN_CLAUDE_MODEL` | `claude-opus-4-8` (or `claude-sonnet-4-6` to cut cost) |
| `BRAIN_SCRAPE_PROVIDER` | `apify` |
| `BRAIN_APIFY_TOKEN` | your Apify token |
| `BRAIN_API_KEY` | a random string (locks the API; the SPA sends it) |
| `CRON_SECRET` | a random string (Vercel sends it to your cron endpoints) |

`BRAIN_SERVERLESS` is set automatically (Vercel sets `VERCEL=1`). `VITE_API_BASE_URL=/` is baked
in by `vercel.json`, so the SPA calls its own origin — no extra config.

> Note on `BRAIN_API_KEY`: the frontend must send it as `x-api-key`. It currently reads
> `VITE_API_KEY` at build time — set that to the **same** value in Vercel's build env, or leave
> `BRAIN_API_KEY` unset for an open API while testing.

### 4. Deploy
Vercel builds the SPA → `dist/`, deploys `api/index.py` as a function, and registers the crons.
Visit your `*.vercel.app` URL. `/health` and `/brain/status` should return your real numbers.

## Important limits & how the design respects them
- **Function timeout** — `vercel.json` sets `maxDuration: 300` (5 min, needs Vercel **Pro**; Hobby
  caps at 60s). Generation is one item at a time in-request; the parallel-beats change keeps a
  single item well under that. The weekly cron defaults to `refresh=false` and a **small n** —
  don't try to generate a big batch in one request. **Large initial scrapes still run best
  locally**, then migrate the DB up.
- **Cold starts** — sklearn/numpy load on first hit; the virality model is cached after the first
  score within a warm instance.
- **No persistent queue/progress** — on serverless the queue/progress bars reflect work that
  finished *inside* the request rather than a live background job. The data result is identical.

## Keeping the hybrid option
Nothing here removes the local/Docker path. On your machine (no `VERCEL` env), it still uses the
Claude CLI subscription, SQLite, real background threads and APScheduler — exactly as before.
Vercel is purely additive.
