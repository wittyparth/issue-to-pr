import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { isAllowlisted } from "../src/lib/allowlist.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["INSTALLATIONS_TABLE"] = "installations-test";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

function fakeDocClient(item: Record<string, unknown> | undefined): {
  docClient: DynamoDBDocumentClient;
  send: ReturnType<typeof vi.fn>;
} {
  const send = vi.fn(async () => ({ Item: item }));
  return { docClient: { send } as unknown as DynamoDBDocumentClient, send };
}

describe("isAllowlisted", () => {
  it("returns true when the item exists and allowlisted is not false", async () => {
    const { docClient } = fakeDocClient({ install_id: "42", allowlisted: true });
    expect(await isAllowlisted(docClient, 42)).toBe(true);
  });

  it("returns true when the item exists and allowlisted is absent", async () => {
    const { docClient } = fakeDocClient({ install_id: "42" });
    expect(await isAllowlisted(docClient, 42)).toBe(true);
  });

  it("returns false when the item does not exist", async () => {
    const { docClient } = fakeDocClient(undefined);
    expect(await isAllowlisted(docClient, 999)).toBe(false);
  });

  it("returns false when allowlisted is explicitly false", async () => {
    const { docClient } = fakeDocClient({ install_id: "42", allowlisted: false });
    expect(await isAllowlisted(docClient, 42)).toBe(false);
  });

  // Regression: the `installations` table's `install_id` partition key is
  // STRING (infra/lib/data.ts), but `installationId` arrives as a number
  // from the webhook payload. A real DynamoDB table rejects a numeric Key
  // against a STRING partition key with ValidationException, so the
  // GetCommand Key must always be coerced to a string.
  it("sends the GetCommand Key with install_id coerced to a string", async () => {
    const { docClient, send } = fakeDocClient({ install_id: "42", allowlisted: true });
    await isAllowlisted(docClient, 42);

    expect(send).toHaveBeenCalledTimes(1);
    const command = send.mock.calls[0]?.[0] as { input: { Key: Record<string, unknown> } };
    expect(command.input.Key).toEqual({ install_id: "42" });
    expect(typeof command.input.Key["install_id"]).toBe("string");
  });
});
