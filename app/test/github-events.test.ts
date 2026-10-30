import { describe, expect, it } from "vitest";
import { detectTrigger } from "../src/lib/github-events.js";

const REPO = { full_name: "acme/widgets" };
const INSTALLATION = { id: 12345 };
const ISSUE = { number: 42 };

describe("detectTrigger", () => {
  it("matches an issues/labeled event with the exact trigger label", () => {
    const payload = {
      action: "labeled",
      label: { name: "@Agent Fix This " },
      issue: ISSUE,
      repository: REPO,
      installation: INSTALLATION,
    };
    expect(detectTrigger("issues", payload)).toEqual({
      kind: "issue-label",
      repoFullName: "acme/widgets",
      issueNumber: 42,
      installationId: 12345,
    });
  });

  it("ignores an issues/labeled event with a non-matching label", () => {
    const payload = {
      action: "labeled",
      label: { name: "bug" },
      issue: ISSUE,
      repository: REPO,
      installation: INSTALLATION,
    };
    expect(detectTrigger("issues", payload)).toBeNull();
  });

  it("matches an issue_comment/created event whose body starts with the trigger phrase", () => {
    const payload = {
      action: "created",
      comment: { body: "  @agent fix the failing test please" },
      issue: ISSUE,
      repository: REPO,
      installation: INSTALLATION,
    };
    expect(detectTrigger("issue_comment", payload)).toEqual({
      kind: "pr-comment",
      repoFullName: "acme/widgets",
      issueNumber: 42,
      installationId: 12345,
    });
  });

  it("ignores an issue_comment/created event with a non-matching body", () => {
    const payload = {
      action: "created",
      comment: { body: "thanks for the report" },
      issue: ISSUE,
      repository: REPO,
      installation: INSTALLATION,
    };
    expect(detectTrigger("issue_comment", payload)).toBeNull();
  });

  it("returns null for a ping event", () => {
    expect(detectTrigger("ping", { zen: "Keep it logically awesome." })).toBeNull();
  });

  it("returns null (never throws) when expected fields are missing", () => {
    expect(detectTrigger("issues", { action: "labeled" })).toBeNull();
    expect(detectTrigger("issue_comment", { action: "created" })).toBeNull();
    expect(detectTrigger("issues", null)).toBeNull();
    expect(detectTrigger("issues", "not-an-object")).toBeNull();
    expect(detectTrigger("issues", undefined)).toBeNull();
  });
});
