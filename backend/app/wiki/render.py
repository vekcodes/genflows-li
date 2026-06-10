"""Page renderers for the Brain Wiki.

Turns Raw-Lake rows + an LLM source summary into markdown pages, and merges new evidence
into existing pages *in place* so knowledge compounds (never delete-and-rebuild). Every
performance number is quoted from the DB / virality model and cited by ``video_id`` — these
renderers never invent one.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlmodel import Session, select

from ..generation import prompts
from ..llm.base import LLMProvider
from ..llm.parse import complete_json
from ..models import Transcript, Video
from .store import WikiStore

MAX_CHANNEL_TRANSCRIPT_CHARS = 6000


def slugify(text: str, *, fallback: str = "untitled", max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].strip("-") or fallback


def _link(subdir: str, key: str) -> str:
    """An Obsidian-style wikilink to a page by its (to-be-)slugified key."""
    return f"[[{subdir}/{slugify(key)}]]"


def _mult_str(mult: float | None) -> str:
    return f"{mult}×" if mult is not None else "—"


def _dedupe_append(items: list[dict], new: dict, key: str) -> list[dict]:
    """Append ``new`` unless an item with the same ``key`` value is already present."""
    if any(i.get(key) == new.get(key) for i in items):
        return items
    return [*items, new]


def _example_lines(examples: list[dict]) -> str:
    """`- <mult> — <title> [[sources/<id>]]` rows, strongest first."""
    rows = []
    for e in sorted(examples, key=lambda e: (e.get("multiplier") or 0), reverse=True):
        title = e.get("title", "")
        rows.append(f"- {_mult_str(e.get('multiplier'))} — {title} {_link('sources', e.get('video_id', ''))}")
    return "\n".join(rows)


# ---- source page (atomic ingest unit) ----

def source_page(
    store: WikiStore, video: Video, summary: dict[str, Any], mult: float | None, today: date
) -> str:
    rel = f"sources/{slugify(video.id)}.md"
    channel = video.channel_name or video.channel_id
    fmt = str(summary.get("format", "")).strip()
    takeaways = [str(t).strip() for t in (summary.get("takeaways") or []) if str(t).strip()]
    signals = [s for s in (summary.get("audience_signals") or []) if s.get("question")]

    fm = {
        "type": "source",
        "title": video.title,
        "slug": slugify(video.id),
        "video_id": video.id,
        "channel": channel,
        "multiplier": mult,
        "updated": today.isoformat(),
        "summary": (summary.get("hook") or "").strip()[:140],
    }
    body = [
        f"# {video.title}",
        f"**Channel:** {_link('channels', channel)}  ·  "
        f"**Outlier:** {_mult_str(mult)} (views ÷ channel median, from the Raw Lake)  ·  `{video.id}`",
        f"**Hook:** {summary.get('hook', '').strip()}",
        f"**Format:** {_link('formats', fmt)} — {summary.get('why_it_works', '').strip()}",
    ]
    if takeaways:
        body.append("## Takeaways\n" + "\n".join(f"- {t}" for t in takeaways))
    if signals:
        sig_rows = [f"- {s['question'].strip()} {_link('audience', s['question'])}" for s in signals]
        body.append("## Audience signals\n" + "\n".join(sig_rows))
    return store.write(rel, fm, "\n\n".join(body))


# ---- channel entity page ----

def channel_page(
    session: Session,
    store: WikiStore,
    video: Video,
    mult: float | None,
    llm: LLMProvider,
    today: date,
) -> str:
    name = video.channel_name or video.channel_id
    rel = f"channels/{slugify(name)}.md"

    rows = session.exec(
        select(Transcript.text)
        .join(Video, Video.id == Transcript.video_id)
        .where(Video.channel_id == video.channel_id)
        .limit(8)
    ).all()
    excerpt = "\n---\n".join(t for t in rows if t)[:MAX_CHANNEL_TRANSCRIPT_CHARS]
    card: dict[str, Any] = {}
    if excerpt:
        system, prompt = prompts.style_card(name, excerpt)
        card = complete_json(llm, prompt, system=system) or {}

    existing = store.read(rel)
    prev_fm = existing[0] if existing else {}
    history = _dedupe_append(
        list(prev_fm.get("outliers") or []),
        {"video_id": video.id, "title": video.title, "multiplier": mult},
        "video_id",
    )
    # Prefer this run's style card; fall back to the page's stored style so a missing/empty
    # card never wipes prior knowledge.
    prev_style = prev_fm.get("style") or {}
    style = {
        "tone": (card.get("tone") or prev_style.get("tone") or "").strip(),
        "pacing": (card.get("pacing") or prev_style.get("pacing") or "").strip(),
        "hooks": [str(h).strip() for h in (card.get("hooks") or prev_style.get("hooks") or []) if str(h).strip()],
        "vocabulary": [str(v).strip() for v in (card.get("vocabulary") or prev_style.get("vocabulary") or []) if str(v).strip()],
    }
    hooks, vocab = style["hooks"], style["vocabulary"]

    fm = {
        "type": "channel",
        "title": name,
        "slug": slugify(name),
        "channel_id": video.channel_id,
        "updated": today.isoformat(),
        "source_count": len(history),
        "summary": (style["tone"] or prev_fm.get("summary") or "").strip()[:140],
        "style": style,
        "outliers": history,
    }
    body = [
        f"# {name}",
        "## Style card",
        f"- **Tone:** {card.get('tone', '').strip() or '_n/a_'}",
        f"- **Pacing:** {card.get('pacing', '').strip() or '_n/a_'}",
        f"- **Hooks:** {', '.join(hooks) or '_n/a_'}",
        f"- **Vocabulary:** {', '.join(vocab) or '_n/a_'}",
        "## Outlier history (from the Raw Lake)",
        _example_lines(history),
    ]
    return store.write(rel, fm, "\n\n".join(body))


# ---- format concept page ----

def format_page(
    store: WikiStore, fmt: str, summary: dict[str, Any], video: Video, mult: float | None, today: date
) -> str:
    rel = f"formats/{slugify(fmt)}.md"
    existing = store.read(rel)
    prev_fm = existing[0] if existing else {}
    examples = _dedupe_append(
        list(prev_fm.get("examples") or []),
        {"video_id": video.id, "title": video.title, "multiplier": mult},
        "video_id",
    )
    mults = [e["multiplier"] for e in examples if e.get("multiplier") is not None]
    avg = round(sum(mults) / len(mults), 2) if mults else None

    fm = {
        "type": "format",
        "title": fmt,
        "slug": slugify(fmt),
        "updated": today.isoformat(),
        "source_count": len(examples),
        "avg_multiplier": avg,
        "summary": (summary.get("why_it_works") or prev_fm.get("summary") or "").strip()[:140],
        "examples": examples,
    }
    body = [
        f"# Format — {fmt}",
        summary.get("why_it_works", "").strip(),
        f"**Avg outlier across examples:** {_mult_str(avg)} (from the Raw Lake)",
        "## Examples",
        _example_lines(examples),
    ]
    return store.write(rel, fm, "\n\n".join(body))


# ---- audience concept page ----

def audience_page(store: WikiStore, signal: dict[str, Any], video: Video, today: date) -> str | None:
    question = str(signal.get("question") or "").strip()
    if not question:
        return None
    rel = f"audience/{slugify(question)}.md"
    existing = store.read(rel)
    prev_fm = existing[0] if existing else {}
    examples = _dedupe_append(
        list(prev_fm.get("examples") or []),
        {"video_id": video.id, "quote": str(signal.get("example") or "").strip()},
        "video_id",
    )
    quote_rows = [
        f"- \"{e['quote']}\" {_link('sources', e.get('video_id', ''))}"
        for e in examples
        if e.get("quote")
    ]
    fm = {
        "type": "audience",
        "title": question,
        "slug": slugify(question),
        "updated": today.isoformat(),
        "source_count": len(examples),
        "summary": question[:140],
        "examples": examples,
    }
    body = [
        f"# Audience — {question}",
        "Recurring pain-point / question surfaced from comments.",
        "## Evidence",
        "\n".join(quote_rows) or "_(no quotes captured)_",
    ]
    return store.write(rel, fm, "\n\n".join(body))


# ---- index (rebuilt from disk, always consistent) ----

_CATEGORIES = [
    ("Channels (entities)", "channels"),
    ("Formats (concepts)", "formats"),
    ("Audience (pain-points / demand)", "audience"),
    ("Sources (per-video summaries)", "sources"),
    ("Filed queries", "queries"),
]


def rebuild_index(store: WikiStore, today: date) -> str:
    lines = [
        "# Brain Wiki — Index",
        "Auto-rebuilt on every ingest. Read this first when answering a query, then drill in.",
        "## Synthesis",
        "- [[overview]] — what's working now",
    ]
    for heading, subdir in _CATEGORIES:
        pages = store.list(subdir)
        if not pages:
            continue
        rows = []
        for rel in pages:
            page = store.read(rel)
            fm = page[0] if page else {}
            label = str(fm.get("summary") or fm.get("title") or rel).strip()
            tail = ""
            if fm.get("type") == "source" and fm.get("multiplier") is not None:
                tail = f" · {fm['multiplier']}×"
            elif fm.get("type") == "format" and fm.get("avg_multiplier") is not None:
                tail = f" · avg {fm['avg_multiplier']}×"
            link = f"[[{rel[:-3]}]]"
            rows.append(f"- {link} — {label}{tail}")
        lines.append(f"## {heading}\n" + "\n".join(rows))
    fm = {"type": "index", "title": "Brain Wiki — Index", "updated": today.isoformat()}
    return store.write("index.md", fm, "\n\n".join(lines))
