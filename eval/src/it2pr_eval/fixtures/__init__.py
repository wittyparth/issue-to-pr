"""Seeded eval issue manifest.

The manifest is a static, versioned list of GitHub issues filed against
pinned-SHA fixture repos (B1-compatible: pure Python or Node/TS, no custom
system deps). `load_seed_issues` reads and validates the manifest; it does
not touch the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Literal

Difficulty = Literal["easy", "med", "hard"]

_VALID_DIFFICULTIES = frozenset({"easy", "med", "hard"})


class FixtureError(ValueError):
    """Raised when the seed-issue manifest fails validation."""


@dataclass(frozen=True, slots=True)
class SeedIssue:
    """One seeded issue in the eval set."""

    id: str
    repo: str
    commit_sha: str
    issue_number: int
    difficulty: Difficulty
    language: str
    expected_outcome: str


def _validate(entry: dict[str, object], *, index: int) -> SeedIssue:
    required = (
        "id",
        "repo",
        "commit_sha",
        "issue_number",
        "difficulty",
        "language",
        "expected_outcome",
    )
    missing = [key for key in required if key not in entry]
    if missing:
        raise FixtureError(f"seed issue at index {index} missing field(s): {', '.join(missing)}")

    commit_sha = entry["commit_sha"]
    if not isinstance(commit_sha, str) or not commit_sha:
        raise FixtureError(f"seed issue {entry.get('id')!r} is missing a pinned commit_sha")

    difficulty = entry["difficulty"]
    if difficulty not in _VALID_DIFFICULTIES:
        raise FixtureError(
            f"seed issue {entry.get('id')!r} has invalid difficulty: {difficulty!r}"
        )

    return SeedIssue(
        id=str(entry["id"]),
        repo=str(entry["repo"]),
        commit_sha=commit_sha,
        issue_number=int(entry["issue_number"]),  # type: ignore[arg-type]
        difficulty=difficulty,  # type: ignore[arg-type]
        language=str(entry["language"]),
        expected_outcome=str(entry["expected_outcome"]),
    )


def load_seed_issues(text: str | None = None) -> list[SeedIssue]:
    """Load and validate the seed-issue manifest.

    If `text` is not provided, reads the packaged `seed_issues.json` shipped
    alongside this module. Every entry must reference a pinned `commit_sha`
    and a valid difficulty.
    """
    if text is None:
        text = resources.files(__package__).joinpath("seed_issues.json").read_text("utf-8")

    data = json.loads(text)
    entries = data.get("issues", [])
    if not entries:
        raise FixtureError("seed-issue manifest has no entries")

    issues = [_validate(entry, index=i) for i, entry in enumerate(entries)]

    ids = [issue.id for issue in issues]
    if len(ids) != len(set(ids)):
        raise FixtureError("seed-issue manifest has duplicate ids")

    return issues
