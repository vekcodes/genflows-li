# Single-image deploy: build the Vite frontend, then run the FastAPI backend which serves
# BOTH the API and the built SPA (one origin, one URL). Works on Render / Railway / Fly / any
# Docker host. The backend reads dist/ at repo-root (see app/main.py).

# ---- Stage 1: build the frontend ----
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig*.json ./
COPY public ./public
COPY src ./src
# Same-origin API calls (the backend serves this SPA).
RUN VITE_API_BASE_URL=/ npm run build   # -> /app/dist

# ---- Stage 2: backend runtime ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# System deps: ffmpeg only needed if local Whisper is enabled (off in cloud). Keep image lean.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend ./backend
COPY --from=frontend /app/dist ./dist

# main.py resolves dist at parents[2] of backend/app/main.py == /app, so /app/dist is correct.
WORKDIR /app/backend
EXPOSE 8000
# Render/Railway inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
