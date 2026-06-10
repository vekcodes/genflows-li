---
type: home
title: GenFlows Content Engine — Vault Home
updated: 2026-06-04
---

# 🧠 GenFlows Content Engine — Vault Home

This Obsidian vault is the **visual + knowledge layer** over the YouTube content engine.
Code lives in `backend/` and `src/` (hidden from the file explorer); this vault surfaces the
diagrams and the Brain's compounding knowledge.

## 🗺️ Start here
- **[[content-engine.canvas|Pipeline map (Canvas)]]** — how a script gets made, end to end.
  Click to open the visual board; drag nodes, zoom, edit.

## 📚 The Brain Wiki (Karpathy LLM-Wiki pattern)
The compounding markdown knowledge — creator styles, winning formats, audience pain-points,
per-video takeaways. Maintained by Claude on each ingest (currently **flag-gated OFF**, so it's
still scaffold; turn on `BRAIN_WIKI_ENABLED` to populate).

- [[index|Wiki Index]] — catalog of every page (read this first)
- [[log|Provenance log]] — append-only ingest/query/lint history
- Schema & rules: `backend/brain_wiki/CLAUDE.md`

## How the layers fit (the hard boundary)
- **Quantitative core (authoritative):** SQLite lake + the sklearn **virality model** (ROC-AUC
  ~0.93). All scores/multipliers come from here — the wiki never invents numbers.
- **Qualitative wiki (this vault):** explains *why* things work, and links liberally with
  `[[wikilinks]]`.

> Tip: open the **graph view** (left sidebar) once the wiki is populated to see the knowledge
> graph of channels ↔ formats ↔ pain-points.
