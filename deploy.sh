#!/usr/bin/env bash
# Deploy the Mobile Products Dashboard to ev-product-analytics.
#
# Reuses infra owned by tenant-health-dashboard/deploy.sh:
#   - Project, folder, billing, APIs
#   - VPC + subnet (not in the data path; serverless NEG)
#   - IAP OAuth brand
#   - WIF pool/provider (github-actions / github-oidc), org-pinned to GetEvinced
#   - Static IP, managed cert, target HTTPS proxy, forwarding rule, URL map
#
# Creates per-service:
#   - Artifact Registry repo
#   - Secret Manager secret (coralogix-api-key)
#   - Runtime SA, scheduler SA, deploy SA (with WIF binding for this repo)
#   - Cloud Run service (private; only IAP service agent + scheduler can invoke)
#   - Serverless NEG + backend service (IAP enabled, group-bound)
#   - URL map path rule /mobile/* → this backend (re-imports YAML)
#   - Cloud Scheduler job mobile-dashboard-refresh (daily)
#   - GitHub repo variables for the CI workflow
#
# Prerequisites:
#   - tenant-health-dashboard/deploy.sh has been run (LB + WIF pool exist)
#   - gcloud auth login && gcloud auth application-default login
#   - gh auth login (for repo variables)
#   - CORALOGIX_API_KEY in env on first run, or secret already seeded
#
# Idempotent: safe to re-run. Image tag = git short SHA.

set -euo pipefail

PROJECT="${PROJECT:-ev-product-analytics}"
REGION="${REGION:-us-central1}"

SERVICE="${SERVICE:-mobile-dashboard}"
REPO="${REPO:-mobile-dashboard}"
SECRET_NAME="${SECRET_NAME:-coralogix-api-key}"
GROUP="${GROUP:-product-analytics@evinced.com}"
SCHEDULE="${SCHEDULE:-0 8 * * *}"   # 08:00 UTC daily
GH_REPO="${GH_REPO:-GetEvinced/evinced-mobile-dashboard}"

NEG_NAME="${NEG_NAME:-neg-mobile-dashboard}"
BACKEND_NAME="${BACKEND_NAME:-be-mobile-dashboard}"
URLMAP_NAME="${URLMAP_NAME:-urlmap-tenant-health}"
TENANT_BACKEND="${TENANT_BACKEND:-be-tenant-health}"

RUN_SA_NAME="mobile-dashboard-run"
SCHED_SA_NAME="mobile-dashboard-scheduler"
DEPLOY_SA_NAME="mobile-dashboard-deploy"
WIF_POOL_ID="github-actions"
WIF_PROVIDER_ID="github-oidc"

RUN_SA_EMAIL="${RUN_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SCHED_SA_EMAIL="${SCHED_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA_EMAIL="${DEPLOY_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${GIT_SHA}"

say() { printf '\033[1;34m▶  %s\033[0m\n' "$*"; }

OPERATOR="$(gcloud config get-value account 2>/dev/null || true)"
if [[ -z "${OPERATOR}" ]]; then
  echo "Not authenticated. Run: gcloud auth login" >&2
  exit 1
fi

# ─── 0. Prerequisites: project + shared LB exist ───
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)' 2>/dev/null || true)"
if [[ -z "${PROJECT_NUMBER}" ]]; then
  echo "Project ${PROJECT} not found. Run tenant-health-dashboard/deploy.sh first." >&2
  exit 1
fi
if ! gcloud compute url-maps describe "${URLMAP_NAME}" --project="${PROJECT}" >/dev/null 2>&1; then
  echo "URL map ${URLMAP_NAME} not found. Run tenant-health-dashboard/deploy.sh first." >&2
  exit 1
fi
if ! gcloud compute backend-services describe "${TENANT_BACKEND}" \
    --project="${PROJECT}" --global >/dev/null 2>&1; then
  echo "Backend ${TENANT_BACKEND} not found. Run tenant-health-dashboard/deploy.sh first." >&2
  exit 1
fi
if ! gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
    --project="${PROJECT}" --location=global \
    --workload-identity-pool="${WIF_POOL_ID}" >/dev/null 2>&1; then
  echo "WIF provider ${WIF_PROVIDER_ID} not found. Run tenant-health-dashboard/deploy.sh first." >&2
  exit 1
fi

# ─── 1. Artifact Registry ───
say "Ensuring Artifact Registry repo ${REPO}"
if ! gcloud artifacts repositories describe "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" \
    --repository-format=docker \
    --description="Mobile products dashboard container images"
fi

