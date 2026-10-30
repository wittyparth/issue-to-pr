"""Thin GitHub REST client (M5, MAJOR-1 rate limits + token re-mint).

Wraps an injectable httpx client so tests never touch the network. Requests
are header-authenticated (`Authorization: Bearer <token>`) — the token is
never logged or embedded in a URL. On HTTP 403/429 with `Retry-After` or
`X-RateLimit-Remaining: 0`, requests are retried with exponential backoff via
an injectable `sleep`, up to a bounded number of attempts.

Single-flight semantics for content-creation: callers (see `post_result.py`)
should check for existing state (branch/PR) before calling a create method
again on retry, since blindly retrying a POST that already succeeded could
create a duplicate. This client itself does not retry POSTs across a
network-level ambiguity; it only retries responses that GitHub explicitly
flagged as rate-limited (403/429), which are safe to retry because the
original request did not get processed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

_GITHUB_API_BASE = "https://api.github.com"
_API_VERSION = "2022-11-28"
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_BACKOFF_BASE = 1.0


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
    ) -> httpx.Response: ...


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API request fails after exhausting retries."""


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    html_url: str
    state: str
    head_ref: str


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    title: str
    body: str


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    if "Retry-After" in response.headers:
        return True
    remaining = response.headers.get("X-RateLimit-Remaining")
    return remaining == "0"


def _retry_after_seconds(response: httpx.Response, attempt: int, backoff_base: float) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
        # Retry-After may be an HTTP-date instead of a number of seconds.
        try:
            when = parsedate_to_datetime(retry_after)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            delta = (when - datetime.now(UTC)).total_seconds()
            return max(delta, 0.0)
    return backoff_base * (2**attempt)


class GitHubClient:
    """Header-authenticated GitHub REST client with rate-limit backoff."""

    def __init__(
        self,
        token: str,
        *,
        http: HttpClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = _DEFAULT_BACKOFF_BASE,
    ) -> None:
        self._token = token
        self._http = http if http is not None else httpx.Client()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(self._max_attempts):
            response = self._http.request(method, url, headers=self._headers(), json=json)
            last_response = response
            if _is_rate_limited(response) and attempt < self._max_attempts - 1:
                wait_seconds = _retry_after_seconds(response, attempt, self._backoff_base)
                self._sleep(wait_seconds)
                continue
            return response
        assert last_response is not None
        return last_response

    def get_branch(self, repo: str, branch: str) -> dict[str, Any] | None:
        """Return the branch object, or None if it does not exist (404)."""
        url = f"{_GITHUB_API_BASE}/repos/{repo}/branches/{branch}"
        response = self._request("GET", url)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubApiError(f"get_branch failed: HTTP {response.status_code}")
        return response.json()

    def get_issue(self, repo: str, issue: int) -> Issue:
        """Return the issue's number, title, and body."""
        url = f"{_GITHUB_API_BASE}/repos/{repo}/issues/{issue}"
        response = self._request("GET", url)
        if response.status_code >= 400:
            raise GitHubApiError(f"get_issue failed: HTTP {response.status_code}")
        data = response.json()
        return Issue(
            number=data["number"],
            title=data.get("title") or "",
            body=data.get("body") or "",
        )

    def get_open_pr(self, repo: str, head: str) -> PullRequest | None:
        """Return the open PR for `head` (owner:branch or branch), or None."""
        url = f"{_GITHUB_API_BASE}/repos/{repo}/pulls"
        head_param = head if ":" in head else f"{repo.split('/')[0]}:{head}"
        response = self._request("GET", f"{url}?head={head_param}&state=open")
        if response.status_code >= 400:
            raise GitHubApiError(f"get_open_pr failed: HTTP {response.status_code}")
        results = response.json()
        if not results:
            return None
        pr = results[0]
        return PullRequest(
            number=pr["number"],
            html_url=pr["html_url"],
            state=pr["state"],
            head_ref=pr["head"]["ref"],
        )

    def create_pull(self, repo: str, head: str, base: str, title: str, body: str) -> PullRequest:
        url = f"{_GITHUB_API_BASE}/repos/{repo}/pulls"
        response = self._request(
            "POST", url, json={"head": head, "base": base, "title": title, "body": body}
        )
        if response.status_code >= 400:
            raise GitHubApiError(f"create_pull failed: HTTP {response.status_code}")
        pr = response.json()
        return PullRequest(
            number=pr["number"],
            html_url=pr["html_url"],
            state=pr["state"],
            head_ref=pr["head"]["ref"],
        )

    def create_issue_comment(self, repo: str, issue: int, body: str) -> dict[str, Any]:
        url = f"{_GITHUB_API_BASE}/repos/{repo}/issues/{issue}/comments"
        response = self._request("POST", url, json={"body": body})
        if response.status_code >= 400:
            raise GitHubApiError(f"create_issue_comment failed: HTTP {response.status_code}")
        return response.json()

    def add_labels(self, repo: str, issue: int, labels: list[str]) -> dict[str, Any]:
        url = f"{_GITHUB_API_BASE}/repos/{repo}/issues/{issue}/labels"
        response = self._request("POST", url, json={"labels": labels})
        if response.status_code >= 400:
            raise GitHubApiError(f"add_labels failed: HTTP {response.status_code}")
        return response.json()
