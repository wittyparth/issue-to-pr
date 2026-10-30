// Lambda handler for the GitHub webhook receiver (API Gateway HTTP API v2).
//
// Verifies the HMAC signature, detects whether the delivery is a supported
// trigger, and enqueues a work item to SQS for the dispatcher (M2) to pick
// up. Dependencies (SQS sender, webhook secret) are injectable so the
// handler is unit-testable without touching AWS or real env vars.
import type {
  APIGatewayProxyEventV2,
  APIGatewayProxyStructuredResultV2,
} from "aws-lambda";
import { getWorkQueueUrl } from "../lib/config.js";
import { detectTrigger } from "../lib/github-events.js";
import { resolveWebhookSecret } from "../lib/secret-resolver.js";
import { createSqsSender } from "../lib/sqs.js";
import type { SqsSender } from "../lib/sqs.js";
import { verifySignature } from "../lib/verify.js";

export interface HandlerDeps {
  sqsSender?: SqsSender;
  webhookSecret?: string;
}

function getRawBody(event: APIGatewayProxyEventV2): Buffer {
  const body = event.body ?? "";
  return event.isBase64Encoded ? Buffer.from(body, "base64") : Buffer.from(body, "utf8");
}

function jsonResponse(statusCode: number, body?: unknown): APIGatewayProxyStructuredResultV2 {
  if (body === undefined) {
    return { statusCode };
  }
  return {
    statusCode,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function handler(
  event: APIGatewayProxyEventV2,
  deps: HandlerDeps = {},
): Promise<APIGatewayProxyStructuredResultV2> {
  const headers = event.headers ?? {};
  const signature = headers["x-hub-signature-256"];
  const githubEvent = headers["x-github-event"];
  const deliveryId = headers["x-github-delivery"];

  const rawBody = getRawBody(event);
  const secret = deps.webhookSecret ?? (await resolveWebhookSecret());

  if (!signature || !verifySignature(rawBody, signature, secret)) {
    return jsonResponse(401, { error: "invalid signature" });
  }

  if (!githubEvent || !deliveryId) {
    return jsonResponse(400, { error: "missing required GitHub headers" });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(rawBody.toString("utf8"));
  } catch {
    return jsonResponse(400, { error: "malformed JSON body" });
  }

  const trigger = detectTrigger(githubEvent, payload);
  if (trigger === null) {
    return jsonResponse(204);
  }

  const sqsSender = deps.sqsSender ?? createSqsSender(getWorkQueueUrl());
  await sqsSender.send(deliveryId, {
    deliveryId,
    event: githubEvent,
    kind: trigger.kind,
    repoFullName: trigger.repoFullName,
    issueNumber: trigger.issueNumber,
    installationId: trigger.installationId,
    receivedAt: new Date().toISOString(),
  });

  return jsonResponse(202, { status: "accepted" });
}
