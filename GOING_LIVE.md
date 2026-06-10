# Going Live — Ship Checklist

Everything needed to take the Brain OS + YouTube Script Writer from the current
backend foundation to a live product. Grouped by category, with **free options
highlighted** and status: ✅ done · 🟡 partial · ⬜ to build/set up.

> The hard constraint that shapes hosting: **scraping must run from a residential IP**, so the
> backend cannot live on Vercel/Lambda. The frontend can. See §4 and §6.

---

## 0. TL;DR — recommended **free** MVP stack

| Concern | Free choice for MVP | Upgrade at scale |
|---|---|---|
| YouTube scraping | `yt-dlp` + `youtube-transcript-api` from your **home machine** (residential IP) | residential proxy (paid) |
| JS runtime for yt-dlp | **Deno** (free) — fixes the extraction warning we saw | — |
| Backend host | your **always-on machine / mini-PC**, exposed via **Cloudflare Tunnel** (free) | small VPS + residential proxy |
| Database | **SQLite** (already wired) | **Postgres** — Supabase/Neon free tier |
| Vector "brain" DB | **Chroma** (local, free) or **pgvector** on Postgres | **Qdrant** (cloud free tier → paid) |
| Embeddings | **fastembed / sentence-transformers** (local, free) | OpenAI/Voyage embeddings (paid) |
| LLM reasoning | **Claude subscription** via Claude Code CLI (no API billing) | Anthropic API key |
| Frontend host | **Vercel** free tier | Vercel Pro |
| Trends/demand | `pytrends` + search-suggest (free) | — |
| Error tracking | **Sentry** free tier | paid |
| TTS (optional) | **MeloTTS** (local, free) | ElevenLabs (paid) |

**Net cash cost of the MVP path: ~$0** (assuming you already have a Claude Pro/Max plan and a
machine to run the backend). Paid items only appear when you scale scraping volume.

---

## 1. Already shipped ✅ (the whole MVP runs on localhost)
- FastAPI Brain API (`backend/`)
- Sources registry + **incremental** ingestion (yt-dlp signals + comments + transcripts) → SQLite Raw Lake
- Channel baselines + outlier scoring
- **★ Virality model + time-split backtester** (`/brain/virality/backtest`, `/brain/virality/score`)
- Hardened scheduled scraper (jitter · backoff · hourly cap · non-overlapping ticks)
- **LLM insight mining** (Claude): comment pain-points · format patterns · style-cards → Brain Store
- **Generation pipeline**: evidence-ranked ideas → **virality gate** → outline → expand → polish
- **Demand validation** (Google Trends + search-suggest) + **local vector search** (TF-IDF RAG)
- **API key auth** (optional, off for local dev)
- LLM provider interface (Claude-CLI default + API-key fallback)
- **Frontend (Vite/React)** wired to the real API: Sources/Brain admin · Insights · Script Writer · Demand & Search
- Tests: `test_throttle`, `test_virality`, `test_generation`, `test_extras` (all pass)

---

## 2. Code still to build (post-MVP / scale)
- ⬜ **Upgrade vector search** from TF-IDF to embeddings + Qdrant/pgvector (current local index is fine for MVP)
- ⬜ **Whisper fallback** for no-caption videos (needs ffmpeg + faster-whisper/torch)
- ⬜ **Performance-feedback re-training** — feed published results back into the virality model
- ⬜ **Persisted ideas/scripts** + library UI (currently generation is stateless per request)
- ⬜ **Demand merged into idea ranking** (currently a standalone tool to keep generation fast/offline)

---

## 3. Data layer setup
- ⬜ **Vector DB** ("brain" semantic memory). Free MVP: **Chroma** (embedded, zero infra) or
  **pgvector** if you move to Postgres. Add an embeddings step (local `fastembed` = free).
- 🟡 **Primary DB**: SQLite works now. For a hosted/concurrent deploy, migrate to **Postgres**
  (Supabase/Neon free tier) — the code uses SQLModel, so it's a connection-string change + a
  migration tool (Alembic).
- ⬜ **Backups**: scheduled dump of the DB (and a raw-data export), since the Raw Lake is the
  source of truth everything is re-derived from.

---

## 4. Hosting / infrastructure
- ⬜ **Backend runner** (always-on, residential IP):
  - Free: your own machine / a mini-PC / home server running `uvicorn` + the scheduler.
  - Expose it securely with a **Cloudflare Tunnel** (free) or **Tailscale** — no port-forwarding,
    gives you an HTTPS URL for the frontend to call.
  - Alternative: a small VPS, but then you need a **residential proxy** (paid) to avoid IP blocks.
- ⬜ **Process management**: run uvicorn + scheduler as a service (systemd / NSSM on Windows /
  `pm2`) so it restarts on reboot/crash.
- ⬜ **Frontend**: deploy the Vite app to **Vercel**; set `VITE_API_BASE_URL` to the tunnel URL.
- ⬜ **Deno** + **ffmpeg** installed on the backend machine (yt-dlp robustness + whisper).

---

