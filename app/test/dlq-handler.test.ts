import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SQSEvent } from "aws-lambda";
import type { SSMClient } from "@aws-sdk/client-ssm";
import { handler } from "../src/dlq/handler.js";
import type { PostIssueCommentParams } from "../src/lib/github-comment.js";
import { getCachedSecretValue } from "../src/lib/secret-resolver.js";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env["GITHUB_APP_ID"] = "app-id-test";
  process.env["GITHUB_APP_PRIVATE_KEY_PEM"] = "pem-test";
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

describe("dlq consumer handler", () => {
  it("mints a token and posts a terminal-failure comment on the originating issue", async () => {
    const postComment = vi.fn(async (_params: PostIssueCommentParams) => undefined);
    const mintToken = vi.fn(async () => ({ token: "install-token", expiresAt: new Date() }));

    await handler(makeEvent(message), { postComment, mintToken });

    expect(mintToken).toHaveBeenCalledTimes(1);
    expect(mintToken).toHaveBeenCalledWith(
      { appId: "app-id-test", privateKeyPem: "pem-test" },
      42,
    );
    expect(postComment).toHaveBeenCalledTimes(1);
    const call = postComment.mock.calls[0]?.[0];
    expect(call?.repoFullName).toBe("acme/widgets");
    expect(call?.issueNumber).toBe(7);
    expect(call?.installationToken).toBe("install-token");
    expect(call?.body).toContain("delivery-1");
  });

  it("logs and does not throw when the message body is malformed", async () => {
    const postComment = vi.fn(async () => undefined);
    const mintToken = vi.fn(async () => ({ token: "install-token", expiresAt: new Date() }));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(
      handler(makeEvent({ not: "a valid message" }), { postComment, mintToken }),
    ).resolves.toBeUndefined();

    expect(postComment).not.toHaveBeenCalled();
    expect(errorSpy).toHaveBeenCalled();
  });

  it("swallows a failure to post the comment (no rethrow) but still logs", async () => {
    const postComment = vi.fn(async () => {
      throw new Error("GitHub 500");
    });
    const mintToken = vi.fn(async () => ({ token: "install-token", expiresAt: new Date() }));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(
      handler(makeEvent(message), { postComment, mintToken }),
    ).resolves.toBeUndefined();

    expect(errorSpy).toHaveBeenCalledWith(
      "dlq-terminal-failure: failed to post issue comment",
      expect.objectContaining({ deliveryId: "delivery-1" }),
    );
  });

  it("swallows a token-minting failure without throwing", async () => {
    const postComment = vi.fn(async () => undefined);
    const mintToken = vi.fn(async () => {
      throw new Error("token mint failed");
    });
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(
      handler(makeEvent(message), { postComment, mintToken }),
    ).resolves.toBeUndefined();

    expect(postComment).not.toHaveBeenCalled();
  });

  it("falls back to GITHUB_APP_PARAM_NAME when direct env vars are absent", async () => {
    delete process.env["GITHUB_APP_ID"];
    delete process.env["GITHUB_APP_PRIVATE_KEY_PEM"];
    process.env["GITHUB_APP_PARAM_NAME"] = "/it2pr/github-app";

    const send = vi.fn(async () => ({
      Parameter: { Value: JSON.stringify({ appId: "from-secret", privateKeyPem: "pem-from-secret" }) },
    }));
    // Warm the shared secret-resolver cache for this parameter name so the
    // DLQ handler's internal (non-injectable) call hits the cache instead of
    // constructing a real SSMClient.
    await getCachedSecretValue(process.env["GITHUB_APP_PARAM_NAME"], {
      client: { send } as unknown as SSMClient,
    });

    const postComment = vi.fn(async (_params: PostIssueCommentParams) => undefined);
    const mintToken = vi.fn(async () => ({ token: "install-token", expiresAt: new Date() }));

    await handler(makeEvent(message), { postComment, mintToken });

    expect(mintToken).toHaveBeenCalledWith(
      { appId: "from-secret", privateKeyPem: "pem-from-secret" },
      42,
    );
    expect(postComment).toHaveBeenCalledTimes(1);
  });
});
