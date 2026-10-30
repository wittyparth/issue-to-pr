// Lambda handler for the SQS-triggered dispatcher (M2).
//
// For each record (the M1 webhook message: deliveryId, event, kind,
// repoFullName, issueNumber, installationId):
//   1. tryClaimRun  — exactly-once guard; duplicate delivery skips silently.
//   2. isAllowlisted — invite-only gate; rejects with a recorded status.
//   3. reserveSlot   — two-phase budget; blocks with a recorded reason.
//   4. launchWorker  — Fargate RunTask with metadata-only env overrides.
//      On failure: releaseSlot (don't leak the reservation), record
//      "launch-failed", and rethrow so SQS can retry/DLQ the record.
//   5. On success: record "dispatched".
//
// Dependencies (doc client, ECS client, budget ceilings) are injectable via
// `DispatcherDeps`, mirroring M1's `HandlerDeps` on the webhook handler, so
// the handler is unit-testable without touching AWS.
import type { SQSEvent } from "aws-lambda";
import { UpdateCommand } from "@aws-sdk/lib-dynamodb";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { ECSClient } from "@aws-sdk/client-ecs";
import { isAllowlisted } from "../lib/allowlist.js";
import { releaseSlot, reserveSlot } from "../lib/budget.js";
import { getRunsTable } from "../lib/config.js";
import { getDefaultDocClient } from "../lib/dynamo.js";
import { launchWorker } from "../lib/ecs.js";
import { tryClaimRun } from "../lib/idempotency.js";
import { branchName, runIdForDelivery } from "../lib/run-id.js";

export interface DispatcherDeps {
  docClient?: DynamoDBDocumentClient;
  ecsClient?: ECSClient;
}

interface WorkMessage {
  deliveryId: string;
  event: string;
  kind: string;
  repoFullName: string;
  issueNumber: number;
  installationId: number;
}

function isWorkMessage(value: unknown): value is WorkMessage {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v["deliveryId"] === "string" &&
    typeof v["event"] === "string" &&
    typeof v["kind"] === "string" &&
    typeof v["repoFullName"] === "string" &&
    typeof v["issueNumber"] === "number" &&
    typeof v["installationId"] === "number"
  );
}

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

async function updateRunStatus(
  docClient: DynamoDBDocumentClient,
  runId: string,
  status: string,
  reason?: string,
): Promise<void> {
  const expressionValues: Record<string, unknown> = { ":status": status };
  let updateExpression = "SET #status = :status";
  if (reason !== undefined) {
    updateExpression += ", reason = :reason";
    expressionValues[":reason"] = reason;
  }

  await docClient.send(
    new UpdateCommand({
      TableName: getRunsTable(),
      Key: { run_id: runId },
      UpdateExpression: updateExpression,
      ExpressionAttributeNames: { "#status": "status" },
      ExpressionAttributeValues: expressionValues,
    }),
  );
}

async function processRecord(
  body: string,
  docClient: DynamoDBDocumentClient,
  ecsClient: ECSClient,
): Promise<void> {
  const parsed: unknown = JSON.parse(body);
  if (!isWorkMessage(parsed)) {
    throw new Error("malformed dispatcher message");
  }

  const runId = runIdForDelivery(parsed.deliveryId);

  const claimed = await tryClaimRun(docClient, runId, {
    deliveryId: parsed.deliveryId,
    event: parsed.event,
    kind: parsed.kind,
    repoFullName: parsed.repoFullName,
    issueNumber: parsed.issueNumber,
    installationId: parsed.installationId,
  });
  if (!claimed) {
    // Duplicate delivery of an already-claimed run; skip silently.
    return;
  }

  const allowed = await isAllowlisted(docClient, parsed.installationId);
  if (!allowed) {
    await updateRunStatus(docClient, runId, "rejected-allowlist");
    return;
  }

  const date = todayUtc();
  const reservation = await reserveSlot(docClient, parsed.repoFullName, date);
  if (!reservation.ok) {
    await updateRunStatus(docClient, runId, "blocked-budget", reservation.reason);
    return;
  }

  const branch = branchName(parsed.issueNumber, runId);
  try {
    // NOTE: `date` (the budget partition reserved above) is not currently
    // threaded into the worker's RunTask env. The worker's own
    // cross-process budget reconciliation (reconcileDollars) recomputes
    // "today" independently, which can disagree with `date` if the run
    // straddles UTC midnight. Follow-up: pass `date` through as a
    // `BUDGET_DATE` env override in `launchWorker`/`ecs.ts` so the worker
    // reconciles against the same partition it was dispatched under.
    await launchWorker(ecsClient, {
      repoFullName: parsed.repoFullName,
      issueNumber: parsed.issueNumber,
      installationId: parsed.installationId,
      runId,
      branch,
      kind: parsed.kind,
    });
  } catch (err) {
    // Best-effort: a ConditionalCheckFailedException (or any other error)
    // from releaseSlot here must never mask the original launch error, and
    // must never prevent the run status from being recorded as
    // launch-failed below.
    try {
      await releaseSlot(docClient, parsed.repoFullName, date);
    } catch {
      // Swallow — the original launch error is what must propagate.
    }
    await updateRunStatus(docClient, runId, "launch-failed");
    throw err;
  }

  await updateRunStatus(docClient, runId, "dispatched");
}

let defaultEcsClient: ECSClient | undefined;

function getDefaultEcsClient(): ECSClient {
  defaultEcsClient ??= new ECSClient({});
  return defaultEcsClient;
}

export async function handler(event: SQSEvent, deps: DispatcherDeps = {}): Promise<void> {
  const docClient = deps.docClient ?? getDefaultDocClient();
  const ecsClient = deps.ecsClient ?? getDefaultEcsClient();

  for (const record of event.Records) {
    await processRecord(record.body, docClient, ecsClient);
  }
}
