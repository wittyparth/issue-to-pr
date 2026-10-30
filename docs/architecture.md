# Architecture

See the source of truth: [`../.omc/plans/issue-to-pr-consensus-plan.md`](../.omc/plans/issue-to-pr-consensus-plan.md).

## Control plane (this repo, `app/` + `infra/`)

```
GitHub issue labeled `@agent fix this`
        -> API Gateway + webhook Lambda   (HMAC verify, label filter, delivery-id dedupe, enqueue)
        -> SQS
        -> dispatcher Lambda              (idempotency, allowlist, two-phase budget reserve, RunTask)
        -> ECS Fargate ephemeral task     (worker/, M3+)
```

## Key invariants (enforced across milestones)

- **Scale-to-zero:** no NAT gateways, no long-lived compute, managed/free observability.
- **Exactly-once:** `runs` conditional PutItem keyed on `SHA256(delivery_id)`; run-scoped branches.
- **Two-phase budget:** reserve PR slot pre-run, reconcile dollars post-run, release on launch failure.
- **Secret hygiene:** secrets only in Secrets Manager; scrubbed before any log/PR-body/git-dir write.
- **No token in task env:** the worker mints its own short-lived installation token at start.
- **Least-privilege IAM:** dispatcher may `RunTask` only the worker; worker reads only its run's secrets.

## Networking (M2.5)

Public subnet + `assignPublicIp` + egress-only security group; zero NAT. VPC endpoints for
AWS services (ECR/Secrets/S3/CloudWatch) where cheaper; public egress only for the LLM
provider and `github.com`.
