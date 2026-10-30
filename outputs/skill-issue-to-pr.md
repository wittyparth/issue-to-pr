# Issue-to-PR Agent — Ship It

A GitHub App + async cloud worker that turns a labeled issue into a
review-ready pull request, under a hard cost/time/turn budget, with scoped
credentials and verified (CI-in-sandbox) results. This is the M8 "Ship It"
deliverable: what the system is, how it's built, its safety/cost invariants,
how to deploy it, and how to run its reproducible eval.

Spec: `.omc/specs/deep-interview-issue-to-pr.md` · Plan: `.omc/plans/issue-to-pr-consensus-plan.md`

## What it is

Label a GitHub issue on an installed repo → the control plane dispatches an
ephemeral Fargate worker → the worker clones the repo, infers its
Python/Node toolchain, runs a provider-agnostic agentic fix loop under hard
caps, verifies full tests + coverage delta inside the sandbox, and opens a
scoped-credential PR carrying a (secret-scrubbed) rationale, cost, turn
count, and trace link.

It is not an interactive coding assistant — it is a non-interactive,
label-triggered background agent, closer in shape to Cursor Background
Agents, OpenAI Codex Cloud, or Google Jules than to a terminal coding tool.

## Architecture

Three deployable units plus an eval harness:

- **`app/`** — control plane (TypeScript, AWS Lambda + API Gateway).
  - `webhook/` verifies GitHub App webhook signatures and enqueues label
    events.
  - `dispatcher/` reserves per-repo/day budget (two-phase reserve/
    reconcile), dedupes runs exactly-once, and launches the Fargate task via
    `RunTask` — passing **secret ARNs, not secret values**, in the task's
    environment (M7 hardening).
  - `dlq/` handles failed SQS deliveries and reconciles abandoned budget
    reservations.
  - IAM, network (no NAT / no long-lived compute when idle), and API Gateway
    wiring live in `infra/` (CDK, TypeScript) — see `infra/lib/{iam,network,
    api,compute,data,functions}.ts`.

- **`worker/`** — the ephemeral Fargate task (Python), one per run.
  - Mints its own GitHub App installation token at start (never receives one
    via env); uses git header-auth so the token never lands in
    `.git/config` or the reflog.
  - `adapters/` (`PythonAdapter`, `NodeAdapter`) detect the repo's toolchain,
    install deps, run tests, and compute coverage against a pinned "B1"
    base image (pinned Python/Node toolchains, no custom system deps).
    Unsupported repos fast-fail with a clear comment instead of hanging.
  - `llm/` is a provider-agnostic boundary (`Provider.complete(messages,
    tools)`) with adapters for OpenRouter (default), OpenAI, Anthropic, and
    generic OpenAI-compatible providers. Cost is always the
    **provider-reported** usage/cost, never a hand-rolled token tally.
  - `agent/` runs a mini-SWE loop (ripgrep, tree-sitter repo map, read/edit
    file, run tests, git) under hard limits: max 30 turns, 30 minutes
    wall-clock, $20 cost ceiling. A diff allow-list guard blocks edits to
    `.github/workflows/**` before any patch is applied.
  - `observability.py` sends Langfuse traces (managed free tier) per run —
    spans for inference, each loop turn, and verification — plus CloudWatch
    structured logs. A secret scrubber runs before *any* external write:
    logs, S3 archival, and the PR body, and also scans the git directory
    for leaked tokens.

- **`eval/`** — this package (Python, uv). A reproducible harness that
  triggers the deployed pipeline against a seeded set of issues and reports
  pass rate, cost, and latency. See "Running the eval" below.

## Safety and cost invariants

- **Scoped credentials**: GitHub App installation tokens are short-lived and
  minted inside the worker; never passed in via env, never written to
  `.git/config`. Secrets Manager holds provider API keys; the dispatcher
  passes ARNs, not values, to the task.
- **No force-push, no workflow edits**: branch protection rejects force-push
  to `main`; the agent's own diff allow-list independently blocks any edit
  under `.github/workflows/**` before the patch is applied.
