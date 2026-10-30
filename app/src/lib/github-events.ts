// Trigger detection for inbound GitHub webhook deliveries.
//
// A delivery is a "trigger" when it matches one of the two supported
// entrypoints for kicking off an automated fix:
//   (a) an `issues` event, action `labeled`, where the label added is
//       exactly "@agent fix this" (case-insensitive, trimmed).
//   (b) an `issue_comment` event, action `created`, where the comment body
//       starts with "@agent fix" (trimmed).
//
// Detection never throws: malformed or missing fields simply yield `null`.

const LABEL_TRIGGER = "@agent fix this";
const COMMENT_TRIGGER_PREFIX = "@agent fix";

export type TriggerKind = "issue-label" | "pr-comment";

export interface DetectedTrigger {
  kind: TriggerKind;
  repoFullName: string;
  issueNumber: number;
  installationId: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getRepoFullName(payload: Record<string, unknown>): string | null {
  const repo = payload["repository"];
  if (!isRecord(repo)) return null;
  const fullName = repo["full_name"];
  return typeof fullName === "string" && fullName.length > 0 ? fullName : null;
}

function getInstallationId(payload: Record<string, unknown>): number | null {
  const installation = payload["installation"];
  if (!isRecord(installation)) return null;
  const id = installation["id"];
  return typeof id === "number" ? id : null;
}

function getIssueNumber(payload: Record<string, unknown>): number | null {
  const issue = payload["issue"];
  if (!isRecord(issue)) return null;
  const number = issue["number"];
  return typeof number === "number" ? number : null;
}

function detectLabelTrigger(payload: Record<string, unknown>): DetectedTrigger | null {
  if (payload["action"] !== "labeled") return null;

  const label = payload["label"];
  if (!isRecord(label)) return null;
  const name = label["name"];
  if (typeof name !== "string") return null;
  if (name.trim().toLowerCase() !== LABEL_TRIGGER) return null;

  const repoFullName = getRepoFullName(payload);
  const issueNumber = getIssueNumber(payload);
  const installationId = getInstallationId(payload);
  if (repoFullName === null || issueNumber === null || installationId === null) return null;

  return { kind: "issue-label", repoFullName, issueNumber, installationId };
}

function detectCommentTrigger(payload: Record<string, unknown>): DetectedTrigger | null {
  if (payload["action"] !== "created") return null;

  const comment = payload["comment"];
  if (!isRecord(comment)) return null;
  const body = comment["body"];
  if (typeof body !== "string") return null;
  if (!body.trim().toLowerCase().startsWith(COMMENT_TRIGGER_PREFIX)) return null;

  const repoFullName = getRepoFullName(payload);
  const issueNumber = getIssueNumber(payload);
  const installationId = getInstallationId(payload);
  if (repoFullName === null || issueNumber === null || installationId === null) return null;

  return { kind: "pr-comment", repoFullName, issueNumber, installationId };
}

/**
 * Inspect a webhook delivery and decide whether it should trigger the agent.
 * Returns `null` for non-matching events (e.g. `ping`) or malformed payloads.
 */
export function detectTrigger(event: string, payload: unknown): DetectedTrigger | null {
  if (!isRecord(payload)) return null;

  try {
    if (event === "issues") return detectLabelTrigger(payload);
    if (event === "issue_comment") return detectCommentTrigger(payload);
    return null;
  } catch {
    return null;
  }
}
