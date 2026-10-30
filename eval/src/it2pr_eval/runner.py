"""Eval runner: triggers the pipeline per seeded issue and aggregates outcomes.

The real trigger (`HttpTrigger`) labels a GitHub issue against the deployed
webhook and polls for the resulting PR — that requires the deployed AWS
control plane. The harness itself depends only on the `Trigger` protocol, so
`run_eval` and the report layer are fully unit-testable with a fake trigger
that returns scripted `RunOutcome`s (no network, no infra).

Reproducibility (CRITICAL-3): given the same config, issues, and trigger,
`run_eval` produces the same pass/fail set in the same order. Outcomes are
sorted by issue id before returning, and no wall-clock value is consulted
when deciding pass/fail — only the trigger's reported `passed` flag.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from it2pr_eval.config import EvalConfig
from it2pr_eval.fixtures import SeedIssue


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Result of triggering the pipeline for one seeded issue."""

    issue_id: str
    passed: bool
    cost_usd: float | None
    time_to_first_action_s: float
    time_to_pr_s: float
    pr_url: str | None
    notes: str = ""


@runtime_checkable
class Trigger(Protocol):
    """Narrow boundary between the eval harness and the pipeline trigger.

    The harness depends only on this protocol so tests can inject a fake
    trigger; only `HttpTrigger` needs live infra.
    """

    def run(self, issue: SeedIssue) -> RunOutcome: ...


@dataclass(frozen=True, slots=True)
class EvalRun:
    """Aggregated result of running the full seeded issue set once."""

    config: EvalConfig
    outcomes: list[RunOutcome] = field(default_factory=list)
    issues: list[SeedIssue] = field(default_factory=list)

    @property
    def issues_by_id(self) -> dict[str, SeedIssue]:
        return {issue.id: issue for issue in self.issues}

    @property
    def pass_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.passed)

    @property
    def total_count(self) -> int:
        return len(self.outcomes)

    @property
    def meets_floor(self) -> bool:
        return self.pass_count >= self.config.pass_rate_floor


class TriggerError(RuntimeError):
    """Raised by a `Trigger` when it cannot reach or interpret the pipeline."""


@dataclass
class HttpTrigger:
    """Real trigger: labels a GitHub issue and polls for the resulting PR.

    Thin by design — it only knows how to (1) apply the trigger label via
    the GitHub API and (2) poll a status/PR-lookup endpoint until a PR
    appears or polling is exhausted. All HTTP is via the injectable `http`
    client so this can be exercised in tests without a network call, though
    in practice only live-infra runs use this class.
    """

    api_base: str
    token: str
    poll_interval_s: float = 5.0
    max_polls: int = 60
    http: httpx.Client = field(default_factory=httpx.Client)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _label_issue(self, issue: SeedIssue) -> None:
        url = f"{self.api_base}/repos/{issue.repo}/issues/{issue.issue_number}/labels"
        response = self.http.post(url, headers=self._headers(), json={"labels": ["agent"]})
        response.raise_for_status()

    def _poll_for_pr(self, issue: SeedIssue) -> dict[str, object] | None:
        url = f"{self.api_base}/repos/{issue.repo}/issues/{issue.issue_number}/run-status"
        for _ in range(self.max_polls):
            response = self.http.get(url, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "done":
                return payload
            time.sleep(self.poll_interval_s)
        raise TriggerError(
            f"timed out waiting for PR on {issue.repo}#{issue.issue_number} "
            f"after {self.max_polls} polls"
        )

    def run(self, issue: SeedIssue) -> RunOutcome:
        started = time.monotonic()
        self._label_issue(issue)
        payload = self._poll_for_pr(issue)
        finished = time.monotonic()

        return RunOutcome(
            issue_id=issue.id,
            passed=bool(payload.get("passed", False)),
            cost_usd=payload.get("cost_usd"),  # type: ignore[arg-type]
            time_to_first_action_s=float(payload.get("time_to_first_action_s", 0.0)),
            time_to_pr_s=finished - started,
            pr_url=payload.get("pr_url"),  # type: ignore[arg-type]
            notes=str(payload.get("notes", "")),
        )


def run_eval(
    config: EvalConfig,
    issues: Iterable[SeedIssue],
    trigger: Trigger,
    *,
    concurrency: int = 1,
) -> EvalRun:
    """Run every seeded issue through `trigger` and aggregate the outcomes.

    `concurrency` is capped at 1..8 to respect GitHub API rate limits
    (MAJOR-1) — a misconfigured caller cannot accidentally fan out
    unbounded parallel requests against the live API.

    Outcomes are always returned sorted by `issue_id`, independent of
    completion order, so re-running the same inputs yields an identical
    pass/fail set in identical order (reproducibility).
    """
    capped_concurrency = max(1, min(concurrency, 8))
    issue_list = list(issues)

    if capped_concurrency == 1:
        outcomes = [trigger.run(issue) for issue in issue_list]
    else:
        with ThreadPoolExecutor(max_workers=capped_concurrency) as pool:
            outcomes = list(pool.map(trigger.run, issue_list))

    outcomes.sort(key=lambda outcome: outcome.issue_id)
    return EvalRun(config=config, outcomes=outcomes, issues=issue_list)
