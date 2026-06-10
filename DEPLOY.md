# Deploy (test) — one hosted URL

This ships **one Docker service** that serves the API **and** the frontend. Good enough to test
on a real URL now; harden later (see bottom).

## What you get
- A public `https://<your-app>.onrender.com` running the whole app.
- The current Brain data (Eric's videos/transcripts) is baked into the image, so the deployed
  app has real content immediately.

## Known test-deploy limitations (by design — fix later)
- **Generation needs an Anthropic API key.** The Claude *subscription* CLI can't run in a
  container, so cloud uses the pay-per-token API. Without `BRAIN_ANTHROPIC_API_KEY`, the app
  runs but "generate" returns 501.
- **New video scraping (yt-dlp) is unreliable from a datacenter IP.** Transcripts via Apify work
  anywhere. To populate fresh data in cloud later, move video scraping to Apify or seed the DB.
- **Free plan spins down** after ~15 min idle (cold start on next visit) and the autonomous
  scheduler is off. Bump to a paid always-on plan to enable the weekly cron.

## Steps (Render)
1. **Put the code on GitHub** (Render deploys from a repo):
   ```
   git init
   git add -A
   git commit -m "Deploy: dockerized API+frontend"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
2. **Render → New + → Blueprint** → connect the repo. It reads `render.yaml` and creates the
   web service.
3. In the service's **Environment**, set the two secrets:
   - `BRAIN_ANTHROPIC_API_KEY` = `sk-ant-...`
   - `BRAIN_APIFY_TOKEN` = `apify_api_...`
4. Deploy. Open the URL. Done.

## Alternative: Railway (also Docker, one click)
`railway init` → `railway up` (uses the same `Dockerfile`), then set the same two env vars in the
Railway dashboard. Railway has no hard spin-down on its trial credit.

## Local sanity check (optional)
```
docker build -t yt-content-engine .
docker run -p 8000:8000 -e BRAIN_LLM_PROVIDER=none yt-content-engine
# open http://localhost:8000
```

## Hardening later (production)
- Always-on plan → set `BRAIN_SCHEDULER_ENABLED=true` for the weekly auto-generation.
- Postgres (Neon/Supabase) instead of the baked SQLite, so data persists across deploys
  (SQLModel = connection-string change + Alembic migration).
- Move video+comments scraping to Apify (a video actor) or a residential proxy.
- Add `BRAIN_API_KEY` + serve the frontend from Vercel separately if you want auth on the API.
- See `GOING_LIVE.md` for the full checklist.
