import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import type { ECSClient } from "@aws-sdk/client-ecs";
import type { SQSEvent } from "aws-lambda";
import { handler } from "../src/dispatcher/handler.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["RUNS_TABLE"] = "runs-test";
  process.env["BUDGETS_TABLE"] = "budgets-test";
  process.env["INSTALLATIONS_TABLE"] = "installations-test";
  process.env["MAX_PRS_PER_REPO_PER_DAY"] = "5";
  process.env["ECS_CLUSTER"] = "cluster-test";
  process.env["ECS_TASK_DEFINITION"] = "taskdef-test";
  process.env["ECS_SUBNETS"] = "subnet-1,subnet-2";
  process.env["ECS_SECURITY_GROUPS"] = "sg-1";
  process.env["ECS_CONTAINER_NAME"] = "worker";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.restoreAllMocks();
});

const message = {
  deliveryId: "delivery-1",
  event: "issues",
  kind: "issue-label",
  repoFullName: "acme/widgets",
  issueNumber: 7,
  installationId: 42,
};

function makeEvent(body: unknown): SQSEvent {
  return {
    Records: [
      {
        body: JSON.stringify(body),
      } as SQSEvent["Records"][number],
    ],
  };
}

function conditionalCheckFailedException(): Error {
  const err = new Error("The conditional request failed");
  err.name = "ConditionalCheckFailedException";
  return err;
}

interface FakeDocClient {
  docClient: DynamoDBDocumentClient;
  send: ReturnType<typeof vi.fn>;
}

function fakeDocClient(opts: {
  claimSucceeds?: boolean;
  allowlisted?: boolean;
  budgetOk?: boolean;
  releaseSlotFails?: boolean;
}): FakeDocClient {
  const claimSucceeds = opts.claimSucceeds ?? true;
  const allowlisted = opts.allowlisted ?? true;
  const budgetOk = opts.budgetOk ?? true;
  const releaseSlotFails = opts.releaseSlotFails ?? false;

  const send = vi.fn((command: unknown) => {
    const name = (command as { constructor: { name: string } }).constructor.name;
    if (name === "PutCommand") {
      if (!claimSucceeds) return Promise.reject(conditionalCheckFailedException());
      return Promise.resolve({});
    }
    if (name === "GetCommand") {
      const input = (command as { input: { TableName: string } }).input;
      if (input.TableName === "installations-test") {
        return Promise.resolve({ Item: allowlisted ? { install_id: 42, allowlisted: true } : undefined });
      }
      // budgets GetCommand (used to distinguish ceiling-reached vs contention)
      return Promise.resolve({ Item: { prs_used: budgetOk ? 0 : 5 } });
    }
    if (name === "UpdateCommand") {
      const input = (command as { input: { TableName: string; UpdateExpression: string } }).input;
      if (input.TableName === "budgets-test" && input.UpdateExpression.includes("prs_used") && !budgetOk) {
        return Promise.reject(conditionalCheckFailedException());
      }
      // releaseSlot's UpdateCommand decrements prs_used ("- :one").
      if (
        input.TableName === "budgets-test" &&
        input.UpdateExpression.includes("- :one") &&
        releaseSlotFails
      ) {
        return Promise.reject(conditionalCheckFailedException());
      }
      return Promise.resolve({});
    }
    return Promise.resolve({});
  });

  return { docClient: { send } as unknown as DynamoDBDocumentClient, send };
}

function fakeEcsClient(opts: { shouldFail?: boolean } = {}): { ecsClient: ECSClient; send: ReturnType<typeof vi.fn> } {
  const send = vi.fn(async () => {
    if (opts.shouldFail) throw new Error("RunTask failed");
    return {};
  });
  return { ecsClient: { send } as unknown as ECSClient, send };
}

function calledCommandNames(send: ReturnType<typeof vi.fn>): string[] {
  return send.mock.calls.map(
    (call) => (call[0] as { constructor: { name: string } }).constructor.name,
  );
}

