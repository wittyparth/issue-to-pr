#!/usr/bin/env bash
# Build and push the it2pr-worker image to ECR.
#
# Run this AFTER `cdk deploy` (which creates the ECR repository and prints
# the `WorkerRepositoryUri` stack output) and BEFORE labeling the first
# issue — the Fargate task pulls `<repo>:latest`, so nothing will run until
# an image has been pushed.
#
# Usage:
#   scripts/build-and-push-worker.sh <ecr-repository-uri> [aws-region]
#
# Or via env vars:
#   WORKER_ECR_REPOSITORY_URI=<...> AWS_REGION=us-east-1 scripts/build-and-push-worker.sh
#
# The repository URI is the `WorkerRepositoryUri` output from `cdk deploy`
# (or `cdk deploy --outputs-file outputs.json` / `aws cloudformation
# describe-stacks`), e.g.:
#   123456789012.dkr.ecr.us-east-1.amazonaws.com/it2pr-worker

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REPOSITORY_URI="${1:-${WORKER_ECR_REPOSITORY_URI:-}}"
REGION="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-}}}"

if [[ -z "${REPOSITORY_URI}" ]]; then
  echo "Usage: $0 <ecr-repository-uri> [aws-region]" >&2
  echo "  or:  WORKER_ECR_REPOSITORY_URI=<uri> AWS_REGION=<region> $0" >&2
  echo "" >&2
  echo "Get <ecr-repository-uri> from the 'WorkerRepositoryUri' output of 'cdk deploy'." >&2
  exit 1
fi

if [[ -z "${REGION}" ]]; then
  echo "Usage: $0 <ecr-repository-uri> [aws-region]" >&2
  echo "  or:  WORKER_ECR_REPOSITORY_URI=<uri> AWS_REGION=<region> $0" >&2
  echo "" >&2
  echo "No AWS region provided (arg 2, or AWS_REGION / AWS_DEFAULT_REGION)." >&2
  exit 1
fi

REGISTRY="${REPOSITORY_URI%%/*}"

echo "==> Logging in to ECR registry: ${REGISTRY} (region ${REGION})"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo "==> Building ${REPOSITORY_URI}:latest from ${REPO_ROOT}/worker (linux/amd64, matching the Fargate task's default X86_64 runtime platform regardless of host arch)"
docker buildx build --platform linux/amd64 -t "${REPOSITORY_URI}:latest" -f "${REPO_ROOT}/worker/Dockerfile" --push "${REPO_ROOT}/worker"

echo "==> Done. The Fargate worker task will pull ${REPOSITORY_URI}:latest on its next run."
