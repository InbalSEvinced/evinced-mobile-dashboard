#!/usr/bin/env bash
# Deploy the Mobile Products Dashboard to Cloud Run (Stage A).
#
# Creates: Artifact Registry repo, Secret Manager secret, two SAs, Cloud Run
# service (private, group-invokable), Cloud Scheduler job hitting /refresh daily.
#
# Prerequisites (one-time, per operator):
#   - Authenticated: gcloud auth login && gcloud auth application-default login
#   - Operator is a member of group:product-analytics@evinced.com (has admin roles
#     on sbx-product-analytics via the sandbox-team module)
#   - The CORALOGIX_API_KEY value you want to store (passed via env or prompted)
#
# Idempotent: safe to re-run. Image tag = git short SHA.

set -euo pipefail

PROJECT="${PROJECT:-sbx-product-analytics}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-mobile-dashboard}"
REPO="${REPO:-mobile-dashboard}"
SECRET_NAME="${SECRET_NAME:-coralogix-api-key}"
GROUP="${GROUP:-product-analytics@evinced.com}"
SCHEDULE="${SCHEDULE:-0 8 * * *}"   # 08:00 UTC daily
RUN_SA_NAME="mobile-dashboard-run"
SCHED_SA_NAME="mobile-dashboard-scheduler"

RUN_SA_EMAIL="${RUN_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SCHED_SA_EMAIL="${SCHED_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${GIT_SHA}"

say() { printf '\033[1;34m▶  %s\033[0m\n' "$*"; }

OPERATOR="$(gcloud config get-value account 2>/dev/null)"
if [[ -z "${OPERATOR}" ]]; then
  echo "Not authenticated. Run: gcloud auth login" >&2
  exit 1
fi

# ─── 1. Self-grant missing roles (operator has projectIamAdmin from sandbox module) ───
say "Granting operator ${OPERATOR} roles needed for the deploy"
for role in roles/serviceusage.serviceUsageAdmin roles/cloudbuild.builds.editor roles/cloudscheduler.admin; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="user:${OPERATOR}" --role="${role}" --condition=None >/dev/null 2>&1 || true
done

# ─── 2. Enable APIs not enabled by the sandbox-team module ───
say "Enabling APIs"
gcloud services enable \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  --project="${PROJECT}"

# ─── 3. Artifact Registry repo ───
say "Ensuring Artifact Registry repo ${REPO}"
if ! gcloud artifacts repositories describe "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" \
    --repository-format=docker \
    --description="Mobile products dashboard container images"
fi

# ─── 4. Secret (coralogix-api-key) ───
say "Ensuring secret ${SECRET_NAME}"
if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT}" >/dev/null 2>&1; then
  gcloud secrets create "${SECRET_NAME}" \
    --project="${PROJECT}" --replication-policy=automatic
fi

HAS_VERSION="$(gcloud secrets versions list "${SECRET_NAME}" --project="${PROJECT}" \
  --filter="state=ENABLED" --format='value(name)' 2>/dev/null | head -n1 || true)"
if [[ -z "${HAS_VERSION}" ]]; then
  if [[ -n "${CORALOGIX_API_KEY:-}" ]]; then
    printf '%s' "${CORALOGIX_API_KEY}" | gcloud secrets versions add "${SECRET_NAME}" \
      --project="${PROJECT}" --data-file=-
    say "Seeded secret ${SECRET_NAME} from CORALOGIX_API_KEY env var"
  else
    echo
    echo "!! Secret ${SECRET_NAME} has no versions yet."
    echo "   Either re-run with CORALOGIX_API_KEY=... ./deploy.sh, or run:"
    echo "     printf 'YOUR_KEY' | gcloud secrets versions add ${SECRET_NAME} --project=${PROJECT} --data-file=-"
    echo
  fi
fi

# ─── 5. Service accounts ───
say "Ensuring service accounts"
for pair in "${RUN_SA_NAME}:Mobile Dashboard Cloud Run runtime" \
            "${SCHED_SA_NAME}:Mobile Dashboard Scheduler"; do
  name="${pair%%:*}"; display="${pair#*:}"
  email="${name}@${PROJECT}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${email}" --project="${PROJECT}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${name}" \
      --project="${PROJECT}" --display-name="${display}"
  fi
done

# Runtime SA: read the secret
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${RUN_SA_EMAIL}" \
  --role=roles/secretmanager.secretAccessor \
  --condition=None >/dev/null

# ─── 6. Build + push image via Cloud Build ───
say "Building image ${IMAGE}"
gcloud builds submit --project="${PROJECT}" --tag="${IMAGE}" .

# ─── 7. Deploy Cloud Run ───
say "Deploying Cloud Run service ${SERVICE}"
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${RUN_SA_EMAIL}" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=1 \
  --max-instances=1 \
  --cpu=1 \
  --memory=2Gi \
  --timeout=600 \
  --set-env-vars=OUTPUT_DIR=/tmp/dashboard-output \
  --set-secrets=CORALOGIX_API_KEY="${SECRET_NAME}:latest"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" \
  --format='value(status.url)')"

# ─── 8. Grant invoker to the group and the scheduler SA ───
say "Granting run.invoker to group:${GROUP} and ${SCHED_SA_EMAIL}"
for member in "group:${GROUP}" "serviceAccount:${SCHED_SA_EMAIL}"; do
  gcloud run services add-iam-policy-binding "${SERVICE}" \
    --project="${PROJECT}" --region="${REGION}" \
    --member="${member}" --role=roles/run.invoker >/dev/null
done

# ─── 9. Cloud Scheduler (daily refresh) ───
say "Upserting Cloud Scheduler job ${SERVICE}-refresh"
JOB="${SERVICE}-refresh"
if gcloud scheduler jobs describe "${JOB}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${JOB}" \
    --project="${PROJECT}" --location="${REGION}" \
    --schedule="${SCHEDULE}" --time-zone=UTC \
    --uri="${SERVICE_URL}/refresh" --http-method=POST \
    --oidc-service-account-email="${SCHED_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --attempt-deadline=900s
else
  gcloud scheduler jobs create http "${JOB}" \
    --project="${PROJECT}" --location="${REGION}" \
    --schedule="${SCHEDULE}" --time-zone=UTC \
    --uri="${SERVICE_URL}/refresh" --http-method=POST \
    --oidc-service-account-email="${SCHED_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --attempt-deadline=900s
fi

cat <<EOF

─────────────────────────────────────────────────────────────
✓  Deployed: ${SERVICE_URL}
─────────────────────────────────────────────────────────────

Trigger a first refresh (required — HTML is not yet populated):
  curl -X POST "${SERVICE_URL}/refresh" \\
    -H "Authorization: Bearer \$(gcloud auth print-identity-token)"

View the dashboard via local proxy (browser):
  gcloud run services proxy ${SERVICE} --project=${PROJECT} --region=${REGION}
  # then open http://localhost:8080

Scheduler: ${JOB} runs at '${SCHEDULE}' UTC.

EOF