describe("dispatcher handler", () => {
  it("happy path: claims, reserves, launches, and marks dispatched", async () => {
    const { docClient, send } = fakeDocClient({});
    const { ecsClient, send: ecsSend } = fakeEcsClient();

    await handler(makeEvent(message), { docClient, ecsClient });

    expect(ecsSend).toHaveBeenCalledTimes(1);
    const names = calledCommandNames(send);
    expect(names).toContain("PutCommand");
    const updateCalls = send.mock.calls.filter(
      (call) => (call[0] as { constructor: { name: string } }).constructor.name === "UpdateCommand",
    );
    // budget reserve UpdateCommand + final status UpdateCommand
    expect(updateCalls.length).toBeGreaterThanOrEqual(2);
    const statusCall = updateCalls[updateCalls.length - 1]?.[0] as {
      input: { ExpressionAttributeValues: Record<string, unknown> };
    };
    expect(statusCall.input.ExpressionAttributeValues[":status"]).toBe("dispatched");
  });

  it("duplicate delivery (claim false) does not launch the worker", async () => {
    const { docClient } = fakeDocClient({ claimSucceeds: false });
    const { ecsClient, send: ecsSend } = fakeEcsClient();

    await handler(makeEvent(message), { docClient, ecsClient });

    expect(ecsSend).not.toHaveBeenCalled();
  });

  it("not allowlisted: no reserve/launch, status rejected", async () => {
    const { docClient, send } = fakeDocClient({ allowlisted: false });
    const { ecsClient, send: ecsSend } = fakeEcsClient();

    await handler(makeEvent(message), { docClient, ecsClient });

    expect(ecsSend).not.toHaveBeenCalled();
    const updateCalls = send.mock.calls.filter(
      (call) => (call[0] as { constructor: { name: string } }).constructor.name === "UpdateCommand",
    );
    expect(updateCalls).toHaveLength(1);
    const statusCall = updateCalls[0]?.[0] as { input: { ExpressionAttributeValues: Record<string, unknown> } };
    expect(statusCall.input.ExpressionAttributeValues[":status"]).toBe("rejected-allowlist");
  });

  it("budget exhausted: no launch, status blocked-budget", async () => {
    const { docClient, send } = fakeDocClient({ budgetOk: false });
    const { ecsClient, send: ecsSend } = fakeEcsClient();

    await handler(makeEvent(message), { docClient, ecsClient });

    expect(ecsSend).not.toHaveBeenCalled();
    const updateCalls = send.mock.calls.filter(
      (call) => (call[0] as { constructor: { name: string } }).constructor.name === "UpdateCommand",
    );
    const statusCall = updateCalls[updateCalls.length - 1]?.[0] as {
      input: { ExpressionAttributeValues: Record<string, unknown> };
    };
    expect(statusCall.input.ExpressionAttributeValues[":status"]).toBe("blocked-budget");
  });

  it("RunTask throws: releaseSlot is called and the handler rethrows", async () => {
    const { docClient, send } = fakeDocClient({});
    const { ecsClient } = fakeEcsClient({ shouldFail: true });

    await expect(handler(makeEvent(message), { docClient, ecsClient })).rejects.toThrow("RunTask failed");

    const updateCalls = send.mock.calls.filter(
      (call) => (call[0] as { constructor: { name: string } }).constructor.name === "UpdateCommand",
    );
    // reserve slot + release slot + launch-failed status = 3 UpdateCommands
    expect(updateCalls.length).toBeGreaterThanOrEqual(3);
    const releaseCall = updateCalls.find((call) => {
      const input = (call[0] as { input: { UpdateExpression: string } }).input;
      return input.UpdateExpression.includes("- :one");
    });
    expect(releaseCall).toBeDefined();
    const statusCall = updateCalls[updateCalls.length - 1]?.[0] as {
      input: { ExpressionAttributeValues: Record<string, unknown> };
    };
    expect(statusCall.input.ExpressionAttributeValues[":status"]).toBe("launch-failed");
  });

  // Regression: releaseSlot is best-effort in the launch-failure path. If it
  // also throws (e.g. ConditionalCheckFailedException), that failure must
  // not mask the original launchWorker error, and the run status must still
  // be recorded as launch-failed.
  it("RunTask throws and releaseSlot also throws: the original launch error propagates and status is launch-failed", async () => {
    const { docClient, send } = fakeDocClient({ releaseSlotFails: true });
    const { ecsClient } = fakeEcsClient({ shouldFail: true });

    await expect(handler(makeEvent(message), { docClient, ecsClient })).rejects.toThrow(
      "RunTask failed",
    );

    const updateCalls = send.mock.calls.filter(
      (call) => (call[0] as { constructor: { name: string } }).constructor.name === "UpdateCommand",
    );
    const statusCall = updateCalls[updateCalls.length - 1]?.[0] as {
      input: { ExpressionAttributeValues: Record<string, unknown> };
    };
    expect(statusCall.input.ExpressionAttributeValues[":status"]).toBe("launch-failed");
  });
});
