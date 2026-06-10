"""DB engine + session helpers (Raw Lake storage) — SQLite locally, Postgres when hosted."""
from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
# check_same_thread=False so the scheduler thread can share the engine.
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(
    _settings.database_url,
    echo=False,
    connect_args=_connect_args,
    # Hosted Postgres (Neon/Supabase) closes idle connections; pre-ping replaces dead ones
    # instead of erroring mid-request. No-op cost on a healthy pool.
    pool_pre_ping=not _is_sqlite,
)


def init_db() -> None:
    # Import models so SQLModel registers the tables before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
