// Lambda handler for the work-queue dead-letter consumer (M6).
//
// A message lands here only after the dispatcher has exhausted its SQS
// redrive attempts on the work queue — i.e. a terminal failure. For each
// record: log a structured terminal-failure record (so it's queryable in
// CloudWatch Logs Insights) and best-effort post a comment on the originating
// issue so the reporter isn't left silently waiting. Never throws on the
// GitHub-comment step: a failure to notify must not re-drive the DLQ message
// (there's nowhere further for it to go), it's only logged.
import type { SQSEvent } from "aws-lambda";
import { getGithubAppId, getGithubAppPrivateKeyPem } from "../lib/config.js";
import { postIssueComment } from "../lib/github-comment.js";
import { getCachedSecretValue } from "../lib/secret-resolver.js";
import { getInstallationToken } from "../lib/token.js";

export interface DlqDeps {
  postComment?: typeof postIssueComment;
  mintToken?: typeof getInstallationToken;
}

/**
 * Resolve the GitHub App id + private key PEM at runtime: prefer direct env
 * vars (`GITHUB_APP_ID`/`GITHUB_APP_PRIVATE_KEY_PEM`, useful for local/test);
 * otherwise fetch+cache the two JSON fields from the SSM parameter
 * referenced by `GITHUB_APP_PARAM_NAME` (never baked into the CDK template
 * as plaintext).
 */
async function resolveGithubAppCredentials(): Promise<{ appId: string; privateKeyPem: string }> {
  try {
    return { appId: getGithubAppId(), privateKeyPem: getGithubAppPrivateKeyPem() };
  } catch {
    const paramName = process.env["GITHUB_APP_PARAM_NAME"];
    if (!paramName) {
      throw new Error(
        "Missing GitHub App credentials: set GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY_PEM or GITHUB_APP_PARAM_NAME",
      );
    }
    const raw = await getCachedSecretValue(paramName);
    const parsed = JSON.parse(raw) as { appId?: unknown; privateKeyPem?: unknown };
    if (typeof parsed.appId !== "string" || typeof parsed.privateKeyPem !== "string") {
      throw new Error(`Parameter ${paramName} is missing appId/privateKeyPem fields`);
    }
    return { appId: parsed.appId, privateKeyPem: parsed.privateKeyPem };
  }
}

interface DlqMessage {
  deliveryId: string;
  event: string;
  kind: string;
  repoFullName: string;
  issueNumber: number;
  installationId: number;
}

function isDlqMessage(value: unknown): value is DlqMessage {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v["deliveryId"] === "string" &&
    typeof v["event"] === "string" &&
    typeof v["kind"] === "string" &&
    typeof v["repoFullName"] === "string" &&
    typeof v["issueNumber"] === "number" &&
    typeof v["installationId"] === "number"
  );
}

function terminalFailureCommentBody(message: DlqMessage): string {
  return [
    "The Issue-to-PR agent could not complete this run after repeated attempts.",
    "",
    `- delivery: \`${message.deliveryId}\``,
    `- trigger: \`${message.kind}\``,
    "",
    "No pull request was opened. Please retry by re-applying the trigger label/comment, or contact the maintainers if this persists.",
  ].join("\n");
}

async function processRecord(body: string, deps: Required<DlqDeps>): Promise<void> {
  const parsed: unknown = JSON.parse(body);
  if (!isDlqMessage(parsed)) {
    console.error("dlq-terminal-failure: malformed message", { body });
    return;
  }

  console.error("dlq-terminal-failure", {
    deliveryId: parsed.deliveryId,
    event: parsed.event,
    kind: parsed.kind,
    repoFullName: parsed.repoFullName,
    issueNumber: parsed.issueNumber,
    installationId: parsed.installationId,
  });

  try {
    const credentials = await resolveGithubAppCredentials();
    const { token } = await deps.mintToken(credentials, parsed.installationId);
    await deps.postComment({
      repoFullName: parsed.repoFullName,
      issueNumber: parsed.issueNumber,
      installationToken: token,
      body: terminalFailureCommentBody(parsed),
    });
  } catch (err) {
    // Best-effort notification only; the terminal-failure log line above is
    // the record of truth. Don't let a notification failure surface as a
    // Lambda error (there's no further redrive target for a DLQ consumer).
    console.error("dlq-terminal-failure: failed to post issue comment", {
      deliveryId: parsed.deliveryId,
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

export async function handler(event: SQSEvent, deps: DlqDeps = {}): Promise<void> {
  const resolvedDeps: Required<DlqDeps> = {
    postComment: deps.postComment ?? postIssueComment,
    mintToken: deps.mintToken ?? getInstallationToken,
  };

  for (const record of event.Records) {
    await processRecord(record.body, resolvedDeps);
  }
}
