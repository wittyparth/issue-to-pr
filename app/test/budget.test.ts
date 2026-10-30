import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { reconcileDollars, releaseSlot, reserveSlot } from "../src/lib/budget.js";

function conditionalCheckFailedException(): Error {
  const err = new Error("The conditional request failed");
  err.name = "ConditionalCheckFailedException";
  return err;
}

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["BUDGETS_TABLE"] = "budgets-test";
  process.env["MAX_PRS_PER_REPO_PER_DAY"] = "5";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.restoreAllMocks();
});

describe("reserveSlot", () => {
  it("succeeds under the ceiling with a single conditional UpdateCommand", async () => {
    const send = vi.fn(async () => ({}));
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    const result = await reserveSlot(docClient, "acme/widgets", "2026-08-22");

    expect(result).toEqual({ ok: true });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("returns ok:false with a reason when the ceiling is reached (persistent failure)", async () => {
    const send = vi.fn((command: unknown) => {
      const name = (command as { constructor: { name: string } }).constructor.name;
      if (name === "UpdateCommand") {
        return Promise.reject(conditionalCheckFailedException());
      }
      // GetCommand used to distinguish "ceiling reached" from contention.
      return Promise.resolve({ Item: { prs_used: 5 } });
    });
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    const result = await reserveSlot(docClient, "acme/widgets", "2026-08-22");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toMatch(/budget reached/);
    }
  });

  it("retries transient contention (fails once, then succeeds) and returns ok", async () => {
    let updateCalls = 0;
    const send = vi.fn((command: unknown) => {
      const name = (command as { constructor: { name: string } }).constructor.name;
      if (name === "UpdateCommand") {
        updateCalls += 1;
        if (updateCalls === 1) {
          return Promise.reject(conditionalCheckFailedException());
        }
        return Promise.resolve({});
      }
      // GetCommand reports below-ceiling usage, so the failure is treated as
      // transient contention rather than a reached ceiling.
      return Promise.resolve({ Item: { prs_used: 1 } });
    });
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    const result = await reserveSlot(docClient, "acme/widgets", "2026-08-22");

    expect(result).toEqual({ ok: true });
    expect(updateCalls).toBe(2);
  });
});

describe("releaseSlot", () => {
  it("issues a decrementing conditional UpdateCommand", async () => {
    const send = vi.fn(async () => ({}));
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    await releaseSlot(docClient, "acme/widgets", "2026-08-22");

    expect(send).toHaveBeenCalledTimes(1);
    const [command] = send.mock.calls[0] as unknown as [
      { input: { UpdateExpression: string; ExpressionAttributeValues: Record<string, unknown> } },
    ];
    expect(command.input.UpdateExpression).toMatch(/- :one/);
  });
});

describe("reconcileDollars", () => {
  it("issues an ADD UpdateCommand for the dollar amount", async () => {
    const send = vi.fn(async () => ({}));
    const docClient = { send } as unknown as DynamoDBDocumentClient;

    await reconcileDollars(docClient, "acme/widgets", "2026-08-22", 3.5);

    expect(send).toHaveBeenCalledTimes(1);
    const [command] = send.mock.calls[0] as unknown as [
      { input: { UpdateExpression: string; ExpressionAttributeValues: Record<string, unknown> } },
    ];
    expect(command.input.UpdateExpression).toMatch(/ADD dollars_used/);
    expect(command.input.ExpressionAttributeValues[":dollars"]).toBe(3.5);
  });
});
