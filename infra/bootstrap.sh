#!/usr/bin/env bash
# Creates every GCP resource Tube2Dev needs (docs/implementation-plan.md §5). Safe to re-run: each
# create is skipped if the resource already exists. Review before running; it creates billable resources
# (Cloud SQL is the main cost).
#
#   PROJECT=my-project ./infra/bootstrap.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-us-east1}"
INSTANCE="${INSTANCE:-tube2dev-pg}"
BUCKET="${BUCKET:-${PROJECT}-tube2dev-content}"
QUEUE="${QUEUE:-graph-runs}"
REPO="${REPO:-tube2dev}"
ME="$(gcloud config get-value account 2>/dev/null)"

gc() { gcloud --project "$PROJECT" "$@"; }
exists() { "$@" >/dev/null 2>&1; }
step() { printf '\n==> %s\n' "$*"; }

step "Enable APIs"
gc services enable run.googleapis.com sqladmin.googleapis.com storage.googleapis.com cloudkms.googleapis.com \
  secretmanager.googleapis.com cloudtasks.googleapis.com cloudscheduler.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com iam.googleapis.com iamcredentials.googleapis.com identitytoolkit.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com cloudtrace.googleapis.com clouderrorreporting.googleapis.com

step "Service accounts"
for sa in sa-api sa-worker sa-tasks-invoker sa-migrate sa-web sa-build; do
  exists gc iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" ||
    gc iam service-accounts create "$sa" --display-name "Tube2Dev $sa"
done
SA() { echo "$1@$PROJECT.iam.gserviceaccount.com"; }

step "Cloud SQL (Postgres 16, IAM auth, backups + PITR)"
exists gc sql instances describe "$INSTANCE" || gc sql instances create "$INSTANCE" \
  --database-version=POSTGRES_16 --region="$REGION" --edition=ENTERPRISE --tier=db-custom-1-3840 \
  --storage-auto-increase --backup-start-time=03:00 --enable-point-in-time-recovery \
  --database-flags=cloudsql.iam_authentication=on --deletion-protection
for db in tube2dev_app tube2dev_credentials; do
  exists gc sql databases describe "$db" --instance="$INSTANCE" || gc sql databases create "$db" --instance="$INSTANCE"
done
for sa in sa-api sa-worker sa-migrate; do
  exists gc sql users describe "$sa@$PROJECT.iam" --instance="$INSTANCE" ||
    gc sql users create "$sa@$PROJECT.iam" --instance="$INSTANCE" --type=cloud_iam_service_account
done
[ -n "$ME" ] && { exists gc sql users describe "$ME" --instance="$INSTANCE" ||
  gc sql users create "$ME" --instance="$INSTANCE" --type=cloud_iam_user; }
if ! exists gc secrets describe postgres-password; then
  PW="$(openssl rand -base64 30)"
  gc sql users set-password postgres --instance="$INSTANCE" --password="$PW"
  printf '%s' "$PW" | gc secrets create postgres-password --data-file=- --replication-policy=automatic
fi

step "GCS bucket (private, lifecycle)"
exists gcloud storage buckets describe "gs://$BUCKET" || gcloud storage buckets create "gs://$BUCKET" \
  --project "$PROJECT" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
cat > /tmp/t2d-lifecycle.json <<'JSON'
{"rule": [
  {"action": {"type": "Delete"}, "condition": {"age": 90, "matchesPrefix": ["users/"]}},
  {"action": {"type": "Delete"}, "condition": {"age": 30, "matchesPrefix": ["cache/"]}},
  {"action": {"type": "AbortIncompleteMultipartUpload"}, "condition": {"age": 1}}
]}
JSON
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=/tmp/t2d-lifecycle.json

step "KMS key for per-user API keys (90-day rotation)"
exists gc kms keyrings describe tube2dev --location="$REGION" || gc kms keyrings create tube2dev --location="$REGION"
exists gc kms keys describe user-api-keys --keyring=tube2dev --location="$REGION" || gc kms keys create user-api-keys \
  --keyring=tube2dev --location="$REGION" --purpose=encryption --rotation-period=90d \
  --next-rotation-time="$(date -u -d '+90 days' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+90d +%Y-%m-%dT%H:%M:%SZ)"
KEY="projects/$PROJECT/locations/$REGION/keyRings/tube2dev/cryptoKeys/user-api-keys"

step "Secrets (fill values later with: gcloud secrets versions add <name> --data-file=-)"
for s in yt-proxy-credentials langsmith-api-key; do
  exists gc secrets describe "$s" || gc secrets create "$s" --replication-policy=automatic
done

step "Cloud Tasks queue"
exists gc tasks queues describe "$QUEUE" --location="$REGION" || gc tasks queues create "$QUEUE" --location="$REGION" \
  --max-concurrent-dispatches=10 --max-attempts=5 --min-backoff=10s --max-backoff=300s

