# Tube2Dev — implementation plan

Source of truth for the build. Inputs: `notebooks/yt_to_devto_langgraph.ipynb` (graph logic),
`docs/frontend-design-prompt.md` (API contract + pages), `UI mockups for Tube2Dev/` (visual design).

---

## 0. Architecture

```
 Browser ──► tube2dev-web (Cloud Run, Next.js)
    │            │  Firebase ID token
    │            ▼
    └──SSE──► tube2dev-api (Cloud Run, FastAPI) ──enqueue──► Cloud Tasks "graph-runs"
                 │  │                                              │ OIDC
                 │  │ LISTEN job_events                            ▼
                 │  └──────────────────────────────── tube2dev-worker (Cloud Run, FastAPI)
                 │                                     runs / resumes the LangGraph graph
                 ▼                                                 │
   ┌─────────────────────────────── Cloud SQL (Postgres 16) ───────┴──────────────┐
   │ DB tube2dev_app:  users, jobs, job_events, articles, publish_attempts,       │
   │                   usage_ledger, idempotency_keys, model_cache                │
   │                   + LangGraph checkpoints + LangGraph store                  │
   │ DB tube2dev_credentials:  user_credentials (KMS-encrypted OpenRouter/dev.to) │
   └──────────────────────────────────────────────────────────────────────────────┘
   GCS  <project>-tube2dev-content   transcripts / sections / drafts (state stores gs:// URIs only)
   KMS  tube2dev/user-api-keys        encrypts per-user keys (AAD = user_id|provider)
   Secret Manager                     YouTube proxy creds, LangSmith key
```

Key decisions:

