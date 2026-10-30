import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SSMClient } from "@aws-sdk/client-ssm";
import { getCachedSecretValue, resolveWebhookSecret } from "../src/lib/secret-resolver.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV };
  delete process.env["GH_WEBHOOK_SECRET"];
  delete process.env["GH_WEBHOOK_PARAM_NAME"];
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.restoreAllMocks();
});

function fakeSsmClient(value: string | undefined): {
  client: SSMClient;
  send: ReturnType<typeof vi.fn>;
} {
  const send = vi.fn(async () => ({ Parameter: { Value: value } }));
  return { client: { send } as unknown as SSMClient, send };
}

describe("resolveWebhookSecret", () => {
  it("returns GH_WEBHOOK_SECRET directly when set, without calling SSM", async () => {
    process.env["GH_WEBHOOK_SECRET"] = "direct-secret";
    const { client, send } = fakeSsmClient("unused");

    const value = await resolveWebhookSecret({ client });

    expect(value).toBe("direct-secret");
    expect(send).not.toHaveBeenCalled();
  });

  it("fetches from SSM via GH_WEBHOOK_PARAM_NAME when direct secret is absent", async () => {
    process.env["GH_WEBHOOK_PARAM_NAME"] = "/it2pr/webhook-secret";
    const { client, send } = fakeSsmClient("from-ssm");

    const value = await resolveWebhookSecret({ client, cache: new Map() });

    expect(value).toBe("from-ssm");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("caches the resolved value across repeated calls (one SSM call)", async () => {
    process.env["GH_WEBHOOK_PARAM_NAME"] = "/it2pr/webhook-secret";
    const { client, send } = fakeSsmClient("cached-secret");
    const cache = new Map<string, string>();

    const first = await resolveWebhookSecret({ client, cache });
    const second = await resolveWebhookSecret({ client, cache });

    expect(first).toBe("cached-secret");
    expect(second).toBe("cached-secret");
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("throws when neither GH_WEBHOOK_SECRET nor GH_WEBHOOK_PARAM_NAME is set", async () => {
    await expect(resolveWebhookSecret()).rejects.toThrow(
      "Missing required environment variable: GH_WEBHOOK_SECRET or GH_WEBHOOK_PARAM_NAME",
    );
  });
});

describe("getCachedSecretValue", () => {
  it("throws when the parameter has no string value", async () => {
    const { client } = fakeSsmClient(undefined);

    await expect(getCachedSecretValue("some-param", { client, cache: new Map() })).rejects.toThrow(
      "Parameter some-param has no string value",
    );
  });
});
