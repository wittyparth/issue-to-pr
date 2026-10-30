// GitHub webhook signature verification (constant-time HMAC-SHA256).
// Adapted from the capstone reference scaffold; reused unchanged in M1.
// Ref: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
import { createHmac, timingSafeEqual } from "node:crypto";

/** Compute the `sha256=<hex>` signature GitHub sends in `X-Hub-Signature-256`. */
export function expectedSig(body: Buffer, secret: string): string {
  const mac = createHmac("sha256", secret).update(body).digest("hex");
  return `sha256=${mac}`;
}

/**
 * Constant-time comparison of a received signature against the expected one.
 * Returns false on any length mismatch or malformed input rather than throwing.
 */
export function verifySignature(body: Buffer, receivedSig: string, secret: string): boolean {
  if (!receivedSig) return false;
  const expected = Buffer.from(expectedSig(body, secret), "utf8");
  const received = Buffer.from(receivedSig, "utf8");
  if (expected.length !== received.length) return false;
  return timingSafeEqual(expected, received);
}