| Topic | Decision |
|---|---|
| GCP auth | **ADC everywhere.** Locally `gcloud auth application-default login`; on Cloud Run the service's own service account. No JSON key files. |
| Cloud SQL connection | **Cloud SQL Auth Proxy with `--auto-iam-authn`**: a sidecar container on Cloud Run, a local binary in dev. The app connects to `127.0.0.1:5432` as an IAM DB user with no password. psycopg3 for both SQLAlchemy and LangGraph (the Python Connector doesn't support psycopg). |
| Credentials DB | A separate **database** `tube2dev_credentials` with its own IAM DB user. Only `sa-api` and `sa-worker` can connect to it, and the app DB user has no grant on it. Same instance by default (cost); switch to a separate instance with one env var. |
| Key encryption | Cloud KMS `encrypt`/`decrypt`, with AAD = `user_id:provider`. Store the ciphertext, `last4`, `verified_at` and `status`. Plaintext lives only in memory for one request or run. |
| Keys and the graph | Keys are passed through **LangGraph runtime `context`** (`context_schema=JobContext`), which is *not* checkpointed. Never put them in state, `configurable`, logs or traces. |
| Long runs | API → Cloud Tasks → worker (dispatch deadline 30 min; each graph segment runs until the next interrupt). No `BackgroundTasks`. |
| Live progress | The worker inserts `job_events` and sends `NOTIFY job_<id>`. The API SSE endpoint `LISTEN`s and replays from `Last-Event-ID` (= `job_events.id`). |
| User auth | Firebase Auth (Identity Platform): Google sign-in plus email link. The backend verifies ID tokens with `firebase-admin` (ADC). |
| Hosting | 3 Cloud Run services + 2 Cloud Run jobs (migrate, cleanup). The browser calls the API origin directly (CORS locked to the web origin). |

---

## 1. Repo layout

```
backend/
  pyproject.toml            # moved from root, uv
  Dockerfile
  alembic/ alembic.ini
  app/
    main_api.py             # FastAPI app for tube2dev-api
    main_worker.py          # FastAPI app for tube2dev-worker (/internal/*)
    core/      config.py (pydantic-settings) · logging.py (JSON + request/job ids) · errors.py · security.py
    auth/      firebase.py (verify token → CurrentUser dependency)
    db/        app_engine.py · creds_engine.py · models_app.py · models_creds.py · repo_*.py
    services/  gcs.py · kms.py · credentials.py · youtube.py (proxy-aware) · devto.py (httpx)
               openrouter_models.py (pricing cache + estimates) · tasks.py (Cloud Tasks) · events.py (NOTIFY/LISTEN)
               usage.py (ledger, budget) · idempotency.py · locks.py (pg advisory locks)
    graph/     state.py · schemas.py · prompts.py · tools.py · llm.py (per-user ChatOpenRouter + fallbacks + usage callback)
               nodes/ (one file per node) · build.py · persistence.py · runner.py (run/resume + event emission)
    api/v1/    videos.py · jobs.py · drafts.py · review.py · publish.py · articles.py · style_profiles.py
               settings.py · integrations.py · usage.py · models.py · health.py
    worker/    internal.py (POST /internal/run-job, /internal/cleanup)
  tests/       unit/ (nodes with GenericFakeChatModel) · integration/ (testcontainers PG + fake-gcs) · e2e/
  evals/       dataset.yaml · run_evals.py
frontend/
  (Next.js 15 app — see §4)
infra/
  bootstrap.sh              # gcloud commands from §5, idempotent
  cloudbuild.yaml           # build → test → push → migrate → deploy
  env/                      # .env.example for api / worker / web
docs/
```

The notebook stays as a reference and isn't imported.

---

## 2. Backend — phases

### Phase B1: foundation
- `pydantic-settings` config: `GCP_PROJECT`, `REGION`, `APP_DB_URL`, `CREDS_DB_URL`, `GCS_BUCKET`, `KMS_KEY`, `TASKS_QUEUE`, `WORKER_URL`, `WEB_ORIGIN`, `YT_PROXY_SECRET`, `LANGSMITH_*`, limits (`MAX_NO_CHAPTER_DURATION`, `WINDOW_SECONDS`, default budgets, daily quota).
- Two async SQLAlchemy engines (psycopg) plus one shared `psycopg_pool.AsyncConnectionPool` for LangGraph (`autocommit=True, row_factory=dict_row, prepare_threshold=0`).
- Alembic with two migration trees (`app`, `creds`), plus a `setup_langgraph` step (`AsyncPostgresSaver.setup()` / `AsyncPostgresStore.setup()`), run by the `tube2dev-migrate` job.
- App tables:
  - `users(id, firebase_uid, email, created_at, settings jsonb)`
  - `jobs(id uuid, user_id, video_id, status, pending_action, current_step, steps jsonb, config jsonb, faithfulness, revision_count, cost_usd, budget_usd, devto_url, publish_status, error jsonb, checkpoint_id, created_at, updated_at)`
  - `job_events(id bigserial, job_id, type, payload jsonb, created_at)`
  - `articles(user_id, video_id UNIQUE together, job_id, devto_article_id, url, title, publish_status, published_at)`, which replaces `published_videos.json`
  - `publish_attempts(job_id PK, idempotency_key, state, devto_article_id, created_at)`
  - `usage_ledger(job_id, step, model, prompt_tokens, completion_tokens, cost_usd, created_at)`
  - `idempotency_keys(user_id, key, request_hash, response jsonb, created_at)`
  - `model_cache(id, data jsonb, fetched_at)`
- Credentials table: `user_credentials(user_id, provider, ciphertext bytea, kms_key_version, last4, status, verified_at, updated_at, PK(user_id, provider))`.
- Auth dependency: verify the Firebase token → upsert `users` → `CurrentUser`. Every job query is scoped by `user_id`; a foreign job returns 404.
- Middleware: request ID, JSON access logs, CORS, global error envelope `{error:{code,message,details}}`, rate limiting (per-user token bucket in Postgres, or `slowapi` behind a single instance).

### Phase B2: services
- `kms.py`: encrypt/decrypt with AAD. `credentials.py`: `put(user, provider, key)` verifies first (OpenRouter `GET /api/v1/key`; dev.to `GET /api/users/me` → username), then encrypts and stores. `get_plaintext(user, provider)` is used only by the worker and the test endpoint.
- `gcs.py`: async wrappers (`asyncio.to_thread`).
  - `put_text(job, kind, text) -> GcsRef{uri, sha256, size}` uses content-hash names: `users/{uid}/jobs/{job}/{kind}/r{rev}-{sha12}.md`.
  - Also `get_text(uri)` and `signed_url(uri)` (V4 signing through the IAM `signBlob` API, which works with ADC on Cloud Run).
- `youtube.py`: `yt-dlp` + `youtube-transcript-api` behind `asyncio.to_thread`, with Webshare proxy config from Secret Manager. Classify errors into `no_transcript | fetch_blocked | not_found`. Cache the raw transcript in GCS so it's fetched only once.
- `devto.py`: an httpx client with timeouts, `create_article`, `find_my_article(title|canonical)` for idempotent retries, and `get_me`.
- `openrouter_models.py`: fetch `GET https://openrouter.ai/api/v1/models` (cached for 1 hour in `model_cache`). Per-video cost estimate = transcript words × calibrated token multipliers per step × price; calibrate the multipliers from `usage_ledger` over the last 30 days. This backs the model picker's "This video ≈" column and the "~$0.07 / post" figure on the Defaults page.

### Phase B3: port the graph
State changes, compared with the notebook:

| Notebook field | New |
|---|---|
| `chapters[].text`, `cleaned_chapters[].text` | `transcript_ref`, `cleaned_transcript_ref` (GcsRef) + `chapter_index: [{title,start,end}]` |
| `section_drafts[].markdown` | `section_drafts[].ref` |
| `draft_markdown` | `draft_ref` + `draft_versions: list[{rev, kind, ref, created_at}]` |
| `final_markdown` | `final_ref` |
| `Send` payload `section_text` | `chapter_idxs` + `cleaned_transcript_ref` |
| interrupt payload `markdown` | `draft_rev` (the API serves the text) |
| `OPENROUTER_API_KEY`, `DEVTO_API_KEY` globals | `runtime.context.openrouter_key` / `devto_key` |
| `STYLE_EXAMPLES` | Store `("users", uid, "style", profile_id)` |
| registry JSON | `articles` table |

Node work:
- All nodes become `async def` with `runtime: Runtime[JobContext]`. The LLM is built per run: `ChatOpenRouter(api_key=ctx.openrouter_key, timeout, max_retries, max_tokens)`, plus `.with_fallbacks([...])` when the user enables fallbacks.
- A `UsageCallback` writes to `usage_ledger` (using OpenRouter's `usage.cost` in the response) and enforces `budget_usd`: it raises `BudgetExceeded` before the next call. The runner maps that to `failed / code=budget_exceeded` (the UI shows 402 and "raise budget & retry").
- `RetryPolicy(max_attempts=3, retry_on=transient)` on clean / plan / write / assemble / fact_check / metadata / social. **No retry policy on `publish`.**
- `revise_draft` revises **per section**: only the sections with unsupported claims or reviewer feedback. It then validates that every heading and every "▶ Watch" link survived; if not, it keeps the original section and records a note.
- `human_review` interrupt: payload = `ReviewPayload` (refs only). An `edit` resume carries `draft_ref` (the API has already written the markdown to GCS as `human_edit`).
- `publish`, made idempotent:
  1. lock the `publish_attempts` row
  2. if it's already `succeeded`, return the stored result
  3. if it's `in_flight` from a crashed attempt, call `devto.find_my_article` first
  4. otherwise POST and record the result

  The HITL middleware for the tool call stays as it is. `published` comes from the resume decision.
- `social_and_store`: insert into `articles` (the unique constraint catches duplicates) and write the social snippets to state (they're small).
- Tag cleaning, the gates at ingest, and fact-check scoring are kept as in the notebook. Ingest also checks the `articles` table.
- Prompt-injection hygiene: transcript text is wrapped in `<transcript>` delimiters with an instruction to treat it as data, and no agent that reads the transcript has the publish tool.

### Phase B4: runner, worker and events
- `runner.run_segment(job_id, input | Command)`:
  1. take a pg advisory lock on the job
  2. load the user's keys
  3. `graph.astream(..., stream_mode=["updates","custom"], context=JobContext, durability="async")`
  4. for each update: map it to step state, write a `job_events` row, update `jobs.steps`, send NOTIFY
  5. at the end: read `get_state` → set `status`, `pending_action` and `checkpoint_id`
- The `write_section` sub-items come from the `custom` stream (`get_stream_writer()`), giving per-section progress like "write 3/6".
- Worker: `POST /internal/run-job {job_id, resume?}`, which verifies the Cloud Tasks OIDC token (audience = worker URL, SA = `sa-tasks-invoker`). The task name is `job_id-segment_n`, so Cloud Tasks deduplicates repeats.
- Cancel sets `jobs.status=cancelled`; the runner checks it between steps and stops.
- The cleanup job (Cloud Scheduler, daily) deletes checkpoints for jobs that finished more than 30 days ago or were abandoned more than 14 days ago, deletes their GCS prefixes, and prunes `job_events` and `idempotency_keys`.

### Phase B5: API endpoints
Everything in the contract in `docs/frontend-design-prompt.md` §4, plus what the mockups require:
- `GET /models?q=&max_price_mtok=&min_context=&used_before=&sort=&video_id=` returns per-video `estimate_usd {low,high}` and `over_budget`.
- `GET /me/settings` includes `model_estimates` (average cost per post per model, last 30 days).
- `GET /jobs/{id}` includes `short_id` (`job_7f3a91`), the step `attempt` count, and `sub_items`.
- `GET /jobs/{id}/events`: SSE with `id:` = `job_events.id` and a heartbeat every 15s.

Resume endpoints (`/review`, `/publish`, `/cancel`, `/retry`):
1. The `Idempotency-Key` header is required. Store it with the request hash, and replay the stored response if the key arrives again.
2. Check `expected_checkpoint_id` against `jobs.checkpoint_id`, and check that the pending action matches. Otherwise return 409.
3. Enqueue the task and return 202.

`POST /jobs` checks, in order: keys present (else 412), daily quota (else 429), already published (else 409), budget greater than 0.

### Phase B6: quality
- Unit tests per node with `GenericFakeChatModel`, plus the gates, tag cleaning and scoring.
- Integration tests with Testcontainers Postgres, `fake-gcs-server`, a KMS fake behind the interface, and the full graph through both interrupts using a fake LLM.
- API tests: authorization (another user's job returns 404), idempotent replay, 409 on stale checkpoint, SSE replay.
- `evals/`: 10–20 real videos, measuring faithfulness, link and heading survival, cost and time; run on demand and before any prompt or model change.
- Observability: LangSmith tracing (key from Secret Manager, `hide_inputs` toggle), OpenTelemetry → Cloud Trace, JSON logs with `job_id` / `user_id` / `request_id`, and Error Reporting.

---

## 3. Design system (taken from the mockups)

- **Palette:** stone neutrals (`#fafaf9 #f5f5f4 #e7e5e4 #d6d3d1 #a8a29e #78716c #57534e #292524 #1c1917`), **one indigo accent `#5b5bd6`** (hover `#4343b8`, tint `#ececfb`), used only for primary actions and live state. Success `#166534/#dcfce7/#f0fdf4`, warning `#b45309/#92400e/#d97706/#fef3c7`, danger `#b91c1c`.
- **Type:** Geist for the UI, Geist Mono for timestamps, tags, IDs and money (`next/font`).
- Status always pairs a glyph with a label and a colour: `✓ ✕ ⊘ ❚❚ ◌ ○`, plus a spinner for running.
- **Motion kit**, all disabled under `prefers-reduced-motion`:
  - a pulse on the running pipeline node
  - a shimmer on running dashboard rows
  - the faithfulness gauge sweeping to its score
  - button transitions: copy → copied, approve → sending
  - the looping "transcript → post" demo on /login
- Shell: a 216px stone sidebar with the "t2" mark and the badge on Dashboard; the target canvas is 1280×820.
- The dark theme comes from the same tokens. The mockups don't show it yet, so it will be derived from the stone scale.

---

## 4. Frontend — phases

### F1: scaffold
- `frontend/`: Next.js 15 App Router, TypeScript strict, Tailwind v4, shadcn/ui (themed to the tokens above), lucide-react, TanStack Query v5, react-hook-form + zod, sonner, next-themes, date-fns.
- `lib/api/`: `openapi-typescript` types generated from the backend's `/openapi.json` (`pnpm gen:api`) and an `openapi-fetch` client with an auth middleware (Firebase ID token, refresh on 401, then retry once) and an error-envelope parser.
- MSW mocks (`NEXT_PUBLIC_API_MOCKS=true`) with fixtures matching the mockups exactly: the Rust CLI, Postgres indexes, Kubernetes operators, RSC (failed), tRPC (completed) and Docker (rejected) jobs. Include a mock SSE stream that replays a run.
- `lib/auth/`: Firebase web SDK with Google sign-in and email link; a `RequireAuth` layout guard.

### F2: design system and components
Build in this order, each shown on `/dev/components`:
1. `StatusBadge`, `ScorePill`, `TimestampChip`, `Money`, `CopyButton`, `CharCounter`, `EmptyState`, `ErrorState`, `ConfirmDialog` (with typed confirmation), `ConnectionIndicator`
2. `AppShell`, `Sidebar`, `OnboardingBanner`
3. `VideoPreviewCard`, `EligibilityBanner`, `ModelPicker` (a cmdk combobox with filters, a price column, a "This video ≈" column, an over-budget ⚠ and keyboard hints; a bottom sheet on mobile)
4. `PipelineStepper` / `PipelineNode` (with sub-items, attempt badge, the ⇄ revision-loop badge and the pulse), `UsageMeter`, `ActivityLog`
5. `MarkdownEditor` (CodeMirror 6, lazy-loaded), `MarkdownPreview` (dev.to style, with `rehype-sanitize`, `{% embed %}` → YouTube card, "▶ Watch" links → seek chips), `DraftDiff`, `VersionSelect`
6. `FaithfulnessGauge`, `ClaimList`, `TitlePicker`, `TagInput`, `ActionBar`, `KeyboardShortcutsDialog`
7. `KeyInputCard`

Hooks: `useJob`, `useJobs`, `useJobEvents` (EventSource with backoff and `Last-Event-ID`, patching the query cache, falling back to 5s polling), `useResumeAction` (Idempotency-Key + `expected_checkpoint_id` + button locking + refetch on 409), `useUnsavedChangesGuard`, `useYouTubePlayer`, `useIntegrations`.

### F3: pages, in lifecycle order (matching mockups 1a–1g, 2a–2b and 3a)
`/login` (3a) → `/dashboard` (1a) → `/jobs/new` (1b + 2a) → `/jobs/[id]` (1c) → `/jobs/[id]/review` (1d, plus a mobile tabs version) → `/jobs/[id]/publish` (1e) → `/jobs/[id]/result` (1f) → `/settings` Integrations (1g) / Defaults (2b) / Style profiles / Account → `/articles` → `/usage` → 404/403/error/offline states. Each page has skeleton, empty and error states, plus the error variants the mockups suggest: failed job, 402 budget and ineligible previews.

### F4: integration and tests
- Switch from MSW to the real API, page by page.
- Vitest + Testing Library for hooks and components (`useResumeAction`, `TagInput` validation, `useJobEvents` reconnect).
- Playwright end to end against mocks in CI, plus one smoke test against a staging deploy that drives both interrupts.
- Accessibility check (axe) in Playwright; Lighthouse budget on dashboard and review.

---

## 5. Google Cloud resources

Region: one region for everything (set `REGION`; Cloud SQL, Cloud Run, the GCS bucket and Cloud Tasks must match).

### APIs to enable
`run`, `sqladmin`, `storage`, `cloudkms`, `secretmanager`, `cloudtasks`, `cloudscheduler`,
`artifactregistry`, `cloudbuild`, `iam`, `iamcredentials`, `identitytoolkit` (Identity Platform / Firebase Auth),
`logging`, `monitoring`, `cloudtrace`, `clouderrorreporting`.

### Resources

| # | Service | Resource | Notes |
|---|---|---|---|
| 1 | Cloud SQL | Instance `tube2dev-pg` (Postgres 16, `db-custom-1-3840` to start, flag `cloudsql.iam_authentication=on`, automated backups + PITR, deletion protection) | Public IP is fine with the Auth Proxy and no authorized networks; switch to private IP + VPC later if needed |
| 2 | Cloud SQL | Databases `tube2dev_app`, `tube2dev_credentials` | Separate database for credentials; optionally a separate instance |
| 3 | Cloud SQL | IAM DB users for `sa-api`, `sa-worker`, `sa-migrate`, plus your own Google account for local dev | `GRANT` set by migrations: `sa-*` on app; only api/worker on credentials |
| 4 | Cloud Storage | Bucket `<project>-tube2dev-content` | Uniform access, public access prevention, lifecycle (delete `jobs/*` after 90d, abort incomplete uploads) |
| 5 | Cloud KMS | Key ring `tube2dev`, key `user-api-keys` (symmetric, 90-day rotation) | Encrypter/decrypter granted only to `sa-api`, `sa-worker` |
| 6 | Secret Manager | `yt-proxy-credentials`, `langsmith-api-key` | No user keys here; those live in the credentials DB |
| 7 | Cloud Tasks | Queue `graph-runs` (max concurrent 10, max attempts 5, backoff 10s→5m) | Target: worker `/internal/run-job` with OIDC |
| 8 | Cloud Run | Service `tube2dev-api` (+ cloud-sql-proxy sidecar), min instances 1 | Request timeout 3600s (SSE) |
| 9 | Cloud Run | Service `tube2dev-worker` (+ sidecar), ingress internal + Cloud Tasks only, `--no-allow-unauthenticated` | Timeout 3600s, CPU always allocated during requests, concurrency 4 |
| 10 | Cloud Run | Service `tube2dev-web` (Next.js standalone) | Public |
| 11 | Cloud Run | Jobs `tube2dev-migrate`, `tube2dev-cleanup` | Migrate runs in CI before deploy |
| 12 | Cloud Scheduler | `tube2dev-cleanup-daily` → runs the cleanup job | |
| 13 | Artifact Registry | Docker repo `tube2dev` | |
| 14 | Cloud Build | Trigger on `main` / `stage` (or GitHub Actions + Workload Identity Federation, no keys) | |
| 15 | Identity Platform / Firebase | Google provider + email link; authorized domains = web URL | Client config (public) goes to the web env |
| 16 | Monitoring | Alert policies: worker 5xx rate, task retries exhausted, Cloud SQL CPU/connections, job failure rate, daily spend | Uptime check on `/healthz` |

### Service accounts and roles

| SA | Roles |
|---|---|
| `sa-api` | `cloudsql.client`, `cloudsql.instanceUser`, `storage.objectAdmin` (bucket), `cloudkms.cryptoKeyEncrypterDecrypter` (key), `cloudtasks.enqueuer`, `iam.serviceAccountUser` on `sa-tasks-invoker`, `iam.serviceAccountTokenCreator` on itself (signed URLs), `secretmanager.secretAccessor`, `firebaseauth.viewer`, `cloudtrace.agent` |
| `sa-worker` | `cloudsql.client`, `cloudsql.instanceUser`, `storage.objectAdmin` (bucket), `cloudkms.cryptoKeyDecrypter` (key), `secretmanager.secretAccessor`, `cloudtrace.agent` |
| `sa-tasks-invoker` | `run.invoker` on `tube2dev-worker` |
| `sa-migrate` | `cloudsql.client`, `cloudsql.instanceUser` |
| `sa-web` | none beyond the defaults |
| `sa-cleanup` (or reuse worker) | worker roles + `storage.objectAdmin` |

### Local development (ADC)
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT
cloud-sql-proxy --auto-iam-authn --port 5432 $PROJECT:$REGION:tube2dev-pg
# APP_DB_URL=postgresql+psycopg://<you@gmail.com>@127.0.0.1:5432/tube2dev_app
```
Tests don't need GCP: Testcontainers Postgres, fake-gcs-server and a fake KMS.

---

## 6. Build order and milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo restructure, `infra/bootstrap.sh`, secrets rotated | `bootstrap.sh` creates everything in §5 on a fresh project |
| M1 | B1 + B2 | Migrations run through the proxy; keys can be saved and verified via the API; GCS round-trip works |
| M2 | B3 | The graph runs end to end locally through both interrupts with real keys; no text blobs in checkpoints |
| M3 | B4 + B5 | Worker via Cloud Tasks; SSE live; all endpoints in OpenAPI; integration tests green |
| M4 | F1 + F2 | Component gallery matches the mockups in light and dark |
| M5 | F3 | All pages working against MSW |
| M6 | F4 + B6 | Real API wired in; Playwright + evals green |
| M7 | Deploy | Cloud Build deploys to `stage`; alerts on; smoke e2e passes |

Open choices (the defaults are above, so say if you want something different): region; credentials DB as a separate *instance* instead of a separate database; Terraform instead of `bootstrap.sh`; custom domain + HTTPS load balancer.