# ─── 2. Secret (coralogix-api-key) ───
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
    say "Seeded ${SECRET_NAME} from CORALOGIX_API_KEY env var"
  else
    echo
    echo "!! Secret ${SECRET_NAME} has no versions yet."
    echo "   Re-run with CORALOGIX_API_KEY=... ./deploy.sh, or run:"
    echo "     printf 'YOUR_KEY' | gcloud secrets versions add ${SECRET_NAME} --project=${PROJECT} --data-file=-"
    echo
  fi
fi

# ─── 3. Service accounts ───
say "Ensuring service accounts"
for pair in "${RUN_SA_NAME}:Mobile Dashboard Cloud Run runtime" \
            "${SCHED_SA_NAME}:Mobile Dashboard Scheduler" \
            "${DEPLOY_SA_NAME}:Mobile Dashboard GitHub CI deployer"; do
  name="${pair%%:*}"; display="${pair#*:}"
  email="${name}@${PROJECT}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${email}" --project="${PROJECT}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${name}" \
      --project="${PROJECT}" --display-name="${display}"
  fi
done

# Runtime SA: read the secret. Retry — newly-created SAs take a few seconds
# to become visible to secretmanager.setIamPolicy.
for attempt in 1 2 3 4 5 6; do
  if gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
       --project="${PROJECT}" \
       --member="serviceAccount:${RUN_SA_EMAIL}" \
       --role=roles/secretmanager.secretAccessor \
       --condition=None >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" -eq 6 ]]; then
    echo "Secret IAM binding never succeeded after 6 attempts" >&2
    exit 1
  fi
  echo "  Secret IAM binding attempt ${attempt} failed (SA not yet visible); retrying in 5s"
  sleep 5
done

# Deploy SA project roles + actAs runtime
say "Granting deploy SA project roles"
for role in roles/run.admin roles/artifactregistry.writer roles/cloudbuild.builds.editor roles/storage.admin roles/iam.serviceAccountUser roles/viewer; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${DEPLOY_SA_EMAIL}" --role="${role}" --condition=None >/dev/null
done
gcloud iam service-accounts add-iam-policy-binding "${RUN_SA_EMAIL}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role=roles/iam.serviceAccountUser >/dev/null

# ─── 4. WIF binding for this repo ───
WIF_POOL_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}"
WIF_PROVIDER_FULL="${WIF_POOL_NAME}/providers/${WIF_PROVIDER_ID}"
say "Binding WIF principal for ${GH_REPO} → ${DEPLOY_SA_EMAIL}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_SA_EMAIL}" \
  --project="${PROJECT}" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_NAME}/attribute.repository/${GH_REPO}" >/dev/null

# ─── 5. Build + push image (skipped if a Cloud Run revision already exists) ───
if gcloud run services describe "${SERVICE}" \
    --project="${PROJECT}" --region="${REGION}" >/dev/null 2>&1; then
  say "Cloud Run service ${SERVICE} already exists — skipping bootstrap build (CI handles updates)"
  IMAGE="$(gcloud run services describe "${SERVICE}" \
    --project="${PROJECT}" --region="${REGION}" \
    --format='value(spec.template.spec.containers[0].image)')"
else
  say "Building bootstrap image ${IMAGE}"
  gcloud builds submit --project="${PROJECT}" --tag="${IMAGE}" .
fi

# ─── 6. Deploy Cloud Run ───
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

# Cloud Run invokers: scheduler SA (refresh) + IAP service agent (LB → Cloud Run).
say "Granting run.invoker to scheduler SA + IAP service agent"
for member in \
    "serviceAccount:${SCHED_SA_EMAIL}" \
    "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"; do
  gcloud run services add-iam-policy-binding "${SERVICE}" \
    --project="${PROJECT}" --region="${REGION}" \
    --member="${member}" --role=roles/run.invoker >/dev/null
done

# ─── 7. NEG + backend service (IAP enabled) ───
say "Ensuring serverless NEG ${NEG_NAME}"
if ! gcloud compute network-endpoint-groups describe "${NEG_NAME}" \
    --project="${PROJECT}" --region="${REGION}" >/dev/null 2>&1; then
  gcloud compute network-endpoint-groups create "${NEG_NAME}" \
    --project="${PROJECT}" --region="${REGION}" \
    --network-endpoint-type=serverless --cloud-run-service="${SERVICE}"
fi

say "Ensuring backend service ${BACKEND_NAME} (with IAP)"
if ! gcloud compute backend-services describe "${BACKEND_NAME}" \
    --project="${PROJECT}" --global >/dev/null 2>&1; then
  gcloud compute backend-services create "${BACKEND_NAME}" \
    --project="${PROJECT}" --global \
    --load-balancing-scheme=EXTERNAL_MANAGED
  gcloud compute backend-services add-backend "${BACKEND_NAME}" \
    --project="${PROJECT}" --global \
    --network-endpoint-group="${NEG_NAME}" \
    --network-endpoint-group-region="${REGION}"
