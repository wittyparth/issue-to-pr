import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ECSClient } from "@aws-sdk/client-ecs";
import { launchWorker } from "../src/lib/ecs.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["ECS_CLUSTER"] = "cluster-test";
  process.env["ECS_TASK_DEFINITION"] = "taskdef-test";
  process.env["ECS_SUBNETS"] = "subnet-1,subnet-2";
  process.env["ECS_SECURITY_GROUPS"] = "sg-1";
  process.env["ECS_CONTAINER_NAME"] = "worker";
  delete process.env["GITHUB_APP_PARAM_NAME"];
  delete process.env["LLM_PROVIDERS_PARAM_NAME"];
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.restoreAllMocks();
});

function fakeEcsClient(): { ecsClient: ECSClient; send: ReturnType<typeof vi.fn> } {
  const send = vi.fn(async () => ({}));
  return { ecsClient: { send } as unknown as ECSClient, send };
}

const params = {
  repoFullName: "acme/widgets",
  issueNumber: 7,
  installationId: 42,
  runId: "run-1",
  branch: "it2pr/fix-7",
  kind: "issue-label",
};

function containerEnv(send: ReturnType<typeof vi.fn>): { name: string; value: string }[] {
  const call = send.mock.calls[0]?.[0] as {
    input: { overrides: { containerOverrides: { environment: { name: string; value: string }[] }[] } };
  };
  return call.input.overrides.containerOverrides[0]?.environment ?? [];
}

describe("launchWorker", () => {
  it("passes the GITHUB_APP_PARAM_NAME env when set, and no secret value", async () => {
    process.env["GITHUB_APP_PARAM_NAME"] = "/it2pr/github-app";
    const { ecsClient, send } = fakeEcsClient();

    await launchWorker(ecsClient, params);

    const env = containerEnv(send);
    const paramEntry = env.find((e) => e.name === "GITHUB_APP_PARAM_NAME");
    expect(paramEntry?.value).toBe("/it2pr/github-app");

    // No secret value (private key material, tokens) present anywhere in env.
    const serialized = JSON.stringify(env);
    expect(serialized).not.toMatch(/BEGIN (RSA )?PRIVATE KEY/);
    expect(serialized).not.toMatch(/ghs_[A-Za-z0-9_]+/);
  });

  it("passes the LLM_PROVIDERS_PARAM_NAME env when set", async () => {
    process.env["LLM_PROVIDERS_PARAM_NAME"] = "/it2pr/llm-providers";
    const { ecsClient, send } = fakeEcsClient();

    await launchWorker(ecsClient, params);

    const env = containerEnv(send);
    const paramEntry = env.find((e) => e.name === "LLM_PROVIDERS_PARAM_NAME");
    expect(paramEntry?.value).toBe("/it2pr/llm-providers");
  });

  it("omits the param name env vars entirely when not configured", async () => {
    const { ecsClient, send } = fakeEcsClient();

    await launchWorker(ecsClient, params);

    const env = containerEnv(send);
    expect(env.find((e) => e.name === "GITHUB_APP_PARAM_NAME")).toBeUndefined();
    expect(env.find((e) => e.name === "LLM_PROVIDERS_PARAM_NAME")).toBeUndefined();
  });

  it("still passes the existing run-metadata env vars", async () => {
    const { ecsClient, send } = fakeEcsClient();

    await launchWorker(ecsClient, params);

    const env = containerEnv(send);
    const byName = Object.fromEntries(env.map((e) => [e.name, e.value]));
    expect(byName["REPO_FULL_NAME"]).toBe("acme/widgets");
    expect(byName["ISSUE_NUMBER"]).toBe("7");
    expect(byName["INSTALLATION_ID"]).toBe("42");
    expect(byName["RUN_ID"]).toBe("run-1");
    expect(byName["BRANCH"]).toBe("it2pr/fix-7");
    expect(byName["EVENT_KIND"]).toBe("issue-label");
  });
});
