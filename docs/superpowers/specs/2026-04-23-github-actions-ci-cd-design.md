# GitHub Actions CI/CD — Design

**Date:** 2026-04-23
**Status:** Approved
**Scope:** Add CI and CD workflows to `evinced-mobile-dashboard`. CD deploys to
Cloud Run in `sbx-product-analytics` by invoking the existing `deploy.sh`.

## Goals

1. **CI** catches regressions on every PR and push to `main` — Python bug-class
   lint errors, Dockerfile / dependency breakage, startup failure.
2. **CD** deploys to Cloud Run on merge to `main`, on GitHub release, or on
   manual dispatch, re-running the full idempotent bootstrap each time so the
   workflow is the single source of truth (no drift between `deploy.sh` and
   what CD does).

## Non-goals (deliberate)

- **No test suite.** The repo has no tests today. Not adding stubs.
- **No image vulnerability scan.** `stark-data-core` has Trivy; we can add
  later. Out of scope for this spec so we ship something useful now.
- **No Terraform / IaC migration.** `deploy.sh` stays authoritative.
- **No WIF setup.** We're using a service-account JSON key — see tradeoff
  below.

## CI — `.github/workflows/ci.yml`

**Triggers:** `pull_request` to `main`, `push` to `main`.

**Two jobs, both `ubuntu-latest`:**

### `lint`
- `actions/checkout@v4`
- `actions/setup-python@v5` with Python 3.12
- `pip install ruff`
- `ruff check --select E9,F63,F7,F82 .`

**Why this ruleset, not defaults:** Default ruff flags a lot of style issues
on code that was never linted (E401 multi-import lines, E701 compound
statements, E722 bare except). The narrow `E9,F63,F7,F82` set catches *bugs*
only — syntax errors, invalid f-strings, import issues, undefined names — so
CI is meaningful on day one without forcing a broad style refactor. Verified
locally on the current tree: passes clean. Broaden the ruleset later if the
team adopts a style pass.

### `smoke`
Proves the container still starts and the FastAPI `/healthz` endpoint
responds.

- `actions/checkout@v4`
- `docker build -t mobile-dashboard:ci .`
- `docker run -d --name smoke -p 8080:8080 mobile-dashboard:ci`
- Poll `curl -sf http://localhost:8080/healthz` up to 30× at 2s intervals
- On failure: dump `docker logs smoke` before exiting
- Always: `docker rm -f smoke` in a cleanup step

**Why not a full refresh smoke?** `/refresh` needs a live `CORALOGIX_API_KEY`
and hits external APIs. `/healthz` proves the image boots and FastAPI
initialises — the cheap win. Anything deeper needs live credentials we don't
want in CI.

## CD — `.github/workflows/cd.yml`

**Triggers (all three):**
- `push` to `main`
- `release: published`
- `workflow_dispatch` (manual button)

**Concurrency:** `group: cd`, `cancel-in-progress: false` — a release-tag push
and the merge commit that created it arrive nearly simultaneously; we queue
the second run rather than cancel it (deploys are idempotent, but we don't
want two `gcloud run deploy` commands racing on the same revision).

**Steps:**
1. `actions/checkout@v4`
2. `google-github-actions/auth@v2` with
   `credentials_json: ${{ secrets.GCP_SA_KEY }}`
3. `google-github-actions/setup-gcloud@v2`
4. `bash deploy.sh`

That's the whole job. `deploy.sh` already handles: enable APIs, create
Artifact Registry repo, create/verify Secret Manager secret, create runtime +
scheduler SAs, grant `secretAccessor` to the runtime SA, Cloud Build image
(tagged with git short SHA), Cloud Run deploy with secret binding, grant
`run.invoker` to the `product-analytics@evinced.com` group and the scheduler
SA, upsert the daily Cloud Scheduler job.

## Prerequisites (one-time, done by operator before first CD run)

### 1. GitHub secret `GCP_SA_KEY`
JSON key for a deploy service account in `sbx-product-analytics`. Stored at
repo scope under Settings → Secrets and variables → Actions.

### 2. Pre-granted roles on the deploy SA

`deploy.sh` has a "self-grant" loop at the top that adds three roles via
`--member=user:${OPERATOR}`. Under a service-account identity this silently
no-ops (the `|| true` suppresses the "invalid member type" error), so every
role must be pre-granted. On `sbx-product-analytics`:

| Role | Needed for |
| --- | --- |
| `roles/artifactregistry.admin` | Create AR repo, push images |
| `roles/cloudbuild.builds.editor` | Submit Cloud Build |
| `roles/run.admin` | Deploy Cloud Run, set IAM on the service |
| `roles/iam.serviceAccountAdmin` | Create runtime + scheduler SAs |
| `roles/iam.serviceAccountUser` | `actAs` the runtime SA on deploy |
| `roles/secretmanager.admin` | Create/read secret, set IAM |
| `roles/cloudscheduler.admin` | Upsert the daily scheduler job |
| `roles/serviceusage.serviceUsageAdmin` | Enable APIs |

Cloud Build also needs the default Cloud Build SA
(`{project_number}@cloudbuild.gserviceaccount.com`) to have
`roles/storage.objectUser` on the `_cloudbuild` GCS bucket — this is
auto-created the first time `gcloud builds submit` runs, so no action
required unless the initial bootstrap failed.

### 3. `CORALOGIX_API_KEY`

Not passed through GHA. The Secret Manager secret `coralogix-api-key` is
already seeded (the operator already ran `deploy.sh` locally at least once).
`deploy.sh` skips the seed step when a version exists, so CD leaves it
untouched.

## Tradeoff — SA key vs. WIF

We're using a long-lived SA JSON key stored as a GitHub secret. This was an
explicit choice over Workload Identity Federation (Q3 → C). Implications:

- **Key rotation is manual.** If the key is exposed, rotation = create a new
  key version, update the GH secret, delete the old version.
- **Broad blast radius.** The key grants admin-level roles across eight
  distinct services in `sbx-product-analytics`. Compromise would allow an
  attacker to deploy arbitrary code and exfiltrate the Coralogix secret.
- **Mitigation:** Scope the deploy SA to `sbx-product-analytics` only (no
  cross-project bindings). Treat `GCP_SA_KEY` as production-sensitive in
  GitHub repo settings. Consider migrating to WIF if this repo graduates
  out of the sandbox.

## Files to create

- `.github/workflows/ci.yml`
- `.github/workflows/cd.yml`
- This spec doc.

No changes to `deploy.sh`, `app.py`, `Dockerfile`, or any Python file.

## Out-of-scope follow-ups (worth noting)

- Add Trivy image scan to CD, gated on CRITICAL/HIGH CVEs (matches
  stark-data-core pattern).
- Migrate to WIF — removes the long-lived key. Requires a WIF pool +
  provider in `sbx-product-analytics` and re-binding the deploy SA.
- Broaden ruff ruleset after a one-time style pass on existing files.
- Decouple `deploy.sh` bootstrap (one-time) from build-and-deploy
  (every-change), so CD doesn't run idempotent-but-slow IAM / API-enable
  calls on every push.
