# The Brain OS — a self-updating YouTube knowledge engine, with a backtested-for-virality script writer

> **Goal:** keep adding YouTube channels/videos → the system scrapes them, analyzes **what
> actually performs** + validates **market demand**, and accumulates a reusable **Brain** of
> proven topics, winning formats, audience pain-points, content gaps and creator style.
> On top of the Brain sits **one consumer app in this repo: the YouTube Script Writer** — and
> every idea/script it produces is **backtested for virality** against the Brain's real history
> before it's surfaced.

**Scope of this repo (locked in):**
- The **Brain stays general and reusable** (an API other tools can call) — but the **only
  consumer built here is the YouTube Script Writer**. LinkedIn / X / newsletter and other tools
  are **out of scope** and will live in **separate future repos** that call this Brain's API.
- The script writer must be **backtested for virality**: predictions are validated on held-out
  historical videos, so "this will perform" is evidence, not vibes.

**Decisions locked in:**
- Data sourcing = **Hybrid DIY scrape** — pull the signals that feed content (outliers,
  comments, gaps). Don't rebuild a vidIQ-style dashboard.
- Market scope = **YouTube signals + search/trend demand** (Google Trends + search-suggest).
- **Reasoning engine = Claude via subscription** (Claude Code CLI headless; no API billing).
  Pluggable behind one `LLMProvider` interface.

### What "trains itself" honestly means
The Brain is **not** a neural net learning weights from scratch. It is a **continuously-updated
knowledge base + a virality model**: every new source re-runs ingestion → enrichment → insight
extraction, so the stores (insights + embeddings) grow, and the **virality model is re-fit and
re-backtested** on the larger corpus. It gets sharper as you feed it — via accumulation, RAG,
and a refreshed predictor — not gradient descent on an LLM.

---

## Layered architecture

```
A SOURCES ─▶ B CONTINUOUS INGESTION ─▶ C RAW LAKE ─▶ D PROCESSING ─▶ E THE BRAIN ★ ─▶ F BRAIN API ─▶ G YOUTUBE SCRIPT WRITER
   (you add)    (scheduled, incremental)  (append-only)  (enrich)      insights +              (the contract)   ideas → ★ virality
        ▲                                                              VIRALITY MODEL                              backtest gate →
        └──────────────── continuous self-update / re-fit + re-backtest ◀──────────────┘                         script
```
See `architecture.excalidraw` for the full visual. Other consumer tools are intentionally not
drawn — they are separate future repos hanging off the same Brain API.

---

## A · Sources (you keep adding)
- **Sources registry / watchlist** — channels, playlists, individual video URLs. Append any
  time; this is the dial that grows the Brain.

## B · Continuous Ingestion (scheduled · incremental)
- **Scheduler / jobs** — periodically re-checks each channel and pulls **only new videos**.
- **URL resolver** — video vs channel/playlist (`yt-dlp --flat-playlist`).
- **Transcripts** — `youtube-transcript-api` (primary) + `faster-whisper` fallback; timestamps kept.
- **Signals** — `yt-dlp --dump-json` (views, likes, duration, publish date, title, description).
  **This is what analysis actually runs on — not transcripts.**
- **Comments** — `commentThreads` / `--write-comments`.
- ⚠️ YouTube blocks datacenter IPs → scrape from a **residential IP / proxy**, periodically.

## C · Raw Lake (append-only)
- Immutable raw store of transcripts · metadata · signals · comments; everything downstream is
  re-derivable from it.

## D · Processing & Enrichment (re-runs on every new batch → self-updating)
- **Chunk transcripts** (~500 tokens, keep `videoId`/timestamp metadata).
- **Channel baselines** — median views per channel (the outlier denominator).
- **Embeddings** → **vector index** (Qdrant / Chroma / pgvector) for semantic retrieval.

## E · The Brain ★ (reusable knowledge + insights + the virality model — the moat)
LLM steps powered by **Claude (subscription)**.
- **Outlier scoring** — `views ÷ channel median`. 3–10× = **proven demand**. Highest-value signal.
- **Pattern mining (LLM)** — cluster winners into formats ("how-to", "X mistakes", contrarian…).
- **Comment → pain-point extraction (LLM)** — audience's exact questions/requests.
- **Content-gap + demand validation** — merge YouTube gaps with Trends + search-suggest.
- **Style-card extraction (LLM)** — tone/pacing/hooks/vocabulary per creator.
- **★ Virality model + backtester** — the part that makes "will this go viral?" a *measurable*
  claim:
  - **Features known at publish time** (no leakage): title/format pattern, title traits (number,
    question, "you", brackets, length), topic embedding vs proven topics, duration bucket,
    demand signal.
  - **Target:** the realized outlier multiplier (`views ÷ channel median`); "viral" = ≥ threshold (e.g. 3×).
  - **Backtest:** **time-based split** (train on older videos, test on newer) → **ROC-AUC**,
    **precision@k**, and rank **correlation** between predicted score and actual multiplier.
    Re-fit + re-backtested on every ingest, so accuracy is always reported on real, held-out data.
