# Issue-to-PR — Autonomous GitHub Coding Agent

Label a GitHub issue `@agent fix this` → an ephemeral AWS worker clones the repo,
infers the build environment, runs a provider-agnostic agentic fix loop under hard
cost/turn/time caps, verifies the full test suite passes in-sandbox with a coverage
gate, and opens a review-ready PR with rationale, cost, turns, and a trace link.

Self-hosted, invite-only multi-tenant, scale-to-zero on AWS. See
[`.omc/specs/deep-interview-issue-to-pr.md`](.omc/specs/deep-interview-issue-to-pr.md)
for the spec and [`.omc/plans/issue-to-pr-consensus-plan.md`](.omc/plans/issue-to-pr-consensus-plan.md)
for the consensus-approved implementation plan.

## Layout

| Package | Language | Role |
|---------|----------|------|
| `app/`    | TypeScript | GitHub App, webhook receiver, dispatcher (Lambdas) |
| `infra/`  | TypeScript (CDK) | AWS infrastructure as code |
| `worker/` | Python | Ephemeral Fargate worker: env inference, agent loop, verification |
| `eval/`   | Python | Reproducible eval harness (pass rate / cost / latency) |
| `docs/`   | Markdown | Architecture and operator docs |

## Prerequisites

- Node ≥ 20, pnpm 11
- Python ≥ 3.12 via `uv`
- (deploy) AWS credentials + `cdk bootstrap`

## Quickstart

```bash
just install     # pnpm install + uv sync (worker, eval)
just ci          # typecheck + lint + test + cdk synth
```

Without `just`:

```bash
pnpm install && uv sync --project worker && uv sync --project eval
pnpm -r test && uv run --project worker pytest -q && uv run --project eval pytest -q
pnpm --filter @it2pr/infra synth
```

## Deploy

Order matters — the ECR repository is created by the CDK stack, and the
worker image must exist before the first issue is labeled (the Fargate task
pulls `<repo>:latest`):

1. `cdk bootstrap` (once per account/region).
2. `pnpm --filter @it2pr/infra deploy` (`cdk deploy`) — stands up the VPC,
   ECS cluster + Fargate task definition, ECR repository, Lambdas, API
   Gateway, SQS, DynamoDB tables, and Secrets Manager placeholders. Note the
   `WorkerRepositoryUri` stack output.
3. `scripts/build-and-push-worker.sh <WorkerRepositoryUri> <aws-region>` —
   builds `worker/Dockerfile` and pushes `<repo>:latest` to ECR. Re-run this
   any time `worker/` changes; the Fargate task always pulls `:latest`.
4. Populate the Secrets Manager secrets:
   - `it2pr/github-app` → `{"app_id": "...", "private_key_pem": "..."}`
   - `it2pr/webhook-secret` → the raw GitHub App webhook signing secret (string)
   - `it2pr/llm-providers` → flat JSON of env-var-name → key, e.g. `{"OPENROUTER_API_KEY": "..."}`
5. Seed the `installations` allowlist table with the invited GitHub App
   installation id(s).
6. Set branch protection on `main` for each allowlisted repo (reject direct
   pushes and force-pushes) so the worker's no-force-push guarantee has a
   server-side backstop.

Docker is only required for step 3 — `cdk synth`/`cdk deploy` never build a
container image (the task definition references the ECR repository by ARN,
not a local build).

## Status

All milestones M0–M8 are implemented and tested: control plane (webhook,
dispatcher, budget, idempotency), zero-NAT CDK infra with least-privilege IAM,
Fargate worker (env inference, provider-agnostic agent loop with hard caps,
verification + PR posting), observability (Langfuse + secret scrubbing), and a
reproducible eval harness. See `.omc/plans/issue-to-pr-consensus-plan.md` for
milestone detail and `outputs/skill-issue-to-pr.md` for the system overview.
Deploy prerequisites are in the Deploy section above.
