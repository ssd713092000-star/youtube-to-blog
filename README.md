# Tube2Dev

Turn a YouTube video into a dev.to post with a LangGraph pipeline (transcript → outline → parallel
section writing → fact-check/revise loop → human review → human-approved publish), served by FastAPI and
a Next.js frontend.

```
backend/    FastAPI API + worker, LangGraph graph, Alembic migrations   (Python 3.13, uv)
frontend/   Next.js 15 app                                              (Node 22)
infra/      bootstrap.sh (creates GCP resources), cloudbuild.yaml, local DB init
docs/       implementation plan, frontend design prompt
```

## Run locally

### Option A: offline (no GCP needed)

Uses local Postgres, a local volume instead of GCS, a local AES key instead of KMS, and dev sign-in
(any email). YouTube, OpenRouter and dev.to are real; add your keys in the app.

```bash
docker compose -f docker-compose.offline.yml up --build
```

- Web: http://localhost:3000 (sign in with any email)
- API docs: http://localhost:8000/docs
- Then go to **Settings → Integrations** and paste your OpenRouter and dev.to keys.

Stop with `docker compose -f docker-compose.offline.yml down` (add `-v` to wipe the data).

### Option B: against your GCP project (ADC)

Run this once the resources from `infra/bootstrap.sh` exist.

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/sqlservice.login
cp .env.example .env                    # GCP_PROJECT, CLOUD_SQL_INSTANCE, DB_IAM_USER, GCLOUD_CONFIG_DIR, Firebase web config
cp backend/.env.example backend/.env    # GCS_BUCKET, KMS_KEY_NAME, ...
docker compose up --build
```

### Option C: without Docker, for hot reload

```bash
# backend (needs a Postgres: the offline compose's `postgres` service works)
cd backend
uv sync
uv run python -m app.cli migrate
uv run python -m app.dev                      # API on :8000 with reload (uses backend/.env)

# frontend
cd frontend
cp .env.example .env.local
npm install
npm run dev                                   # http://localhost:3000
```

## Tests

```bash
cd backend && uv run pytest              # unit + integration (integration needs Docker)
cd frontend && npm test && npm run typecheck
```

## Regenerate the typed API client after backend changes

```bash
cd backend && uv run python -m app.cli openapi --out openapi.json
cd ../frontend && npm run gen:api
```

## Deploy (GCP, us-east1)

1. `PROJECT=<id> ./infra/bootstrap.sh` creates Cloud SQL (two DBs), GCS, KMS, Secret Manager, Cloud Tasks,
   Artifact Registry, service accounts and IAM. It then prints the remaining one-time steps.
2. `gcloud builds submit --config infra/cloudbuild.yaml --substitutions=_API_URL=...,_WEB_URL=...`