- → **Brain Store**: proven topics · winning formats · audience questions · gaps · style-cards ·
  vector embeddings · **the fitted virality model + its latest backtest report**.

## F · Brain API / SDK (the contract)
The single boundary tools call — REST + a typed client. Stable shapes. Capabilities:
- `query insights` · `semantic search (RAG)` · `get style-card` · `validate demand`
- `score virality {title, format, topic, duration, channel}` → predicted multiplier + confidence
- `virality backtest report` → current AUC / precision@k / correlation on held-out data
- `rank ideas for {goal, channel}` → evidence- **and virality-** ranked ideas
> Other future tools (LinkedIn, etc.) are just additional clients of this same API.

## G · YouTube Script Writer (the only consumer app here)
Powered by the Brain; **every step is evidence- and virality-gated**.
1. **Evidence-ranked ideas** — candidates from proven topics + gaps + style fit (LLM, style-matched).
2. **★ Virality backtest gate** — each candidate is **scored by the backtested virality model** and
   compared to its nearest proven outliers ("closest historical analog got 8×"). Low-confidence /
   low-score ideas are dropped; survivors carry a predicted multiplier + the evidence behind it.
3. **Outline → section-wise expand → polish** — explicit Hook · Setup · Body×3-4 · CTA, one LLM call per beat.
4. **Output** — ranked ideas + *why* (cited evidence + predicted virality), full editable script
   (markdown), regenerate loop back to the outline.
- **Performance feedback (future)** — once published, real performance feeds back to re-train the
  virality model (closing the loop). Drawn dashed; not in the first build.

---

## Cross-cutting
- **Claude (subscription)** — reasoning engine for mining + generation, behind one `LLMProvider`.
- **Orchestration** — LangGraph for the agentic generation graph.
- **Self-update loop** — adding a source re-runs B→E and **re-fits + re-backtests** the virality model.

---

## Tech stack
| Layer | Choice |
|---|---|
| Brain backend | Python · FastAPI · LangGraph |
| Jobs / scheduler | APScheduler (runs near a residential IP) |
| Ingestion | youtube-transcript-api · yt-dlp · faster-whisper |
| Demand | pytrends · search-suggest endpoints |
| Analysis | pandas (outlier math) + Claude (pattern/comment/style mining) |
| **Virality model + backtest** | scikit-learn (logistic regression / gradient boosting) · pandas · numpy |
| Raw + insights store | SQLite (MVP) → Postgres (+ pgvector) |
| Vector DB at scale | Qdrant / Chroma / pgvector |
| LLM | **Claude via subscription** (pluggable); Gemini/Groq/Ollama optional fallbacks |
| Script-writer frontend | Vite · React · TypeScript on Vercel (consumes the Brain API) |
| TTS (optional) | MeloTTS / ElevenLabs |

## Deployment reality
- **Brain backend + scheduler** can't run on Vercel — they need long-running workers and a
  **residential IP** for scraping. Run on your machine / a small VPS + residential proxy; expose
  the FastAPI Brain API from there.
- **Script-writer frontend** is Vite + React on **Vercel**, talking to the Brain API via `VITE_API_BASE_URL`.

## Build order
1. ✅ Sources registry + continuous ingestion → Raw Lake (SQLite). *(done)*
2. ✅ Channel baselines + outlier scoring. *(done)*
3. **★ Virality model + backtester** (features → predict outlier multiplier → time-split backtest).
4. LLM insight mining (comment pain-points · format patterns · style-cards) via Claude.
5. Demand validation (Trends + search-suggest) merged into the Brain.
6. Brain API capabilities (incl. `score virality`, `backtest report`, `rank ideas`).
7. YouTube Script Writer: evidence-ranked ideas → **virality gate** → outline → expand → polish,
   plus the Vite frontend + an admin console to add sources and watch the Brain grow.
8. Scale: vector DB · performance-feedback re-training loop · TTS.
