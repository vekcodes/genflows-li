"""Brain API entrypoint.  Run:  uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import assistant, brain, content, cron, generate, sources
from .config import get_settings
from .db import init_db
from .scheduler import start_scheduler, stop_scheduler
from .scrape_queue import resume_pending

# Only the data/generation API is gated by the password. The SPA shell, static assets,
# /health and /docs stay public so the app can load and prompt for the password client-side.
# (/cron/* runs its own Bearer-secret auth.)
GUARDED_API_PREFIXES = ("/sources", "/brain", "/generate", "/assistant", "/content")

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings = get_settings()
    if settings.serverless:
        # Serverless (Vercel): no background threads/scheduler — work runs in-request and the
        # periodic jobs are driven by Vercel Cron via /cron/*. Skip fail_interrupted_runs too:
        # instances start while another instance is mid-generation, and marking its live run
        # as error would kill a healthy batch.
        yield
        return
    # Fail any content run left 'running' by a previous process (its worker thread is gone),
    # so the UI doesn't poll a zombie batch forever.
    from . import agent
    from .db import engine
    from sqlmodel import Session as _Session

    with _Session(engine) as _s:
        n = agent.fail_interrupted_runs(_s)
        if n:
            logging.getLogger("brain.agent").info("marked %s interrupted content run(s) as error", n)
    resume_pending()  # start the scrape-queue worker + re-enqueue any pending scrapes
    if settings.scheduler_enabled:
        start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Brain OS API",
    version=__version__,
    summary="Self-updating YouTube knowledge engine — the contract consumer apps call.",
    lifespan=lifespan,
)

# Consumer-app frontends (Vite/Vercel) call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    key = get_settings().api_key
    if key and request.method != "OPTIONS" and request.url.path.startswith(GUARDED_API_PREFIXES):
        if request.headers.get("x-api-key") != key:
            return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)
    return await call_next(request)


app.include_router(sources.router)
app.include_router(brain.router)
app.include_router(generate.router)
app.include_router(assistant.router)
app.include_router(content.router)
app.include_router(cron.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


# ---- Serve the built frontend (single-origin deploy) ----
# When the Vite build exists at repo-root/dist, this API also serves the SPA, so the whole app
# can sit behind one URL (e.g. a Cloudflare tunnel). Build with VITE_API_BASE_URL=/ so the
# frontend calls this same origin. If dist/ is absent (pure-API deploy), `/` returns JSON.
_DIST = Path(__file__).resolve().parents[2] / "dist"

if _DIST.is_dir():
    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _spa_root():
        return FileResponse(_DIST / "index.html")

    # SPA fallback: any non-API, non-file path returns index.html (client-side routing).
    # Registered last, so the API routers above always take precedence.
    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
else:
    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {"service": "brain-os", "version": __version__, "docs": "/docs"}
