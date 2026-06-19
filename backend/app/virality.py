"""★ Engagement model + backtester (Layer E) — LinkedIn edition.

Turns "will this post go viral?" into a measurable, *backtested* claim.

- Features are everything knowable at write time (post text traits, format).
- Target is the realised engagement multiplier (reactions ÷ author median).
- The backtest uses a time-based split (train on older posts, test on newer).

Pure analytics over the Raw Lake — no LLM required.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from sqlmodel import Session, select

from .config import get_settings
from .models import LinkedInPost

FEATURE_NAMES: list[str] = [
    "post_length",
    "line_count",
    "has_hook",
    "is_listicle",
    "is_story",
    "is_how_to",
    "is_question",
    "is_contrarian",
    "has_emoji",
    "has_cta",
    "has_number",
]

_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff\U00002600-\U000027BF]", flags=re.UNICODE)
_LISTICLE_RE = re.compile(r"^\s*\d+[\.\)]\s|\b\d+\s+(ways|tips|mistakes|lessons|rules|steps|signs|things|reasons)\b", re.I)
_STORY_RE = re.compile(r"\b(i was|i am|i used to|my story|last year|a year ago|when i|i remember|true story|confession)\b", re.I)
_HOWTO_RE = re.compile(r"\b(how to|how i|step by step|guide|framework|playbook|system|formula)\b", re.I)
_CONTRARIAN_RE = re.compile(r"\b(wrong|stop|don't|dont|myth|truth|nobody|everyone|never|secret|unpopular|controversial|hot take)\b", re.I)
_CTA_RE = re.compile(r"\b(comment|like|share|follow|repost|dm me|reach out|link in bio|save this|drop a|let me know|thoughts\?|agree\?|what do you think)\b", re.I)
_HOOK_STARTERS = re.compile(r"^(i |we |you |the |this |why |how |what |when |if |here|just|stop|most|many|every|never|always|last |a |an |in |on )", re.I)


def extract_features(text: str) -> dict[str, float]:
    t = text or ""
    lines = [l for l in t.split("\n") if l.strip()]
    first_line = lines[0] if lines else ""
    return {
        "post_length": float(len(t)),
        "line_count": float(len(lines)),
        "has_hook": 1.0 if (len(first_line) <= 120 and bool(_HOOK_STARTERS.match(first_line))) else 0.0,
        "is_listicle": 1.0 if bool(_LISTICLE_RE.search(t)) else 0.0,
        "is_story": 1.0 if bool(_STORY_RE.search(t)) else 0.0,
        "is_how_to": 1.0 if bool(_HOWTO_RE.search(t)) else 0.0,
        "is_question": 1.0 if "?" in t else 0.0,
        "is_contrarian": 1.0 if bool(_CONTRARIAN_RE.search(t)) else 0.0,
        "has_emoji": 1.0 if bool(_EMOJI_RE.search(t)) else 0.0,
        "has_cta": 1.0 if bool(_CTA_RE.search(t)) else 0.0,
        "has_number": 1.0 if bool(re.search(r"\d", t)) else 0.0,
    }


def dominant_format(feats: dict[str, float]) -> str:
    if feats["is_listicle"]:
        return "listicle"
    if feats["is_story"]:
        return "story"
    if feats["is_how_to"]:
        return "howto"
    if feats["is_contrarian"]:
        return "contrarian"
    return "other"


@dataclass
class Row:
    post_id: str
    text: str
    multiplier: float
    label: int
    published_at: datetime
    fmt: str
    features: list[float] = field(default_factory=list)


def _author_medians(posts: list[LinkedInPost]) -> dict[str, float]:
    by: dict[str, list[int]] = {}
    for p in posts:
        if p.reactions > 0:
            by.setdefault(p.author_id, []).append(p.reactions)
    return {aid: float(median(rs)) for aid, rs in by.items() if rs}


def collect_rows(session: Session, *, threshold: float) -> list[Row]:
    posts = session.exec(select(LinkedInPost)).all()
    medians = _author_medians(posts)
    rows: list[Row] = []
    for p in posts:
        med = medians.get(p.author_id, 0.0)
        if med <= 0 or p.published_at is None or p.reactions <= 0:
            continue
        mult = p.reactions / med
        feats = extract_features(p.text)
        rows.append(
            Row(
                post_id=p.id,
                text=p.text[:120],
                multiplier=round(mult, 3),
                label=1 if mult >= threshold else 0,
                published_at=p.published_at,
                fmt=dominant_format(feats),
                features=[feats[name] for name in FEATURE_NAMES],
            )
        )
    return rows


MIN_ROWS = 20


def backtest(session: Session, *, threshold: float = 2.0, test_frac: float = 0.3) -> dict:
    rows = collect_rows(session, threshold=threshold)
    n = len(rows)
    base = {"status": "ok", "n": n, "viral_threshold": threshold}

    if n < MIN_ROWS:
        return {**base, "status": "insufficient_data",
                "message": f"need >= {MIN_ROWS} posts with publish dates, have {n}"}

    n_viral = sum(r.label for r in rows)
    if n_viral == 0 or n_viral == n:
        return {**base, "status": "insufficient_data",
                "message": f"need both high- and low-engagement examples (viral={n_viral}/{n})"}

    try:
        import numpy as np
        from scipy.stats import spearmanr
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        return {**base, "status": "error", "message": f"ML deps missing: {exc}"}

    rows.sort(key=lambda r: r.published_at)
    cut = int(n * (1 - test_frac))
    train, test = rows[:cut], rows[cut:]
    if len(train) < 8 or len(test) < 4 or len({r.label for r in train}) < 2:
        return {**base, "status": "insufficient_data",
                "message": "time split left too little signal in train/test"}

    X_train = np.array([r.features for r in train])
    y_train = np.array([r.label for r in train])
    X_test = np.array([r.features for r in test])
    y_test = np.array([r.label for r in test])
    mult_test = np.array([r.multiplier for r in test])

    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]

    auc = float(roc_auc_score(y_test, proba)) if len(set(y_test)) > 1 else None
    order = np.argsort(proba)[::-1]
    k = min(10, len(test))
    precision_at_k = float(y_test[order[:k]].mean())
    base_rate = float(y_test.mean())
    spearman = spearmanr(proba, mult_test).statistic
    spearman = None if spearman != spearman else float(spearman)

    logreg = model.named_steps["logisticregression"]
    coefs = dict(zip(FEATURE_NAMES, logreg.coef_[0].tolist()))
    top = sorted(coefs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:6]

    return {
        **base,
        "n_train": len(train),
        "n_test": len(test),
        "n_viral": n_viral,
        "base_rate": round(base_rate, 4),
        "roc_auc": None if auc is None else round(auc, 4),
        "precision_at_k": round(precision_at_k, 4),
        "k": k,
        "lift_at_k": round(precision_at_k / base_rate, 3) if base_rate > 0 else None,
        "spearman_corr": None if spearman is None else round(spearman, 4),
        "top_features": [{"feature": f, "weight": round(w, 3)} for f, w in top],
        "train_span": [train[0].published_at.date().isoformat(), train[-1].published_at.date().isoformat()],
        "test_span": [test[0].published_at.date().isoformat(), test[-1].published_at.date().isoformat()],
    }


_fit_lock = threading.Lock()
_fit_cache: dict | None = None


def _fitted(session: Session, *, threshold: float) -> dict:
    global _fit_cache
    from sqlalchemy import func

    n_posts = session.exec(select(func.count()).select_from(LinkedInPost)).one()
    n_posts = (id(session.get_bind()), n_posts)
    ttl = get_settings().virality_cache_ttl_sec
    with _fit_lock:
        c = _fit_cache
        if (
            c is not None
            and c["key"] == n_posts
            and c["threshold"] == threshold
            and time.monotonic() - c["built_at"] < ttl
        ):
            return c

    rows = collect_rows(session, threshold=threshold)
    entry: dict = {
        "key": n_posts, "threshold": threshold, "built_at": time.monotonic(),
        "rows": rows, "model": None, "backtest": None,
    }
    if len(rows) >= MIN_ROWS and len({r.label for r in rows}) == 2:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        X = np.array([r.features for r in rows])
        y = np.array([r.label for r in rows])
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))
        model.fit(X, y)
        entry["model"] = model
        entry["backtest"] = backtest(session, threshold=threshold)
    with _fit_lock:
        _fit_cache = entry
    return entry


def score(session: Session, *, title: str, duration_sec: int = 0, threshold: float = 2.0) -> dict:
    """Score a candidate post idea/hook text (0-100) for predicted engagement."""
    try:
        import numpy as np
    except ImportError as exc:
        return {"status": "error", "message": f"ML deps missing: {exc}"}

    fitted = _fitted(session, threshold=threshold)
    rows, model = fitted["rows"], fitted["model"]
    if model is None:
        n = len(rows)
        return {"status": "insufficient_data", "n": n,
                "message": f"need >= {MIN_ROWS} posts across both engagement classes (have {n})"}

    feats = extract_features(title)
    fmt = dominant_format(feats)
    vec = np.array([[feats[name] for name in FEATURE_NAMES]])
    proba = float(model.predict_proba(vec)[0, 1])

    viral = [r for r in rows if r.label == 1]
    same_fmt = [r for r in viral if r.fmt == fmt] or viral
    analogs = sorted(same_fmt, key=lambda r: r.multiplier, reverse=True)[:3]

    bt = fitted["backtest"] or {}
    return {
        "status": "ok",
        "title": title,
        "format": fmt,
        "virality_score": round(proba * 100, 1),
        "predicted_viral": proba >= 0.5,
        "viral_threshold": threshold,
        "model_confidence_auc": bt.get("roc_auc"),
        "nearest_analogs": [
            {"video_id": a.post_id, "title": a.text, "multiplier": round(a.multiplier, 2)}
            for a in analogs
        ],
    }
