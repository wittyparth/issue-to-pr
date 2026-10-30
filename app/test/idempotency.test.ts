import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { tryClaimRun } from "../src/lib/idempotency.js";
import type { RunMeta } from "../src/lib/idempotency.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["RUNS_TABLE"] = "runs-test";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

const meta: RunMeta = {
  deliveryId: "delivery-1",
  event: "issues",
  kind: "issue-label",
  repoFullName: "acme/widgets",
  issueNumber: 7,
  installationId: 42,
};

function conditionalCheckFailedException(): Error {
  const err = new Error("The conditional request failed");
  err.name = "ConditionalCheckFailedException";
  return err;
}

describe("tryClaimRun", () => {
  it("returns true on first claim (PutCommand succeeds)", async () => {
    const send = vi.fn(async () => ({}));
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    const claimed = await tryClaimRun(docClient, "run-1", meta);

    expect(claimed).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("returns false when the run already exists (ConditionalCheckFailedException)", async () => {
    const send = vi.fn(async () => {
      throw conditionalCheckFailedException();
    });
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    const claimed = await tryClaimRun(docClient, "run-1", meta);

    expect(claimed).toBe(false);
  });

  it("rethrows unrelated errors", async () => {
    const send = vi.fn(async () => {
      throw new Error("network blip");
    });
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    await expect(tryClaimRun(docClient, "run-1", meta)).rejects.toThrow("network blip");
  });
});
