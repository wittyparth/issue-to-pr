// @it2pr/app — TypeScript control plane (GitHub App, webhook receiver, dispatcher).
// Lambdas are added in M1 (webhook) and M2 (dispatcher). This entry re-exports
// shared library surface so the package has a stable public API from M0.
export { expectedSig, verifySignature } from "./lib/verify.js";
export { detectTrigger } from "./lib/github-events.js";
export type { DetectedTrigger, TriggerKind } from "./lib/github-events.js";
export { getInstallationToken, mintAppJwt } from "./lib/token.js";
export type { GithubAppCredentials, InstallationToken } from "./lib/token.js";
export { createSqsSender } from "./lib/sqs.js";
export type { SqsSender } from "./lib/sqs.js";
export { handler } from "./webhook/handler.js";
export type { HandlerDeps } from "./webhook/handler.js";
export { getCachedSecretValue, resolveWebhookSecret } from "./lib/secret-resolver.js";
export type { SecretResolverOptions } from "./lib/secret-resolver.js";

// M2: dispatcher (exactly-once idempotency, allowlist, two-phase budget, ECS launch).
export { runIdForDelivery, branchName } from "./lib/run-id.js";
export { tryClaimRun } from "./lib/idempotency.js";
export type { RunMeta } from "./lib/idempotency.js";
export { isAllowlisted } from "./lib/allowlist.js";
export { reserveSlot, reconcileDollars, releaseSlot } from "./lib/budget.js";
export type { ReserveResult } from "./lib/budget.js";
export { launchWorker } from "./lib/ecs.js";
export type { LaunchWorkerParams } from "./lib/ecs.js";
export { getDefaultDocClient } from "./lib/dynamo.js";
export { handler as dispatcherHandler } from "./dispatcher/handler.js";
export type { DispatcherDeps } from "./dispatcher/handler.js";

// M6: DLQ consumer (terminal-failure logging + best-effort issue comment).
export { postIssueComment } from "./lib/github-comment.js";
export type { PostIssueCommentParams } from "./lib/github-comment.js";
export { handler as dlqHandler } from "./dlq/handler.js";
export type { DlqDeps } from "./dlq/handler.js";
