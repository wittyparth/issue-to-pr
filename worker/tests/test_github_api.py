from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from it2pr_worker.github_api import GitHubApiError, GitHubClient


@dataclass
class _FakeResponse:
    status_code: int
    _body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return self._body


class _FakeHttp:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], dict | None]] = []

    def request(
        self, method: str, url: str, *, headers: dict[str, str], json: dict | None = None
    ) -> _FakeResponse:
        self.calls.append((method, url, dict(headers), json))
        return self._responses.pop(0)


def test_create_pull_sends_correct_request() -> None:
    http = _FakeHttp(
        [
            _FakeResponse(
                201,
                {
                    "number": 7,
                    "html_url": "https://github.com/o/r/pull/7",
                    "state": "open",
                    "head": {"ref": "agent/issue-1"},
                },
            )
        ]
    )
    client = GitHubClient("ghs_mytoken", http=http)

    pr = client.create_pull("o/r", "agent/issue-1", "main", "Fix", "body text")

    assert pr.number == 7
    assert pr.html_url == "https://github.com/o/r/pull/7"

    assert len(http.calls) == 1
    method, url, headers, json_body = http.calls[0]
    assert method == "POST"
    assert url == "https://api.github.com/repos/o/r/pulls"
    assert headers["Authorization"] == "Bearer ghs_mytoken"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert json_body == {
        "head": "agent/issue-1",
        "base": "main",
        "title": "Fix",
        "body": "body text",
    }


def test_create_issue_comment_sends_correct_request() -> None:
    http = _FakeHttp([_FakeResponse(201, {"id": 1})])
    client = GitHubClient("tok", http=http)

    client.create_issue_comment("o/r", 42, "hello")

    method, url, headers, json_body = http.calls[0]
    assert method == "POST"
    assert url == "https://api.github.com/repos/o/r/issues/42/comments"
    assert json_body == {"body": "hello"}
    assert headers["Authorization"] == "Bearer tok"


def test_add_labels_sends_correct_request() -> None:
    http = _FakeHttp([_FakeResponse(200, [])])
    client = GitHubClient("tok", http=http)

    client.add_labels("o/r", 42, ["needs-review"])

    method, url, headers, json_body = http.calls[0]
    assert method == "POST"
    assert url == "https://api.github.com/repos/o/r/issues/42/labels"
    assert json_body == {"labels": ["needs-review"]}


def test_403_with_retry_after_triggers_backoff_and_retry() -> None:
    sleeps: list[float] = []
    http = _FakeHttp(
        [
            _FakeResponse(403, {}, headers={"Retry-After": "5"}),
            _FakeResponse(201, {"id": 1}),
        ]
    )
    client = GitHubClient("tok", http=http, sleep=sleeps.append)

    result = client.create_issue_comment("o/r", 1, "hi")

    assert result == {"id": 1}
    assert sleeps == [5.0]
    assert len(http.calls) == 2


def test_403_with_http_date_retry_after_triggers_backoff() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    sleeps: list[float] = []
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=30))
    http = _FakeHttp(
        [
            _FakeResponse(403, {}, headers={"Retry-After": future}),
            _FakeResponse(201, {"id": 1}),
        ]
    )
    client = GitHubClient("tok", http=http, sleep=sleeps.append)

    result = client.create_issue_comment("o/r", 1, "hi")

    assert result == {"id": 1}
    assert len(sleeps) == 1
    # ~30s in the future, floored at 0; allow generous slack for test runtime.
    assert 0.0 <= sleeps[0] <= 30.0
    assert sleeps[0] > 20.0


def test_429_without_retry_after_uses_exponential_backoff() -> None:
    sleeps: list[float] = []
    http = _FakeHttp(
        [
            _FakeResponse(429, {}, headers={"X-RateLimit-Remaining": "0"}),
            _FakeResponse(429, {}, headers={"X-RateLimit-Remaining": "0"}),
            _FakeResponse(201, {"id": 2}),
        ]
    )
    client = GitHubClient("tok", http=http, sleep=sleeps.append, backoff_base=1.0)

    result = client.create_issue_comment("o/r", 1, "hi")

    assert result == {"id": 2}
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_exhausting_retries_raises_github_api_error() -> None:
    responses = [_FakeResponse(403, {}, headers={"Retry-After": "0"}) for _ in range(5)]
    http = _FakeHttp(responses)
    client = GitHubClient("tok", http=http, sleep=lambda _s: None, max_attempts=3)

    with pytest.raises(GitHubApiError):
        client.create_issue_comment("o/r", 1, "hi")

    assert len(http.calls) == 3


def test_get_branch_returns_none_on_404() -> None:
    http = _FakeHttp([_FakeResponse(404, {})])
    client = GitHubClient("tok", http=http)

    assert client.get_branch("o/r", "missing") is None


def test_get_issue_parses_title_and_body() -> None:
    http = _FakeHttp(
        [
            _FakeResponse(
                200,
                {"number": 42, "title": "Bug: crash on startup", "body": "Steps to reproduce..."},
            )
        ]
    )
    client = GitHubClient("tok", http=http)

    issue = client.get_issue("o/r", 42)

    assert issue.number == 42
    assert issue.title == "Bug: crash on startup"
    assert issue.body == "Steps to reproduce..."

    method, url, headers, json_body = http.calls[0]
    assert method == "GET"
    assert url == "https://api.github.com/repos/o/r/issues/42"
    assert headers["Authorization"] == "Bearer tok"
    assert json_body is None


def test_get_issue_defaults_missing_body_to_empty() -> None:
    http = _FakeHttp([_FakeResponse(200, {"number": 1, "title": "t", "body": None})])
    client = GitHubClient("tok", http=http)

    issue = client.get_issue("o/r", 1)

    assert issue.body == ""


def test_get_issue_raises_on_error() -> None:
    http = _FakeHttp([_FakeResponse(404, {})])
    client = GitHubClient("tok", http=http)

    with pytest.raises(GitHubApiError):
        client.get_issue("o/r", 999)


def test_get_open_pr_returns_none_when_no_results() -> None:
    http = _FakeHttp([_FakeResponse(200, [])])
    client = GitHubClient("tok", http=http)

    assert client.get_open_pr("o/r", "some-branch") is None


def test_get_open_pr_parses_result() -> None:
    http = _FakeHttp(
        [
            _FakeResponse(
                200,
                [
                    {
                        "number": 3,
                        "html_url": "https://github.com/o/r/pull/3",
                        "state": "open",
                        "head": {"ref": "agent/issue-2"},
                    }
                ],
            )
        ]
    )
    client = GitHubClient("tok", http=http)

    pr = client.get_open_pr("o/r", "agent/issue-2")

    assert pr is not None
    assert pr.number == 3


def test_token_never_appears_in_call_records_other_than_auth_header(capsys) -> None:
    http = _FakeHttp([_FakeResponse(201, {"id": 1})])
    client = GitHubClient("ghs_supersecret", http=http)

    client.create_issue_comment("o/r", 1, "a body with no secrets")
    captured = capsys.readouterr()

    # Nothing printed at all, and the only place the token appears is the
    # Authorization header value we intentionally sent.
    assert "ghs_supersecret" not in captured.out
    assert "ghs_supersecret" not in captured.err
    method, url, headers, json_body = http.calls[0]
    assert headers["Authorization"] == "Bearer ghs_supersecret"
    assert "ghs_supersecret" not in url
    assert "ghs_supersecret" not in str(json_body)
