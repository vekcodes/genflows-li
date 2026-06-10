"""Layer D: transcript chunking + a local vector index for semantic retrieval (RAG).

Uses scikit-learn TF-IDF (already a dependency) so it's fully local and free — no model
downloads, no external vector DB. This is the MVP "brain memory"; swap in embeddings +
Qdrant/pgvector at scale behind the same `search()` signature.
"""
from __future__ import annotations

from sqlmodel import Session, delete, select

from .models import Chunk


def chunk_text(text: str, *, max_chars: int = 1600, overlap: int = 200) -> list[str]:
    """Split into ~500-token windows (≈1600 chars) with a little overlap."""
    text = (text or "").strip()
    if not text:
        return []
    step = max(1, max_chars - overlap)
    return [text[i : i + max_chars] for i in range(0, len(text), step)]


def index_video(session: Session, video_id: str, text: str) -> int:
    """(Re)build chunks for one video. Caller commits."""
    session.exec(delete(Chunk).where(Chunk.video_id == video_id))
    chunks = chunk_text(text)
    for idx, c in enumerate(chunks):
        session.add(Chunk(video_id=video_id, idx=idx, text=c))
    return len(chunks)


def search(session: Session, query: str, *, k: int = 8) -> list[dict]:
    """Top-k transcript chunks most relevant to the query (cosine over TF-IDF)."""
    rows = session.exec(select(Chunk)).all()
    if not rows or not query.strip():
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:  # pragma: no cover
        return []

    texts = [r.text for r in rows]
    vec = TfidfVectorizer(stop_words="english", max_features=4096)
    matrix = vec.fit_transform(texts)
    qv = vec.transform([query])
    sims = cosine_similarity(qv, matrix)[0]
    order = sims.argsort()[::-1][:k]
    return [
        {
            "video_id": rows[i].video_id,
            "idx": rows[i].idx,
            "score": round(float(sims[i]), 4),
            "text": rows[i].text[:300],
        }
        for i in order
        if sims[i] > 0
    ]