fi
gcloud compute backend-services update "${BACKEND_NAME}" \
  --project="${PROJECT}" --global --iap=enabled >/dev/null

say "Granting IAP access to group:${GROUP} on ${BACKEND_NAME}"
gcloud iap web add-iam-policy-binding \
  --project="${PROJECT}" \
  --resource-type=backend-services \
  --service="${BACKEND_NAME}" \
  --member="group:${GROUP}" \
  --role=roles/iap.httpsResourceAccessor >/dev/null

# ─── 8. URL map: re-import full path matcher ───
# Full set of rules — converges with tenant-health-dashboard/deploy.sh.
say "Re-importing ${URLMAP_NAME} with /mobile, /tenant, default→/__home rules"
TMP_URLMAP="$(mktemp)"
trap 'rm -f "${TMP_URLMAP}"' EXIT
BE_TENANT_URL="https://www.googleapis.com/compute/v1/projects/${PROJECT}/global/backendServices/${TENANT_BACKEND}"
BE_MOBILE_URL="https://www.googleapis.com/compute/v1/projects/${PROJECT}/global/backendServices/${BACKEND_NAME}"
URLMAP_FP="$(gcloud compute url-maps describe "${URLMAP_NAME}" \
  --project="${PROJECT}" --format='value(fingerprint)')"
cat >"${TMP_URLMAP}" <<EOF
name: ${URLMAP_NAME}
fingerprint: ${URLMAP_FP}
defaultService: ${BE_TENANT_URL}
hostRules:
  - hosts:
      - '*'
    pathMatcher: main
pathMatchers:
  - name: main
    defaultService: ${BE_TENANT_URL}
    pathRules:
      - paths:
          - /mobile
          - /mobile/*
        service: ${BE_MOBILE_URL}
        routeAction:
          urlRewrite:
            pathPrefixRewrite: /
      - paths:
          - /tenant
          - /tenant/*
        service: ${BE_TENANT_URL}
        routeAction:
          urlRewrite:
            pathPrefixRewrite: /dashboard
EOF
gcloud compute url-maps import "${URLMAP_NAME}" \
  --project="${PROJECT}" --source="${TMP_URLMAP}" --quiet

# ─── 9. Cloud Scheduler ───
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

# ─── 10. GitHub repo variables ───
say "Publishing GitHub repo variables on ${GH_REPO}"
if command -v gh >/dev/null 2>&1; then
  gh variable set WIF_PROVIDER --repo "${GH_REPO}" --body "${WIF_PROVIDER_FULL}" >/dev/null
  gh variable set DEPLOY_SERVICE_ACCOUNT --repo "${GH_REPO}" --body "${DEPLOY_SA_EMAIL}" >/dev/null
  gh variable set GCP_PROJECT --repo "${GH_REPO}" --body "${PROJECT}" >/dev/null
  gh variable set GCP_REGION --repo "${GH_REPO}" --body "${REGION}" >/dev/null
  gh variable set ARTIFACT_REPO --repo "${GH_REPO}" --body "${REPO}" >/dev/null
  gh variable set CLOUD_RUN_SERVICE --repo "${GH_REPO}" --body "${SERVICE}" >/dev/null
  gh variable set RUN_SERVICE_ACCOUNT --repo "${GH_REPO}" --body "${RUN_SA_EMAIL}" >/dev/null
else
  echo "  gh not installed — set these vars manually on ${GH_REPO}:"
  echo "    WIF_PROVIDER=${WIF_PROVIDER_FULL}"
  echo "    DEPLOY_SERVICE_ACCOUNT=${DEPLOY_SA_EMAIL}"
  echo "    GCP_PROJECT=${PROJECT}"
  echo "    GCP_REGION=${REGION}"
  echo "    ARTIFACT_REPO=${REPO}"
  echo "    CLOUD_RUN_SERVICE=${SERVICE}"
  echo "    RUN_SERVICE_ACCOUNT=${RUN_SA_EMAIL}"
fi

cat <<EOF

─────────────────────────────────────────────────────────────
✓  Cloud Run:  ${SERVICE_URL}
✓  Public URL: https://product-analytics.evinced.engineering/mobile/
─────────────────────────────────────────────────────────────

Members of group:${GROUP} can access via IAP.
Cloud Scheduler ${JOB} runs at '${SCHEDULE}' UTC.

Trigger refresh manually (bypasses IAP via Cloud Run IAM):
  curl -X POST "${SERVICE_URL}/refresh" \\
    -H "Authorization: Bearer \$(gcloud auth print-identity-token)"

EOF
