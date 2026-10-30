// Deterministic run-id derivation and run-scoped branch naming.
//
// A run id is the SHA-256 hex digest of the originating webhook delivery id.
// This makes the exactly-once idempotency check (see `idempotency.ts`) a
// pure function of the delivery id: two identical deliveries always yield
// the same run id, and distinct delivery ids are collision-resistant
// against each other (per plan Execution Note, M2).
import { createHash } from "node:crypto";

/** Derive the deterministic run id for a webhook delivery id. */
export function runIdForDelivery(deliveryId: string): string {
  return createHash("sha256").update(deliveryId, "utf8").digest("hex");
}

/**
 * Build the run-scoped branch name for a fix, e.g. `agent/issue-42-a1b2c3d4`.
 * Scoping the branch to the run id (not just the issue number) avoids push
 * races between concurrent runs against the same issue.
 */
export function branchName(issueNumber: number, runId: string): string {
  return `agent/issue-${issueNumber}-${runId.slice(0, 8)}`;
}
