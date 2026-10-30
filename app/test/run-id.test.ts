import { describe, expect, it } from "vitest";
import { branchName, runIdForDelivery } from "../src/lib/run-id.js";

describe("runIdForDelivery", () => {
  it("is deterministic: the same delivery id always yields the same run id", () => {
    const a = runIdForDelivery("delivery-123");
    const b = runIdForDelivery("delivery-123");
    expect(a).toBe(b);
  });

  it("produces a 64-char lowercase hex SHA-256 digest", () => {
    const runId = runIdForDelivery("delivery-abc");
    expect(runId).toMatch(/^[0-9a-f]{64}$/);
  });

  it("produces distinct run ids for distinct delivery ids", () => {
    const a = runIdForDelivery("delivery-1");
    const b = runIdForDelivery("delivery-2");
    expect(a).not.toBe(b);
  });
});

describe("branchName", () => {
  it("formats as agent/issue-<n>-<first 8 chars of runId>", () => {
    const runId = runIdForDelivery("delivery-xyz");
    const branch = branchName(42, runId);
    expect(branch).toBe(`agent/issue-42-${runId.slice(0, 8)}`);
  });

  it("is deterministic for the same issue number and run id", () => {
    const runId = runIdForDelivery("delivery-xyz");
    expect(branchName(7, runId)).toBe(branchName(7, runId));
  });
});
