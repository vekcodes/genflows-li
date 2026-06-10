# Plan — Adopting the LLM-Wiki pattern in the Brain (Hybrid)

**Status:** proposal for review · **Date:** 2026-06-03 · **Pattern:** karpathy's *LLM Wiki*
(gist `442a6bf555914893e9891c11519de94f`) · **Decision taken:** Hybrid — keep the quantitative
core, add a compounding qualitative wiki.

This plan changes **no running backend code**. It records what we'd build, in what order, with
the boundaries that keep the backtested virality claim intact. The schema lives in
`backend/brain_wiki/CLAUDE.md`; the skeleton wiki is seeded under `backend/brain_wiki/wiki/`.

---

## 1. The change in one paragraph

Today the Brain's *qualitative* knowledge (`app/insights.py`: pain-points, format patterns,
style cards) is **recomputed and overwritten** every run — `delete(...)` then re-insert. Nothing
accumulates; there's no history, no cross-reference, no contradiction tracking. We replace that
recompute-and-wipe loop with an **ingest that updates a persistent, interlinked markdown wiki in
place**, so knowledge *compounds* with every video. The `app/vectorstore.py` TF-IDF index is
demoted to an optional search tool behind the wiki's `index.md`. The `app/virality.py` model +
held-out backtest is **untouched** and remains the sole authority on virality numbers.

## 2. What stays vs. what changes

| Component | Verdict | Why |
|---|---|---|
| Raw Lake (`models.py`, ingestion/*) | **Unchanged** | Already immutable/append-only = karpathy's "raw sources". |
| `virality.py` (sklearn model + backtest) | **Unchanged** | NFR-4: virality must be backtested on held-out data. The wiki explains *why*; it never *decides*. |
| `insights.py` (mine_*) | **Re-targeted** | Same prompts, new output: page-writers that update wiki files instead of `delete`+insert DB rows. DB tables kept during dual-write. |
| `vectorstore.py` (TF-IDF) | **Demoted** | Becomes the "search CLI tool the agent shells out to"; `index.md` covers the common case at current scale. |
| `generation/ideas.py`, `script.py`, `refine.py` | **Re-pointed** | Read wiki pages (overview/format/audience/channel) as context; still call `virality.score()` as the gate. |
| `brain.py`, `api/*`, `scheduler.py` | **Extended** | New ingest/query/lint entry points + a wiki status surface; nothing removed. |

## 3. Page model (maps existing tables → wiki pages)

| Existing DB table | Becomes wiki page | Notes |
|---|---|---|
| `StyleCard` (per channel) | `channels/<slug>.md` | tone/pacing/hooks/vocab + outlier history that grows over time |
| `FormatPattern` (per niche) | `formats/<slug>.md` | description + example `video_id`s + `avg_multiplier` (quoted from DB) |
| `PainPoint` (per niche) | `audience/<slug>.md` | clustered pain-points, with example comments + frequency |
| *(new)* per video | `sources/<video_id>.md` | summary, hook, format, takeaways; the atomic ingest unit |
| *(new)* synthesis | `overview.md` | "what's working now"; refreshed only when evidence shifts |
| *(new)* navigation | `index.md`, `log.md` | catalog + append-only provenance |

## 4. Phased build (each phase independently shippable)

### Phase 1 — Schema + skeleton ✅ (this PR, additive only)
- `backend/brain_wiki/CLAUDE.md` — conventions, frontmatter, ingest/query/lint workflows, hard rules.
- `backend/brain_wiki/wiki/{index,log}.md` — seeded templates.
- **No code touched.** Acceptance: schema reviewed and agreed.

### Phase 2 — Ingest (dual-write, behind a flag)
- New `app/wiki/` package: `store.py` (read/write/list markdown + frontmatter, path-safe slugs),
  `ingest.py` (orchestrates the per-video flow from the schema), `render.py` (page templates).
- Reuse `generation/prompts.py` style/format/pain prompts as **page-writers** (text → md sections),
  not JSON-into-DB.
- Wire into `ingestion/pipeline.py` *after* a video's transcript + multiplier exist, gated by a
  config flag `BRAIN_WIKI_ENABLED` (default off). Keep `insights.py` DB writes running in parallel.
- The maintainer LLM is the existing `LLMProvider` (Claude CLI) — no new dependency.
- Acceptance: ingesting one real video produces `sources/<id>.md` + updated channel/format/
  audience pages + `index.md`/`log.md` entries, with all multipliers traceable to the DB.

### Phase 3 — Generation reads the wiki
- `generation/ideas.py`: context = `overview.md` + top `formats/*` + `audience/*` (via wiki store
  or the search tool) instead of `list_patterns`/`list_pain_points` DB reads.
- `generation/script.py`: pull the channel's `channels/<slug>.md` style page.
- **`virality.score()` stays the gate** — survivors still carry predicted multiplier + analogs.
- Run old (DB) and new (wiki) context side-by-side once to compare idea quality before flipping default.
- Acceptance: scripts generated from wiki context pass the same backtest gate; output parity or better.

### Phase 4 — Lint + search (optional, scale)
- `app/wiki/lint.py` + a `brain/wiki/lint` endpoint and an opt-in scheduled pass in `scheduler.py`
  (mirrors the existing cadence/non-overlap design).
- Expose `vectorstore.search()` as the agent's search tool; only invoked when `index.md` is thin.
- Surface wiki health (page counts, contested/stale) in the Assistant sidebar `brain-mini` block.

## 5. Risks & mitigations

- **Drift / hallucinated numbers** → hard rule: numbers come from DB only, cited by `video_id`;
  `virality.py` remains authoritative; `lint` flags `contested`/`stale`.
- **Ingest latency / call volume** (5–15 pages × Claude per source) → on subscription/CLI this is
  time, not money; keep ingest async in the pipeline, batchable, flag-gated; the UI already warns
  ingestion "takes time."
- **Two sources of truth during migration** → dual-write in Phase 2, compare in Phase 3, retire the
  `insights.py` DB writes only after parity is shown.
- **Path safety** (wiki is files) → strict slug/`video_id` validation in `store.py`; wiki is a git
  repo of markdown, so every change is diffable and revertible.

## 6. Open questions for you

1. **Wiki location & versioning** — keep `wiki/` as its own git repo (free history/branching, per
   the gist), or a plain dir inside the backend? (Recommend: git repo.)
2. **Ingest trigger** — automatic in the scheduler (your app is hands-off), or human-in-the-loop
   one-at-a-time as karpathy prefers? (Recommend: auto-ingest + periodic auto-lint, Assistant UI as
   the "browse" surface.)
3. **Niche scoping** — one wiki for everything, or one wiki per niche? (Recommend: one wiki, niche
   as frontmatter `tags`, since formats/pain-points cross niches.)
4. **Per-video summary depth** — terse (hook+format+3 takeaways) vs. rich (full beat breakdown).
   Affects ingest cost. (Recommend: terse now, rich on demand via Query.)

## 7. Out of scope (explicitly not in this change)
Retraining the virality model, embeddings/Qdrant migration, TTS, the demand-validation layer
(FR-4.7), and any frontend rebrand work (already done separately).
