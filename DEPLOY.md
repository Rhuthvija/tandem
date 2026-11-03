# Deploying Tandem (Render + Neon)

Tandem is a FastAPI app (`server.py`) serving `static/index.html`. Each browser
gets a private user id (generated client-side); user data lives in Postgres
(`DATABASE_URL`) or, without it, in local `data/` files.

## 1. Database (Neon)

1. Create a project at [Neon](https://neon.tech) (free tier is fine).
2. Copy the pooled connection string — it looks like
   `postgresql://user:pass@ep-xxxx.region.aws.neon.tech/dbname?sslmode=require`.
3. No migrations needed: the app creates the `users` and `card_images`
   tables itself on startup.

## 2. Web service (Render)

1. Push this repo to GitHub, then **New → Web Service** in Render and point it
   at the repo (`render.yaml` fills in the commands).
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Environment variables:
   - `MODEL_API_KEY` — your Meta Model API key (secret).
   - `DATABASE_URL` — the Neon connection string (secret).
5. Deploy. Open the service URL — onboarding should appear on first load.

## 3. Local dev

```sh
.venv/bin/python -m uvicorn server:app --port 8000
```

Keep `MODEL_API_KEY` in `.env` (loaded automatically). Leave `DATABASE_URL`
unset to store each user's data under `data/` (git-ignored).

## Notes

- Old single-user installs kept everything in `memory.json`; the app no longer
  reads it. Per-user files live at `data/{user_id}.json` instead.
- `data/` and `.env` are git-ignored; never commit secrets.
