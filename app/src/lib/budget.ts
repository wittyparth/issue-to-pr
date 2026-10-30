// Two-phase per-repo/day budget enforcement (M2).
//
// Phase 1 (pre-run): `reserveSlot` atomically increments `prs_used` on the
// `budgets` table (PK `pk` = `<repoFullName>#<YYYY-MM-DD>`) guarded by a
// conditional expression so concurrent dispatchers never overshoot the
// daily PR-count ceiling. `ConditionalCheckFailedException` is ambiguous by
// itself — it fires both for "ceiling already reached" and for transient
// contention between two concurrent conditional writes on the same item —
// so we retry a few times with small exponential backoff and only report
// "ceiling reached" once a fresh read confirms the ceiling is actually met.
//
// Phase 2 (post-run): `reconcileDollars` adds the worker-reported dollar
// cost once it's known (unknowable pre-run), and `releaseSlot` decrements
// the reserved slot if the worker never actually launched (e.g. RunTask
// failure), so the reservation isn't leaked.
import { GetCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { getBudgetsTable, getMaxPrsPerRepoPerDay } from "./config.js";

const BUDGET_TTL_SECONDS = 90 * 24 * 60 * 60; // 90 days
const MAX_RESERVE_ATTEMPTS = 5;
const BASE_BACKOFF_MS = 20;

export type ReserveResult = { ok: true } | { ok: false; reason: string };

function budgetKey(repoFullName: string, date: string): string {
  return `${repoFullName}#${date}`;
}

function isConditionalCheckFailed(err: unknown): boolean {
  return err instanceof Error && err.name === "ConditionalCheckFailedException";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function currentPrsUsed(
  docClient: DynamoDBDocumentClient,
  pk: string,
): Promise<number> {
  const result = await docClient.send(
    new GetCommand({ TableName: getBudgetsTable(), Key: { pk } }),
  );
  const value = result.Item?.["prs_used"];
  return typeof value === "number" ? value : 0;
}

/**
 * Reserve one PR-count slot for `repoFullName` on `date` (YYYY-MM-DD).
 * Returns `{ ok: true }` once the slot is reserved, or `{ ok: false, reason }`
 * once the daily ceiling is confirmed reached. Transient conditional-write
 * contention (concurrent dispatchers) is retried transparently.
 */
export async function reserveSlot(
  docClient: DynamoDBDocumentClient,
  repoFullName: string,
  date: string,
): Promise<ReserveResult> {
  const pk = budgetKey(repoFullName, date);
  const ceiling = getMaxPrsPerRepoPerDay();
  const now = Math.floor(Date.now() / 1000);

  for (let attempt = 0; attempt < MAX_RESERVE_ATTEMPTS; attempt++) {
    try {
      await docClient.send(
        new UpdateCommand({
          TableName: getBudgetsTable(),
          Key: { pk },
          UpdateExpression:
            "SET prs_used = if_not_exists(prs_used, :zero) + :one, expiresAt = :expiresAt",
          ConditionExpression: "attribute_not_exists(prs_used) OR prs_used < :ceiling",
          ExpressionAttributeValues: {
            ":zero": 0,
            ":one": 1,
            ":ceiling": ceiling,
            ":expiresAt": now + BUDGET_TTL_SECONDS,
          },
        }),
      );
      return { ok: true };
    } catch (err) {
      if (!isConditionalCheckFailed(err)) {
        throw err;
      }

      const used = await currentPrsUsed(docClient, pk);
      if (used >= ceiling) {
        return { ok: false, reason: `daily PR budget reached (${used}/${ceiling})` };
      }

      // Transient contention: another writer raced us between our read and
      // write. Back off briefly and retry.
      if (attempt < MAX_RESERVE_ATTEMPTS - 1) {
        await sleep(BASE_BACKOFF_MS * 2 ** attempt);
      }
    }
  }

  return { ok: false, reason: "budget reservation failed after retries (persistent contention)" };
}

/** Add the worker-reported dollar cost to the day's running total (post-run reconciliation). */
export async function reconcileDollars(
  docClient: DynamoDBDocumentClient,
  repoFullName: string,
  date: string,
  dollars: number,
): Promise<void> {
  const pk = budgetKey(repoFullName, date);
  const now = Math.floor(Date.now() / 1000);

  await docClient.send(
    new UpdateCommand({
      TableName: getBudgetsTable(),
      Key: { pk },
      UpdateExpression:
        "ADD dollars_used :dollars SET expiresAt = if_not_exists(expiresAt, :expiresAt)",
      ExpressionAttributeValues: {
        ":dollars": dollars,
        ":expiresAt": now + BUDGET_TTL_SECONDS,
      },
    }),
  );
}

/** Release a previously reserved PR-count slot (e.g. RunTask launch failed), floored at 0. */
export async function releaseSlot(
  docClient: DynamoDBDocumentClient,
  repoFullName: string,
  date: string,
): Promise<void> {
  const pk = budgetKey(repoFullName, date);

  await docClient.send(
    new UpdateCommand({
      TableName: getBudgetsTable(),
      Key: { pk },
      UpdateExpression: "SET prs_used = if_not_exists(prs_used, :zero) - :one",
      ConditionExpression: "attribute_not_exists(prs_used) OR prs_used > :zero",
      ExpressionAttributeValues: {
        ":zero": 0,
        ":one": 1,
      },
    }),
  );
}
