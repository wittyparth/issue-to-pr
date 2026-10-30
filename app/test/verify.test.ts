import { describe, expect, it } from "vitest";
import { expectedSig, verifySignature } from "../src/lib/verify.js";

const SECRET = "demo-shared-secret";

describe("webhook signature verification", () => {
  it("accepts a signature produced with the same secret", () => {
    const body = Buffer.from(JSON.stringify({ zen: "Keep it simple." }), "utf8");
    const sig = expectedSig(body, SECRET);
    expect(verifySignature(body, sig, SECRET)).toBe(true);
  });

  it("rejects a signature produced with a different secret", () => {
    const body = Buffer.from(JSON.stringify({ action: "labeled" }), "utf8");
    const sig = expectedSig(body, "wrong-secret");
    expect(verifySignature(body, sig, SECRET)).toBe(false);
  });

  it("rejects an empty or malformed signature", () => {
    const body = Buffer.from("{}", "utf8");
    expect(verifySignature(body, "", SECRET)).toBe(false);
    expect(verifySignature(body, "sha256=deadbeef", SECRET)).toBe(false);
  });
});
