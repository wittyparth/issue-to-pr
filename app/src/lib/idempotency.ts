// Exactly-once run claiming (M2 idempotency guard).
//
// A run is claimed by a conditional PutItem on the `runs` table keyed by
// `run_id`. If the item already exists (webhook redelivery of the same
// `X-GitHub-Delivery` id, which hashes to the same run id — see
// `run-id.ts`), the conditional check fails and we treat the delivery as a
// duplicate to skip silently. A genuine re-label produces a new delivery id
// and therefore a new run id, so it claims successfully.
import { PutCommand } from "@aws-sdk/lib-dynamodb";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { getRunsTable } from "./config.js";

const RUN_TTL_SECONDS = 30 * 24 * 60 * 60; // 30 days

export interface RunMeta {
  deliveryId: string;
  event: string;
  kind: string;
  repoFullName: string;
  issueNumber: number;
  installationId: number;
}

/**
 * Attempt to claim `runId` for processing. Returns `true` if this call
 * created the run record (first delivery), `false` if a run with this id
 * already exists (duplicate delivery).
 */
export async function tryClaimRun(
  docClient: DynamoDBDocumentClient,
  runId: string,
  meta: RunMeta,
): Promise<boolean> {
  const now = Date.now();
  try {
    await docClient.send(
      new PutCommand({
        TableName: getRunsTable(),
        Item: {
          run_id: runId,
          status: "claimed",
          createdAt: new Date(now).toISOString(),
          expiresAt: Math.floor(now / 1000) + RUN_TTL_SECONDS,
          deliveryId: meta.deliveryId,
          event: meta.event,
          kind: meta.kind,
          repoFullName: meta.repoFullName,
          issueNumber: meta.issueNumber,
          installationId: meta.installationId,
        },
        ConditionExpression: "attribute_not_exists(run_id)",
      }),
    );
    return true;
  } catch (err) {
    if (err instanceof Error && err.name === "ConditionalCheckFailedException") {
      return false;
    }
    throw err;
  }
}
