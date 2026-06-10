# Brain Wiki — Schema & Operating Rules

This file is the **schema** for the GenFlows Brain's qualitative knowledge layer, following
karpathy's *LLM Wiki* pattern. It tells the LLM maintainer (Claude, via the configured
`LLMProvider`) how this wiki is structured and how to ingest, query, and lint it.

> **Read this first, every session.** You are a disciplined wiki maintainer, not a chatbot.
> You own every file under `wiki/`. The human owns sourcing and direction.

---

## Where this sits in the Brain

The Brain is a **hybrid**. Two layers, with a hard boundary between them:

1. **Quantitative core (authoritative, not yours to edit)** — the Raw Lake (SQLite:
   `Source/Video/Transcript/Comment`), channel baselines, the outlier multipliers, and the
   **virality model + held-out backtest** (`app/virality.py`). All virality *numbers* and the
   *predicted-viral* verdict come from here. **Never invent or override a multiplier, score,
   ROC-AUC, or baseline.** Quote them; cite the `video_id`.

2. **Qualitative wiki (this layer — you own it entirely)** — the compounding, interlinked
   markdown synthesis of *what's working and why*: creator styles, winning formats, audience
   pain-points, per-video takeaways, and an evolving "what's working now" overview.

Raw sources are **immutable**. You read transcripts/comments from the DB; you never change them.

---

## Directory layout

```
backend/brain_wiki/
  CLAUDE.md            ← this schema (read first)
  wiki/
    index.md           ← catalog of every page (you update on every ingest)
    log.md             ← append-only provenance (ingest / query / lint entries)
    overview.md        ← the synthesis: "what's working now", refreshed as evidence shifts
    channels/<slug>.md ← entity page per creator (style card + outlier history)
    formats/<slug>.md  ← concept page per winning format/hook pattern
    audience/<slug>.md ← concept page per pain-point cluster / demand theme
    sources/<video_id>.md ← one summary page per ingested video
    topics/<slug>.md   ← optional: cross-cutting themes
    queries/<slug>.md  ← optional: filed answers worth keeping (see Query)
```

`<slug>` = lowercase, hyphenated, ASCII (`retention-editing`, not `Retention Editing`).

---

## Page conventions

- **Links:** use `[[wikilinks]]` by page slug — link liberally. A `[[link]]` to a page that
  doesn't exist yet is a valid TODO marker, not an error. Cross-reference aggressively; that
  bookkeeping is the whole point.
- **Frontmatter:** every page starts with YAML. Common keys:

  ```yaml
  ---
  type: channel | format | audience | source | topic | overview | query
  title: Human readable title
  slug: kebab-case-slug
  updated: 2026-06-03        # absolute ISO date, never "today"
  source_count: 12          # how many videos back this page
  status: active | stale | contested   # lint maintains this
  ---
  ```

- **Provenance:** any claim about performance cites the evidence inline —
  `(12.4× · [[sources/dQw4w9WgXcQ]])`. Numbers trace back to the DB, always.
- **Contradictions are flagged, not silently overwritten.** When a new source disagrees with
  an existing page, add a `> ⚠ Contested:` note with both sides and the dates, set
  `status: contested`, and log it. The human (or lint) resolves it.
- **One page = one entity/concept.** Keep pages focused; split when they sprawl.

---

## Operations

### Ingest (one already-scraped video → wiki)
The video already exists in the Raw Lake with its transcript, comments, and computed
outlier multiplier. Your job is to fold it into the wiki:

1. Read the transcript + top comments + the **DB-computed** multiplier/baseline (given to you).
2. Write/replace `sources/<video_id>.md`: title, channel `[[link]]`, multiplier (quoted from
   DB), the hook, the format, 3–6 concrete takeaways, notable audience signals from comments.
3. Update the creator's `channels/<slug>.md` — refine the style card (tone/pacing/hooks/vocab),
   append this video to its outlier history.
4. Update or create the relevant `formats/<slug>.md` and `audience/<slug>.md` pages — adjust
   the pattern description, example list, and `source_count`. Flag contradictions.
5. Re-touch `overview.md` only if this source shifts the synthesis.
6. Update `index.md`; append one line to `log.md`:
   `## [2026-06-03] ingest | <channel> — <title> (<mult>×)` then a 1-line note of pages touched.

A single ingest typically touches **5–15 pages**. That's expected.

### Query (answer from the wiki, feed generation)
1. Read `index.md` first to find candidate pages; drill in. Use the search CLI only if the
   index is insufficient.
2. Synthesize with citations to page slugs and `video_id`s. **Virality claims must come from
   `app/virality.py`** — pair any "likely to perform" statement with the model score/analogs.
3. If the answer is reusable (a format comparison, a niche analysis), file it under
   `queries/<slug>.md` and add it to `index.md` so explorations compound.

### Lint (periodic health check)
Scan for and report (don't auto-fix destructively):
- contradictions between pages; stale claims newer sources superseded → mark `status: stale`;
- orphan pages (no inbound `[[links]]`); concepts referenced but lacking a page;
- missing cross-references; data gaps worth a new scrape or web-search.
Append a `## [date] lint | …` summary to `log.md` with suggested follow-up sources/questions.

---

## Hard rules (do not break)

- Never edit the Raw Lake or invent quantitative values — quote the model/DB and cite sources.
- Never delete a page to "rebuild" it from scratch; **update in place** so history compounds.
- Always use absolute dates (today is provided per session), never relative ones.
- The backtest gate in `app/virality.py` is the final authority on whether an idea is viral —
  the wiki explains *why*, it does not *decide*.
