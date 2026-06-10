"""★ Virality model + backtester (Layer E).

Turns "will this go viral?" into a measurable, *backtested* claim.

- Features are everything knowable **at publish time** (title traits, format, duration) — no
  leakage from a video's eventual success.
- Target is the realized **outlier multiplier** (views ÷ channel median); "viral" = ≥ threshold.
- The backtest uses a **time-based split** (train on older videos, test on newer) and reports
  ROC-AUC, precision@k, and rank correlation between predicted score and actual multiplier.

Pure analytics over the Raw Lake — no LLM required. scikit-learn is imported lazily so the rest
of the API works even if it isn't installed.
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
from .models import Video

# Fixed feature order — used to build model input vectors consistently.
FEATURE_NAMES: list[str] = [
    "title_chars",
    "title_words",
    "has_number",
    "has_question",
    "has_you",
    "has_brackets",
    "is_listicle",
    "is_howto",
    "is_contrarian",
    "caps_ratio",
    "duration_min",
]

_LISTICLE_RE = re.compile(r"^\s*\d+\s|\b\d+\s+(things|ways|mistakes|tips|reasons|signs|steps|rules)\b")
_CONTRARIAN_RE = re.compile(r"\b(wrong|stop|don't|dont|myth|truth|nobody|everyone|never|secret)\b")
_YOU_RE = re.compile(r"\byou\b|\byour\b")


def extract_features(title: str, duration_sec: int) -> dict[str, float]:
    t = title or ""
    low = t.lower()
    words = re.findall(r"\w+", t)
    wc = len(words)
    caps = sum(1 for w in words if len(w) > 1 and w.isupper())
    return {
        "title_chars": float(len(t)),
        "title_words": float(wc),
        "has_number": 1.0 if re.search(r"\d", t) else 0.0,
        "has_question": 1.0 if "?" in t else 0.0,
        "has_you": 1.0 if _YOU_RE.search(low) else 0.0,
        "has_brackets": 1.0 if re.search(r"[\[\(]", t) else 0.0,
        "is_listicle": 1.0 if _LISTICLE_RE.search(low) else 0.0,
        "is_howto": 1.0 if ("how to" in low or "how i" in low) else 0.0,
        "is_contrarian": 1.0 if _CONTRARIAN_RE.search(low) else 0.0,
        "caps_ratio": (caps / wc) if wc else 0.0,
        "duration_min": (duration_sec or 0) / 60.0,
    }


def dominant_format(feats: dict[str, float]) -> str:
    if feats["is_listicle"]:
        return "listicle"
    if feats["is_howto"]:
        return "howto"
    if feats["is_contrarian"]:
        return "contrarian"
    return "other"


@dataclass
class Row:
    video_id: str
    title: str
    multiplier: float
    label: int
    published_at: datetime
    fmt: str
    features: list[float] = field(default_factory=list)


def _channel_medians(videos: list[Video]) -> dict[str, float]:
    by: dict[str, list[int]] = {}
    for v in videos:
        if v.views > 0:
            by.setdefault(v.channel_id, []).append(v.views)
    return {cid: float(median(vs)) for cid, vs in by.items() if vs}


def collect_rows(session: Session, *, threshold: float) -> list[Row]:
    """Build labelled feature rows from every ingested video with a known publish date."""
    videos = session.exec(select(Video)).all()
    medians = _channel_medians(videos)
    rows: list[Row] = []
    for v in videos:
        med = medians.get(v.channel_id, 0.0)
        if med <= 0 or v.published_at is None or v.views <= 0:
            continue
        mult = v.views / med
        feats = extract_features(v.title, v.duration_sec)
        rows.append(
            Row(
                video_id=v.id,
                title=v.title,
                multiplier=round(mult, 3),
                label=1 if mult >= threshold else 0,
                published_at=v.published_at,
                fmt=dominant_format(feats),
                features=[feats[name] for name in FEATURE_NAMES],
            )
        )
    return rows


# ---- Backtest ----

MIN_ROWS = 24  # below this, a held-out backtest isn't meaningful


def backtest(session: Session, *, threshold: float = 3.0, test_frac: float = 0.3) -> dict:
    rows = collect_rows(session, threshold=threshold)
    n = len(rows)
    base = {"status": "ok", "n": n, "viral_threshold": threshold}

    if n < MIN_ROWS:
        return {**base, "status": "insufficient_data",
                "message": f"need >= {MIN_ROWS} videos with publish dates, have {n}"}

    n_viral = sum(r.label for r in rows)
    if n_viral == 0 or n_viral == n:
        return {**base, "status": "insufficient_data",
                "message": f"need both viral and non-viral examples (viral={n_viral}/{n})"}

    try:
        import numpy as np
        from scipy.stats import spearmanr
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:  # pragma: no cover
        return {**base, "status": "error", "message": f"ML deps missing: {exc}"}

    # Time-based split: oldest -> train, newest -> test (no leakage).
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

    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]

    auc = float(roc_auc_score(y_test, proba)) if len(set(y_test)) > 1 else None
    order = np.argsort(proba)[::-1]
    k = min(10, len(test))
    precision_at_k = float(y_test[order[:k]].mean())
    base_rate = float(y_test.mean())
    spearman = spearmanr(proba, mult_test).statistic
    spearman = None if spearman != spearman else float(spearman)  # NaN guard

    # Standardised-feature coefficients → which traits drive virality.
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


# ---- Scoring a candidate idea/title ----

# A refine loop scores dozens of candidates per batch; refitting on the (unchanged) video set
# each time is pure waste. Cache the fitted production model + backtest, keyed on the video
# count and a TTL, so a batch fits once and rescraping/new ingests invalidate naturally.
_fit_lock = threading.Lock()
_fit_cache: dict | None = None  # {key, threshold, built_at, rows, model, backtest}


def _fitted(session: Session, *, threshold: float) -> dict:
    global _fit_cache
    from sqlalchemy import func

    n_videos = session.exec(select(func.count()).select_from(Video)).one()
    # Key on the engine too — tests/tools use separate (in-memory) engines whose row counts
    # can collide with each other.
    n_videos = (id(session.get_bind()), n_videos)
    ttl = get_settings().virality_cache_ttl_sec
    with _fit_lock:
        c = _fit_cache
        if (
            c is not None
            and c["key"] == n_videos
            and c["threshold"] == threshold
            and time.monotonic() - c["built_at"] < ttl
        ):
            return c

    rows = collect_rows(session, threshold=threshold)
    entry: dict = {
        "key": n_videos, "threshold": threshold, "built_at": time.monotonic(),
        "rows": rows, "model": None, "backtest": None,
    }
    if len(rows) >= MIN_ROWS and len({r.label for r in rows}) == 2:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        X = np.array([r.features for r in rows])
        y = np.array([r.label for r in rows])
        model = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced")
        )
        model.fit(X, y)
        entry["model"] = model
        entry["backtest"] = backtest(session, threshold=threshold)
    with _fit_lock:
        _fit_cache = entry
    return entry


def score(session: Session, *, title: str, duration_sec: int = 0, threshold: float = 3.0) -> dict:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        return {"status": "error", "message": f"ML deps missing: {exc}"}

    fitted = _fitted(session, threshold=threshold)
    rows, model = fitted["rows"], fitted["model"]
    if model is None:
        n = len(rows)
        return {"status": "insufficient_data", "n": n,
                "message": f"train the model first — need >= {MIN_ROWS} videos across both classes (have {n})"}

    feats = extract_features(title, duration_sec)
    fmt = dominant_format(feats)
    vec = np.array([[feats[name] for name in FEATURE_NAMES]])
    proba = float(model.predict_proba(vec)[0, 1])

    # Nearest proven analogs: top viral videos sharing the candidate's format.
    viral = [r for r in rows if r.label == 1]
    same_fmt = [r for r in viral if r.fmt == fmt] or viral
    analogs = sorted(same_fmt, key=lambda r: r.multiplier, reverse=True)[:3]

    bt = fitted["backtest"] or {}
    return {
        "status": "ok",
        "title": title,
        "format": fmt,
        "virality_score": round(proba * 100, 1),  # 0-100
        "predicted_viral": proba >= 0.5,
        "viral_threshold": threshold,
        "model_confidence_auc": bt.get("roc_auc"),  # how trustworthy the score is, from backtest
        "nearest_analogs": [
            {"video_id": a.video_id, "title": a.title, "multiplier": round(a.multiplier, 2)}
            for a in analogs
        ],
    }
