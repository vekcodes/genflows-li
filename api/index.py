"""Vercel serverless entrypoint — serves the whole FastAPI backend as one function.

vercel.json rewrites every API path (/sources, /brain, /content, ...) to this function;
the ASGI app receives the original path, so the FastAPI routes match unchanged. The Vite
SPA is served by Vercel's static layer from dist/ (built with VITE_API_BASE_URL=/), so the
app is single-origin just like the Docker deploy.

Requires (Vercel project env): BRAIN_DATABASE_URL=postgresql://... (Neon/Supabase — the
filesystem here is ephemeral, SQLite won't persist), BRAIN_LLM_PROVIDER=anthropic +
BRAIN_ANTHROPIC_API_KEY, and BRAIN_APIFY_TOKEN for scraping/transcripts. See DEPLOY.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

os.environ.setdefault("BRAIN_SERVERLESS", "true")

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402, F401  (Vercel serves any ASGI `app`)

# The serverless adapter may not run FastAPI's lifespan; create_all is idempotent, so make
# sure the tables exist on every cold start.
init_db()