## 5. External services / APIs
| Service | Purpose | Free? | Setup needed |
|---|---|---|---|
| yt-dlp | metadata, signals, comments | ✅ free, no key | install Deno for reliability |
| youtube-transcript-api | transcripts | ✅ free | — |
| YouTube Data API v3 (optional) | more reliable comments/metadata | ✅ free quota (10k units/day) | Google Cloud project + API key |
| pytrends | Google Trends | ✅ free (unofficial) | — |
| search-suggest endpoint | autocomplete demand | ✅ free | — |
| Claude (Pro/Max) | reasoning + generation | 💳 your existing sub | `claude` login or `claude setup-token` |
| Embeddings (local) | vector search | ✅ free | `fastembed` model download |
| Residential proxy (optional) | scrape at scale w/o home IP | 💳 paid | only if not using home IP |
| Sentry (optional) | error tracking | ✅ free tier | DSN |
| ElevenLabs / MeloTTS | voiceover (optional) | MeloTTS free / EL paid | — |

---

## 6. Scraping reliability — the #1 ship risk ⚠️
- ✅ **Apify transcripts (LIVE & validated)** — `BRAIN_APIFY_TOKEN` + `BRAIN_APIFY_TRANSCRIPT_ACTOR=codepoetry~youtube-transcript-ai-scraper`
  are set in `backend/.env`. Transcripts now fetch from Apify first (captions, behind residential
  proxies → **no caption IP-block**), falling back to the local caption API / Whisper on error.
  This is gated independently of `scrape_provider`, so it's already active. Validated end-to-end
  (61 segments returned for a test video). Cost = pay-per-result; set `BRAIN_APIFY_ENABLE_AI_FALLBACK=true`
  only if you want paid AI transcription for caption-less videos.
- ⬜ **Apify for video signals + comments (optional, not yet wired to a real actor)** — to also move
  per-video metadata/comments off this box, set `BRAIN_SCRAPE_PROVIDER=apify` + a real
  `BRAIN_APIFY_VIDEO_ACTOR` (the default is a placeholder). The mapper in `apify.py:_to_ytdlp_info()`
  is defensive (handles flat or nested-`metadata` shapes); validate once and add any new key names
  if signals come back zeroed. Until then video stays on yt-dlp (which still returns comments).
- ⬜ Install **Deno** (yt-dlp warned: no JS runtime → some extractions degrade) — only matters for the yt-dlp fallback.
- ⬜ Run from a **residential IP** (home) — datacenter IPs get blocked. Confirmed in the architecture.
- ⬜ **Rate-limit + backoff + jitter**; scrape **periodically** via the scheduler, never per user request (already designed this way).
- ⬜ **Cookies** (`yt-dlp --cookies`) for consent/age-gated videos if you hit them.
- ⬜ Cap comment fetches (already `BRAIN_COMMENT_LIMIT`) — comments are the slow part.
- ⬜ Decide proxy strategy if you scale beyond one home IP (paid residential proxy pool).

---

## 7. Security & secrets
- ⬜ **API auth** before exposing publicly — currently the API is open. Add an API key / token check.
- ⬜ **Lock down CORS** — currently `allow_origins=["*"]`; restrict to your Vercel domain.
- ⬜ Keep all secrets in backend `.env` only; **never** ship keys in the frontend bundle.
- ⬜ HTTPS everywhere (Cloudflare Tunnel / Vercel give this for free).

---

## 8. Ops & observability
- ⬜ **Structured logging** + log rotation on the backend.
- ⬜ **Error tracking** (Sentry free tier) for ingestion + generation failures.
- ⬜ **Uptime/health monitor** hitting `/health` (UptimeRobot free).
- ⬜ **Scheduler visibility** — surface last-run + new-videos counts in the admin UI (data already in `IngestRun`).
- ⬜ **Backups** (see §3).

---

## 9. Legal / ToS note
- Scraping YouTube is against YouTube's ToS; you're relying on yt-dlp + your own IP. For a
  personal/research tool this is the common path, but be aware of the risk, **rate-limit
  politely**, and prefer the official **YouTube Data API** where it covers your needs (comments,
  metadata). Don't redistribute scraped transcripts/comments publicly.

---

## 10. Minimal path to "live" (ordered) — MVP code is done; remaining is deploy/ops
1. ✅ Build the product (backend + frontend) — done, runs on localhost.
2. Install **Deno + ffmpeg**; log in to **Claude** on the backend machine.
3. Set **`BRAIN_API_KEY`** (backend) + **`VITE_API_KEY`** (frontend); lock **CORS** to your domain.
4. Run backend as a **service** on your machine; expose via **Cloudflare Tunnel**; deploy frontend to **Vercel** with `VITE_API_BASE_URL` pointing at the tunnel.
5. Add **monitoring + backups** (Sentry/UptimeRobot free; dump the SQLite DB).
6. Scale later: Postgres+pgvector + embeddings, residential proxy, TTS, performance-feedback re-training.

---

## Decisions you'll need to make
- **Backend host:** your machine + Cloudflare Tunnel (free) vs a VPS + residential proxy (paid)?
- **Vector DB:** Chroma (local, simplest) vs pgvector (if you move to Postgres) vs Qdrant?
- **Embeddings:** local free (`fastembed`) vs paid (better quality)?
- **DB:** stay on SQLite for MVP, or go straight to Postgres for a hosted setup?
- **Comments source:** keep yt-dlp only, or add the free **YouTube Data API** for reliability?
