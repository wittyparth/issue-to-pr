// Minimal GitHub issue-comment poster (M6 DLQ consumer).
//
// Posts a single comment to an issue/PR using an installation access token.
// Kept intentionally small: no retries/backoff here (the DLQ consumer is a
// best-effort terminal-failure notifier, not part of the main run path).
export interface FetchLike {
  (input: string, init?: RequestInit): Promise<Response>;
}

export interface PostIssueCommentParams {
  repoFullName: string;
  issueNumber: number;
  installationToken: string;
  body: string;
  fetchImpl?: FetchLike;
}

/** Post a comment to a GitHub issue (or PR, which shares the issues API) via REST. */
export async function postIssueComment(params: PostIssueCommentParams): Promise<void> {
  const fetchImpl = params.fetchImpl ?? fetch;
  const url = `https://api.github.com/repos/${params.repoFullName}/issues/${params.issueNumber}/comments`;

  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${params.installationToken}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "content-type": "application/json",
    },
    body: JSON.stringify({ body: params.body }),
  });

  if (!response.ok) {
    throw new Error(`Failed to post issue comment: HTTP ${response.status}`);
  }
}
