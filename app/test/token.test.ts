import { generateKeyPairSync } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getInstallationToken } from "../src/lib/token.js";
import type { GithubAppCredentials } from "../src/lib/token.js";

const { privateKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
  publicKeyEncoding: { type: "spki", format: "pem" },
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
});

const credentials: GithubAppCredentials = {
  appId: "123456",
  privateKeyPem: privateKey,
};

function makeResponse(body: unknown, ok = true, status = 201): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("getInstallationToken", () => {
  let cache: Map<number, { token: string; expiresAtMs: number }>;

  beforeEach(() => {
    cache = new Map();
  });

  it("exchanges the App JWT for an installation token via the correct URL and Bearer header", async () => {
    const fetchImpl = vi.fn(async (_url: string, _init?: RequestInit) =>
      makeResponse({ token: "ghs_abc123", expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() }),
    );

    const result = await getInstallationToken(credentials, 999, { fetchImpl, cache });

    expect(result.token).toBe("ghs_abc123");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.github.com/app/installations/999/access_tokens");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toMatch(/^Bearer .+/);
  });

  it("returns the cached token without re-fetching when well within TTL", async () => {
    const fetchImpl = vi.fn(async () =>
      makeResponse({ token: "ghs_first", expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() }),
    );

    await getInstallationToken(credentials, 1, { fetchImpl, cache });
    const second = await getInstallationToken(credentials, 1, { fetchImpl, cache });

    expect(second.token).toBe("ghs_first");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("re-mints when the cached token is within the refresh margin of expiring", async () => {
    cache.set(1, { token: "ghs_stale", expiresAtMs: Date.now() + 60 * 1000 });

    const fetchImpl = vi.fn(async () =>
      makeResponse({ token: "ghs_fresh", expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() }),
    );

    const result = await getInstallationToken(credentials, 1, { fetchImpl, cache });

    expect(result.token).toBe("ghs_fresh");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
