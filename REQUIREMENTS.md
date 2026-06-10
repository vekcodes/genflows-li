# Requirements — Brain OS + YouTube Script Writer

Derived from `ARCHITECTURE.md`. The **Brain** is a reusable, self-updating YouTube knowledge
engine; the **only consumer built in this repo is the YouTube Script Writer**, and every idea/
script it produces must be **backtested for virality**. Other tools (LinkedIn, X, newsletter…)
are explicitly **out of scope** — they will be separate future repos that call the Brain API.

Legend: **[BE]** backend (`backend/`) · **[FE]** frontend (Vite/Vercel) · **[★]** virality core ·
status: ✅ done · 🟡 partial · ⬜ not started.

---

## 1. Functional requirements

### 1.1 Sources (Layer A)
- **FR-1.1** [BE] ✅ Register sources (channel/playlist/video URLs) you can add any time.
- **FR-1.2** [BE] ✅ Classify source kind; resolve YouTube id on first ingest.
- **FR-1.3** [FE] ⬜ Admin console to add sources and watch the Brain grow.

### 1.2 Continuous ingestion (Layer B)
- **FR-2.1** [BE] ✅ Resolve video vs channel/playlist (`yt-dlp --flat-playlist`).
- **FR-2.2** [BE] ✅ Incremental — fetch only videos not already in the Raw Lake.
- **FR-2.3** [BE] ✅ Fetch signals (views/likes/duration/dates/title/description) + comments.
- **FR-2.4** [BE] ✅ Fetch transcripts (youtube-transcript-api); 🟡 whisper fallback deferred.
- **FR-2.5** [BE] ✅ Scheduler re-checks sources past their cadence (opt-in), non-overlapping ticks.
- **FR-2.6** [BE] Run on a residential IP; scrape periodically, never per user request.
- **FR-2.7** [BE] ✅ Scraping politeness: per-video jittered delay, retry+backoff, rolling-hour cap.

### 1.3 Raw Lake + Processing (Layers C–D)
- **FR-3.1** [BE] ✅ Append-only store: Source · Video · Transcript · Comment · IngestRun.
- **FR-3.2** [BE] ✅ Channel baselines (median views).
- **FR-3.3** [BE] ⬜ Transcript chunking (~500 tok) + embeddings → vector index.

### 1.4 The Brain (Layer E)
- **FR-4.1** [BE] ✅ Outlier scoring (views ÷ channel median); 3–10× = proven demand.
- **FR-4.2** [BE][★] ✅ **Virality model** — predict outlier multiplier from publish-time
  features (title traits, format, duration).
- **FR-4.3** [BE][★] ✅ **Backtest** — time-based split (train old → test new); report
  **ROC-AUC, precision@k, rank correlation**; re-fit on every ingest. Validated by a planted-
  signal test.
- **FR-4.4** [BE] ✅ LLM pattern mining (winning formats) — Claude.
- **FR-4.5** [BE] ✅ LLM comment → pain-point extraction — Claude.
- **FR-4.6** [BE] ✅ LLM style-card extraction (tone/pacing/hooks/vocab) — Claude.
- **FR-4.7** [BE] ⬜ Content-gap + demand validation (Trends + search-suggest).

### 1.5 Brain API (Layer F)
- **FR-5.1** [BE] ✅ Sources CRUD + ingest trigger.
- **FR-5.2** [BE] ✅ `brain/status`, `baselines`, `outliers`.
- **FR-5.3** [BE][★] ✅ `virality/backtest` (held-out report) + `virality/score` (candidate → 0-100 + analogs).
- **FR-5.4** [BE] 🟡 `get style-card` ✅ + `rank ideas` ✅ (`/generate/ideas`); `validate demand` ⬜.
- **FR-5.5** [BE] ⬜ Auth on the API (multi-tool ready).

### 1.6 YouTube Script Writer (Layer G — the only consumer here)
- **FR-6.1** [BE] ✅ Evidence-ranked idea generation (proven demand + gap + style fit) — Claude.
- **FR-6.2** [BE][★] ✅ **Virality backtest gate** — score each candidate; drop low-score;
  survivors carry a predicted multiplier + nearest proven analogs.
- **FR-6.3** [BE] ✅ Outline → section-wise expand → polish (Hook · Setup · Body×3-4 · CTA).
- **FR-6.4** [FE] ⬜ UI: ranked ideas + why (evidence + predicted virality) → editable script (markdown) → regenerate → export.
- **FR-6.5** [BE] ⬜ Performance-feedback re-training loop (future).

---

## 2. Non-functional requirements
- **NFR-1** Brain backend = Python/FastAPI; runs near a residential IP (not Vercel).
- **NFR-2** Script-writer frontend = Vite/React/TS on Vercel, via `VITE_API_BASE_URL`.
- **NFR-3** Reasoning engine = **Claude via subscription** (Claude Code CLI; no API billing),
  behind one swappable `LLMProvider`.
- **NFR-4** Virality claims must be **backtested on held-out data**; report the metric with the score.
- **NFR-5** "Self-updating" = re-ingest + re-fit + re-backtest as sources grow (not weight-training).
- **NFR-6** Brain API stays general so future tools (separate repos) can consume it; only the
  YouTube consumer is built here.
- **NFR-7** No secrets in any frontend bundle.

## 3. Build order (status)
1. ✅ Sources + incremental ingestion → Raw Lake (SQLite).
2. ✅ Baselines + outlier scoring.
3. ✅ **Virality model + backtester**.
4. ✅ LLM insight mining (patterns · pain-points · style) via Claude.
5. ⬜ Demand validation (Trends + search-suggest).
6. 🟡 Brain API: style-card ✅ · rank-ideas ✅ · demand ⬜ · auth ⬜.
7. 🟡 YouTube Script Writer: ideas → **virality gate** → outline → expand → polish ✅ (backend);
   Vite UI + admin ⬜.
8. ⬜ Scale: vector DB · performance-feedback re-training · TTS.
