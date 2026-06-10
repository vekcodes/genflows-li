# Brain OS — Backend

The self-updating YouTube knowledge engine described in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
This is **layers A–E** (sources → ingestion → raw lake → processing → brain) plus a skeleton of
**layer F** (the Brain API). Consumer apps (layer G) are separate Vite frontends.

> This is the **backend foundation** slice: sources registry + incremental ingestion → Raw
> Lake (SQLite), plus working baseline/outlier analytics. LLM-powered mining is wired behind a
> provider interface but returns `501` until implemented (build-order step 3).

## Setup

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\Activate.ps1     macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for the interactive API.

> ⚠️ YouTube blocks datacenter IPs. Run this on a machine with a **residential IP** (yours) or
> via a residential proxy. Ingestion is incremental and periodic — never per end-user request.

## LLM auth (Claude via subscription, no API billing)

The default provider shells out to the **Claude Code CLI** in headless mode, which uses your
**Claude subscription**:

1. Install Claude Code and run `claude` once to log in, **or**
2. `claude setup-token` → paste the token into `.env` as `BRAIN_CLAUDE_CODE_OAUTH_TOKEN`.

Check it's wired: `GET /brain/status` → `llm.available: true`.
Fallback: set `BRAIN_LLM_PROVIDER=anthropic` + `BRAIN_ANTHROPIC_API_KEY` to use the API instead.
(Anthropic is rolling out native Agent-SDK subscription credits on 2026-06-15; we can switch to
that behind the same `LLMProvider` interface.)

## Try it

```bash
# Add a source (resolves + ingests the newest videos in the background)
curl -X POST localhost:8000/sources -H "content-type: application/json" \
  -d '{"url":"https://www.youtube.com/@SomeChannel","niche":"editing"}'

# Or ingest synchronously, capped to a few videos (good for a first test)
curl -X POST "localhost:8000/sources/1/ingest?max_new=5"

# The brain
curl localhost:8000/brain/status
curl localhost:8000/brain/baselines
curl "localhost:8000/brain/outliers?min_multiplier=3"

# ★ Virality — backtest the predictor on held-out history, then score a candidate
curl "localhost:8000/brain/virality/backtest?viral_threshold=3"
curl "localhost:8000/brain/virality/score?title=7%20Editing%20Mistakes%20Killing%20Your%20Retention&duration_sec=600"
```

### ★ Backtested-for-virality

`virality.py` fits a model that predicts a video's **outlier multiplier** (views ÷ channel
median) from features known **at publish time** (title traits, format, duration). It's
**backtested on a time-based split** (train on older videos, test on newer) and reports
**ROC-AUC, precision@k, and rank correlation** — so "this will perform" is a measured claim,
not a guess. `tests/test_virality.py` plants a known signal and asserts the backtest recovers
it. Run the tests:

```bash
PYTHONPATH=. .venv/Scripts/python.exe tests/test_virality.py
```

Needs ~24+ ingested videos (across viral and non-viral) before it can train; below that the
endpoints return `status: insufficient_data`.

### Mine insights + generate scripts (needs Claude logged in)

The reasoning steps use the configured LLM provider (Claude via your subscription by default).
Confirm `GET /brain/status` shows `llm.available: true` first.

```bash
# Mine reusable Brain state from what you've scraped
curl -X POST "localhost:8000/brain/mine/pain-points?niche=editing"
curl -X POST "localhost:8000/brain/mine/patterns?min_multiplier=3"
curl -X POST "localhost:8000/brain/mine/style-card?channel_id=UC..."
curl "localhost:8000/brain/pain-points"   # read back (no LLM needed)

# Generate evidence-ranked ideas, gated by the backtested virality model
curl -X POST localhost:8000/generate/ideas -H "content-type: application/json" \
  -d '{"channel_id":"UC...","niche":"editing","n":8,"min_score":50}'

# Turn a chosen idea into a full script (outline -> expand -> polish)
curl -X POST localhost:8000/generate/script -H "content-type: application/json" \
  -d '{"title":"7 Editing Mistakes Killing Your Retention","channel_id":"UC..."}'
```

Each idea comes back with a `virality_score` (0-100), `predicted_viral`, and `nearest_analogs`
(the closest proven outliers). `min_score` is the virality gate — ideas below it are dropped.

## Layout

```
app/
  config.py          env-driven settings (BRAIN_*)
  db.py              SQLite engine/session (Raw Lake)
  models.py          Source · Video · Transcript · Comment · IngestRun
  schemas.py         API request/response shapes
  ingestion/         resolver · scraper (yt-dlp) · transcripts · pipeline (incremental)
  brain.py           channel baselines + outlier scoring (pure analytics)
  virality.py        ★ virality model + time-split backtester (features → predict multiplier)
  insights.py        LLM mining: comment pain-points · format patterns · style-cards
  generation/        prompts · ideas (virality-gated) · script (outline→expand→polish)
  llm/               provider interface · claude_cli (subscription) · anthropic (fallback)
  scheduler.py       continuous incremental re-check (opt-in)
  api/               sources router · brain router (layer F)
  main.py            FastAPI app
```

## Run the continuous self-update loop (scheduled scraping)

Set `BRAIN_SCHEDULER_ENABLED=true` — every `BRAIN_SCHEDULER_INTERVAL_MINUTES` (default 30) the
scheduler re-ingests any source past its `cadence_hours` (default 24), **new videos only**. This
is the "trains itself as you feed it" loop. It runs in-process, so the backend must stay on
(another reason it isn't serverless).

**Politeness / anti-blocking** (all configurable, see `.env.example`):
- Random pause between videos (`BRAIN_SCRAPE_MIN/MAX_DELAY_SEC`) — set both to `0` for fast dev.
- Exponential backoff + jitter on transient fetch errors (`BRAIN_SCRAPE_MAX_RETRIES`).
- Global rolling-hour cap on videos scraped (`BRAIN_SCRAPE_HOURLY_VIDEO_CAP`); when hit, the run
  stops cleanly and resumes next tick.
- Ticks never overlap (`max_instances=1`), so a long scrape can't pile up.

Covered by `tests/test_throttle.py` (rate limiter, retries, jitter — instant, no network).
