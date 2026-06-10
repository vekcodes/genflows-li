# Brain OS — YouTube Script Writer

A self-updating **Brain** built from YouTube channels you keep adding (scrape → analyze what
performs → accumulate insights), with a **YouTube Script Writer** on top whose every idea is
**backtested for virality**. See [`ARCHITECTURE.md`](./ARCHITECTURE.md),
[`REQUIREMENTS.md`](./REQUIREMENTS.md), and [`GOING_LIVE.md`](./GOING_LIVE.md).

```
backend/   FastAPI Brain (Python) — sources → ingestion → raw lake → analytics → virality
           model → LLM mining → generation. Runs always-on, from a residential IP.
src/       Vite + React + TS frontend — Sources/Brain admin, Insights, Script Writer,
           Demand & Search. Talks to the Brain API; deployable to Vercel.
```

The script writer is the only consumer built here; the Brain API is general so other tools
(LinkedIn, etc.) can be separate future repos. Everything runs on **localhost** today; deploy later.

## Run it locally (two terminals)

**1 · Backend** (needs Python 3.12; Claude Code logged in for the LLM features):
```bash
cd backend
python -m venv .venv && .venv\Scripts\Activate.ps1   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload                         # http://localhost:8000/docs
```

**2 · Frontend:**
```bash
npm install
cp .env.example .env.local        # default points at http://localhost:8000
npm run dev                       # http://localhost:5173
```

## Using it
1. **Sources & Brain** — add a channel/video URL; ingestion runs in the background (incremental).
   Watch videos/transcripts/comments grow and the **virality backtest** report appear (needs ≥ 24
   videos to train).
2. **Insights** — see outliers; click **Mine** to extract format patterns, comment pain-points,
   and style-cards (Claude).
3. **Script Writer** — generate evidence-ranked ideas (each with a 0–100 virality score + nearest
   proven analogs), set a **min virality** gate, then write a full script (outline → expand →
   polish), edit it, and export markdown.
4. **Demand & Search** — validate a topic (Google Trends + search-suggest) and semantically search
   everything ingested.

## Notes
- **LLM**: Claude via your subscription (Claude Code CLI). `GET /brain/status` shows `llm.available`.
  Without it, mining/generation return `501`; analytics + virality still work.
- **Residential IP**: run the backend on your own machine — YouTube blocks datacenter IPs.
- **Tests**: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe tests/test_<name>.py`
  (`throttle`, `virality`, `generation`, `extras`).

## Deploy (later)
Frontend → Vercel (set `VITE_API_BASE_URL`). Backend → your machine / a mini-PC exposed via
Cloudflare Tunnel (it can't be serverless — see `GOING_LIVE.md`).
