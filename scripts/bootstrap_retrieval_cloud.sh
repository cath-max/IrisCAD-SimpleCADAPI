#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="iriscad-production"
REGION="us-east4"
SERVICE="iriscad-retrieval"
RUNTIME_SERVICE_ACCOUNT="iriscad-runtime@iriscad-production.iam.gserviceaccount.com"
EMBEDDING_SECRET="iriscad-embedding-api-key"

gcloud config set project "${PROJECT_ID}"

if ! gcloud secrets describe "${EMBEDDING_SECRET}" >/dev/null 2>&1; then
  gcloud secrets create "${EMBEDDING_SECRET}" --replication-policy=automatic
fi

LATEST_ENABLED_VERSION="$(gcloud secrets versions list "${EMBEDDING_SECRET}" \
  --filter='state=ENABLED' \
  --limit=1 \
  --sort-by='~createTime' \
  --format='value(name)')"
if [[ -z "${LATEST_ENABLED_VERSION}" ]]; then
  printf 'Paste EMBEDDING_API_KEY (input is hidden): '
  IFS= read -r -s EMBEDDING_API_KEY_VALUE
  printf '\n'
  if [[ -z "${EMBEDDING_API_KEY_VALUE}" ]]; then
    echo 'EMBEDDING_API_KEY cannot be empty.' >&2
    exit 1
  fi
  printf '%s' "${EMBEDDING_API_KEY_VALUE}" | \
    gcloud secrets versions add "${EMBEDDING_SECRET}" --data-file=-
  unset EMBEDDING_API_KEY_VALUE
else
  echo "Reusing enabled ${EMBEDDING_SECRET} secret version ${LATEST_ENABLED_VERSION}."
fi

gcloud secrets add-iam-policy-binding "${EMBEDDING_SECRET}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role=roles/secretmanager.secretAccessor

gcloud builds submit \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --config=cloudbuild.retrieval.yaml \
  .

gcloud run services add-iam-policy-binding "${SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role=roles/run.invoker

RETRIEVAL_URL="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.url)')"

echo
echo "Retrieval service URL: ${RETRIEVAL_URL}"
echo "Set the iriscad-web Cloud Build substitution to:"
echo "  _API_RETRIEVAL_URL=${RETRIEVAL_URL}"