step "Artifact Registry"
exists gc artifacts repositories describe "$REPO" --location="$REGION" ||
  gc artifacts repositories create "$REPO" --location="$REGION" --repository-format=docker

step "IAM bindings (least privilege)"
proj_role() { gc projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$(SA "$1")" --role="$2" --condition=None >/dev/null; }
for sa in sa-api sa-worker sa-migrate; do
  proj_role "$sa" roles/cloudsql.client
  proj_role "$sa" roles/cloudsql.instanceUser
done
for sa in sa-api sa-worker; do
  proj_role "$sa" roles/cloudtrace.agent
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$(SA "$sa")" --role=roles/storage.objectAdmin >/dev/null
  for s in yt-proxy-credentials langsmith-api-key; do
    gc secrets add-iam-policy-binding "$s" --member="serviceAccount:$(SA "$sa")" --role=roles/secretmanager.secretAccessor >/dev/null
  done
done
gc kms keys add-iam-policy-binding user-api-keys --keyring=tube2dev --location="$REGION" \
  --member="serviceAccount:$(SA sa-api)" --role=roles/cloudkms.cryptoKeyEncrypterDecrypter >/dev/null
gc kms keys add-iam-policy-binding user-api-keys --keyring=tube2dev --location="$REGION" \
  --member="serviceAccount:$(SA sa-worker)" --role=roles/cloudkms.cryptoKeyDecrypter >/dev/null
proj_role sa-api roles/cloudtasks.enqueuer
proj_role sa-api roles/firebaseauth.viewer
gc iam service-accounts add-iam-policy-binding "$(SA sa-tasks-invoker)" \
  --member="serviceAccount:$(SA sa-api)" --role=roles/iam.serviceAccountUser >/dev/null
# Cloud Build runs as sa-build: build/push images, deploy Cloud Run services + jobs, act as the runtime SAs
for r in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  proj_role sa-build "$r"
done
for sa in sa-api sa-worker sa-migrate sa-web; do
  gc iam service-accounts add-iam-policy-binding "$(SA "$sa")" \
    --member="serviceAccount:$(SA sa-build)" --role=roles/iam.serviceAccountUser >/dev/null
done
# Cloud Scheduler (cleanup) runs the cleanup job as sa-worker
proj_role sa-worker roles/run.invoker

# Your own account, for local development through ADC
if [ -n "$ME" ]; then
  for r in roles/cloudsql.client roles/cloudsql.instanceUser; do
    gc projects add-iam-policy-binding "$PROJECT" --member="user:$ME" --role="$r" --condition=None >/dev/null
  done
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="user:$ME" --role=roles/storage.objectAdmin >/dev/null
  gc kms keys add-iam-policy-binding user-api-keys --keyring=tube2dev --location="$REGION" \
    --member="user:$ME" --role=roles/cloudkms.cryptoKeyEncrypterDecrypter >/dev/null
fi

cat <<EOF

Done. Next steps:
 1. Run the cloud-sql-proxy locally, then hand both databases to the migrate user (one time):
      cloud-sql-proxy --port 5432 $PROJECT:$REGION:$INSTANCE &
      POSTGRES_PASSWORD="\$(gcloud secrets versions access latest --secret=postgres-password --project $PROJECT)" \\
        uv run --directory backend python -m app.cli bootstrap-db --migrate-user "sa-migrate@$PROJECT.iam"
 2. Enable Firebase Authentication (Google + Email link) in the Firebase console for $PROJECT,
    add your web domain to Authorized domains, and copy the web config into .env / Cloud Build substitutions.
 3. Deploy with Cloud Build (also runs migrations and grants your account DB access for local dev):
      gcloud builds submit --config infra/cloudbuild.yaml --project $PROJECT \
        --substitutions=_DEV_USERS=$ME,_FIREBASE_API_KEY=<web api key>,_FIREBASE_APP_ID=<web app id>
 4. After the worker is deployed, allow Cloud Tasks to call it:
      gcloud run services add-iam-policy-binding tube2dev-worker --region $REGION --project $PROJECT \\
        --member serviceAccount:$(SA sa-tasks-invoker) --role roles/run.invoker
 5. Schedule the daily cleanup job:
      gcloud scheduler jobs create http tube2dev-cleanup-daily --location $REGION --project $PROJECT \
        --schedule "15 4 * * *" --http-method POST \
        --uri "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/tube2dev-cleanup:run" \
        --oauth-service-account-email $(SA sa-worker)

Values for backend env:
  GCS_BUCKET=$BUCKET
  KMS_KEY_NAME=$KEY
  TASKS_INVOKER_SA=$(SA sa-tasks-invoker)
  DB_APP_GRANTEES=sa-api@$PROJECT.iam,sa-worker@$PROJECT.iam
  DB_CREDS_GRANTEES=sa-api@$PROJECT.iam,sa-worker@$PROJECT.iam
EOF
