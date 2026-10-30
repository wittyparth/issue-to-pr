import type { APIGatewayProxyEventV2 } from "aws-lambda";
import { describe, expect, it, vi } from "vitest";
import { handler } from "../src/webhook/handler.js";
import type { SqsSender } from "../src/lib/sqs.js";
import { expectedSig } from "../src/lib/verify.js";

const SECRET = "test-webhook-secret";

function makeEvent(opts: {
  body: string;
  event: string;
  signature?: string;
  deliveryId?: string | undefined;
}): APIGatewayProxyEventV2 {
  const headers: Record<string, string> = {
    "x-github-event": opts.event,
  };
  if (opts.deliveryId !== undefined) {
    headers["x-github-delivery"] = opts.deliveryId;
  }
  if (opts.signature !== undefined) {
    headers["x-hub-signature-256"] = opts.signature;
  }

  return {
    version: "2.0",
    routeKey: "POST /webhook",
    rawPath: "/webhook",
    rawQueryString: "",
    headers,
    requestContext: {} as APIGatewayProxyEventV2["requestContext"],
    body: opts.body,
    isBase64Encoded: false,
  } as APIGatewayProxyEventV2;
}

function makeSqsSender(): { sender: SqsSender; send: ReturnType<typeof vi.fn> } {
  const send = vi.fn(async () => undefined);
  return { sender: { send }, send };
}

const labelPayload = {
  action: "labeled",
  label: { name: "@agent fix this" },
  issue: { number: 7 },
  repository: { full_name: "acme/widgets" },
  installation: { id: 42 },
};

describe("webhook handler", () => {
  it("returns 202 and enqueues once for a valid signature + matching trigger", async () => {
    const body = JSON.stringify(labelPayload);
    const sig = expectedSig(Buffer.from(body, "utf8"), SECRET);
    const { sender, send } = makeSqsSender();

    const result = await handler(
      makeEvent({ body, event: "issues", signature: sig, deliveryId: "delivery-1" }),
      { sqsSender: sender, webhookSecret: SECRET },
    );

    expect(result.statusCode).toBe(202);
    expect(send).toHaveBeenCalledTimes(1);
    const [deliveryId, message] = send.mock.calls[0] as [string, Record<string, unknown>];
    expect(deliveryId).toBe("delivery-1");
    expect(message["deliveryId"]).toBe("delivery-1");
    expect(message["repoFullName"]).toBe("acme/widgets");
  });

  it("returns 401 and does not enqueue for an invalid signature", async () => {
    const body = JSON.stringify(labelPayload);
    const { sender, send } = makeSqsSender();

    const result = await handler(
      makeEvent({ body, event: "issues", signature: "sha256=deadbeef", deliveryId: "delivery-2" }),
      { sqsSender: sender, webhookSecret: SECRET },
    );

    expect(result.statusCode).toBe(401);
    expect(send).not.toHaveBeenCalled();
  });

  it("returns 401 when the signature header is missing", async () => {
    const body = JSON.stringify(labelPayload);
    const { sender, send } = makeSqsSender();

    const result = await handler(makeEvent({ body, event: "issues", deliveryId: "delivery-3" }), {
      sqsSender: sender,
      webhookSecret: SECRET,
    });

    expect(result.statusCode).toBe(401);
    expect(send).not.toHaveBeenCalled();
  });

  it("returns 204 for a non-triggering event (e.g. ping)", async () => {
    const body = JSON.stringify({ zen: "Keep it simple." });
    const sig = expectedSig(Buffer.from(body, "utf8"), SECRET);
    const { sender, send } = makeSqsSender();

    const result = await handler(
      makeEvent({ body, event: "ping", signature: sig, deliveryId: "delivery-4" }),
      { sqsSender: sender, webhookSecret: SECRET },
    );

    expect(result.statusCode).toBe(204);
    expect(send).not.toHaveBeenCalled();
  });

  it("returns 400 for malformed JSON even with a valid signature", async () => {
    const body = "{ not valid json";
    const sig = expectedSig(Buffer.from(body, "utf8"), SECRET);
    const { sender, send } = makeSqsSender();

    const result = await handler(
      makeEvent({ body, event: "issues", signature: sig, deliveryId: "delivery-5" }),
      { sqsSender: sender, webhookSecret: SECRET },
    );

    expect(result.statusCode).toBe(400);
    expect(send).not.toHaveBeenCalled();
  });
});
