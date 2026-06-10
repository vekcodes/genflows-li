# Brain Wiki — Log

Append-only record of what happened and when. One entry per ingest / query / lint.
Entries start with a consistent prefix so the log is greppable:

```
grep "^## \[" log.md | tail -5      # last 5 events
```

Entry format:

```
## [YYYY-MM-DD] ingest | <channel> — <title> (<mult>×)
touched: sources/<id>, channels/<slug>, formats/<slug>, audience/<slug>

## [YYYY-MM-DD] query | <question>
filed: queries/<slug>

## [YYYY-MM-DD] lint | <n> contradictions, <n> stale, <n> orphans
follow-up: <suggested sources / questions>
```

---

<!-- new entries appended below this line -->