- **Budget enforcement**: per-repo/day dollar and PR-count caps, enforced at
  the dispatcher via two-phase reserve/reconcile so a crashed run can't leak
  budget.
- **Exactly-once dispatch**: duplicate webhook deliveries and duplicate
  labels dedupe to a single run via a idempotency key.
- **Verification before PR**: the worker runs the repo's own full test suite
  and computes a coverage delta inside the sandbox before opening a PR — a
  failing or coverage-regressing fix does not become a PR.
- **Secret hygiene**: a scrubber redacts tokens/keys from logs, the PR body,
  and the git directory (including reflog) before any of those leave the
  sandbox.
- **Hard agent-loop caps**: 30 turns / 30 minutes / $20 per run, independent
  of what the LLM provider reports, so a runaway loop cannot blow the
  budget or hang the worker.
- **Reproducible eval**: model, temperature (0), prompt version, and every
  fixture repo's commit SHA are pinned in `eval/src/it2pr_eval/config.py`
  (`EvalConfig`) — a claimed pass rate is falsifiable because a re-run
  against the same pins reproduces the same pass/fail set.

## How to deploy

```bash
# 1. Install workspace deps (TS control plane + CDK)
pnpm install

# 2. Bootstrap + deploy the control plane (webhook, dispatcher, DLQ, budget
#    tables, Fargate task definition, IAM roles)
cd infra
pnpm cdk bootstrap   # first time per account/region
pnpm cdk deploy

# 3. Install the GitHub App on the target repo(s), point its webhook at the
#    deployed API Gateway URL, and store its private key + provider API
#    keys in Secrets Manager (see infra/lib/iam.ts and functions.ts for the
#    expected secret names).

# 4. Tear down when not in active use (no ongoing charge without a
#    live task running):
pnpm cdk destroy
```

Once installed, labeling an issue (e.g. `@agent`) triggers a run
end-to-end with no further manual steps.

## How to run the eval

The eval harness lives entirely in `eval/` and only needs the deployed
control plane for a *live* run; the harness and report logic themselves are
fully unit-tested with an injected fake trigger (no infra required).

```bash
cd eval
uv sync
uv run ruff check .
uv run pytest -q

# Demonstrative report using a built-in fake trigger, no infra required:
uv run python -m it2pr_eval --dry-run
# writes eval/REPORT.md
```

A live run requires a deployed stack and a configured `HttpTrigger`
(`it2pr_eval.runner.HttpTrigger`) pointed at the installed GitHub App /
webhook, which labels each seeded issue and polls for its resulting PR. The
seeded set (`eval/src/it2pr_eval/fixtures/seed_issues.json`) is 12 issues
across two pinned-SHA fixture repos (Python + Node), mixed easy/med/hard.
`eval/src/it2pr_eval/config.py` holds the reproducibility pins
(`DEFAULT_CONFIG`): fixed model, temperature 0, a tagged prompt version, and
per-repo commit SHAs. The pass-rate floor defaults to 8/12 issues passing
(CI green + coverage OK); the rendered report states PASS/FAIL against that
floor plus p50 time-to-PR **and** the raw per-issue latency distribution
(the set is small enough that p50 alone is coarse).

## Results (fill in after a live run)

| Metric | Value |
|---|---|
| Pass rate | _n/M vs floor 8_ |
| Total cost | _$_ |
| Mean cost / PR | _$_ |
| p50 time-to-PR | _s_ |
| Raw time-to-PR distribution | _list_ |
| Mean time-to-first-action | _s_ |
| vs Cursor Background Agents (3 shared issues) | _pass rate / cost / latency comparison_ |

Generate this table by running a live eval (see above) and pasting the
`## Summary` and `## Comparison` sections of the resulting
`eval/REPORT.md`.

## Further reading

- Spec: `.omc/specs/deep-interview-issue-to-pr.md`
- Plan and milestone tracking: `.omc/plans/issue-to-pr-consensus-plan.md`
- Reference write-up and scoring rubric: `16-github-issue-to-pr-agent/docs/en.md`
