"""Eval configuration: reproducibility pins + pass-rate floor (CRITICAL-3).

A reproducible eval requires a pinned model, temperature 0, a tagged prompt
version, and fixture repos pinned to a commit SHA. Without these pins the
pass/fail outcome of a run is not falsifiable — a portfolio claim built on
an unpinned eval is not evidence. This module defines and validates those
pins; it does not run anything.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when an EvalConfig fails reproducibility validation."""


@dataclass(frozen=True, slots=True)
class FixtureRepo:
    """A pinned fixture repository used as an eval target.

    `commit_sha` pins the exact state of the repo that seeded issues are
    filed against, so re-running the eval later doesn't drift onto a moved
    branch tip.
    """

    full_name: str
    commit_sha: str
    language: str


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Reproducibility pins + pass-rate floor for one eval run.

    `model`, `temperature`, and `prompt_version` pin the agent's behavior;
    `fixture_repos` pin the target repos to a commit SHA; `pass_rate_floor`
    is the minimum number of passing issues (out of the seeded set) required
    for a "PASS" verdict in the rendered report.
    """

    model: str
    temperature: float
    prompt_version: str
    fixture_repos: list[FixtureRepo] = field(default_factory=list)
    pass_rate_floor: int = 8

    def __post_init__(self) -> None:
        if self.temperature != 0.0:
            raise ConfigError(
                f"temperature must be 0.0 for a reproducible eval, got: {self.temperature!r}"
            )
        if not self.model:
            raise ConfigError("model must be set for a reproducible eval")
        if not self.prompt_version:
            raise ConfigError("prompt_version must be set for a reproducible eval")
        if not self.fixture_repos:
            raise ConfigError("fixture_repos must be non-empty")
        for repo in self.fixture_repos:
            if not repo.commit_sha:
                raise ConfigError(
                    f"fixture repo {repo.full_name!r} is missing a pinned commit_sha"
                )
        if self.pass_rate_floor < 0:
            raise ConfigError(f"pass_rate_floor must be >= 0, got: {self.pass_rate_floor!r}")

    def repo_by_name(self, full_name: str) -> FixtureRepo:
        for repo in self.fixture_repos:
            if repo.full_name == full_name:
                return repo
        raise ConfigError(f"no pinned fixture repo named {full_name!r} in this config")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalConfig:
        repos = [
            FixtureRepo(
                full_name=r["full_name"],
                commit_sha=r["commit_sha"],
                language=r["language"],
            )
            for r in data.get("fixture_repos", [])
        ]
        return cls(
            model=data["model"],
            temperature=float(data["temperature"]),
            prompt_version=data["prompt_version"],
            fixture_repos=repos,
            pass_rate_floor=int(data.get("pass_rate_floor", 8)),
        )

    @classmethod
    def from_file(cls, path: Path | str) -> EvalConfig:
        """Load an EvalConfig from a `.json` or `.toml` file."""
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix == ".toml":
            data = tomllib.loads(text)
        elif file_path.suffix == ".json":
            data = json.loads(text)
        else:
            raise ConfigError(f"unsupported config file extension: {file_path.suffix!r}")
        return cls.from_dict(data)


DEFAULT_CONFIG = EvalConfig(
    model="anthropic/claude-sonnet-4-20250514",
    temperature=0.0,
    prompt_version="issue-to-pr-v1",
    fixture_repos=[
        FixtureRepo(
            full_name="it2pr-eval/fixture-python-cli",
            commit_sha="a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3",
            language="python",
        ),
        FixtureRepo(
            full_name="it2pr-eval/fixture-node-api",
            commit_sha="b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4",
            language="node",
        ),
    ],
    pass_rate_floor=8,
)
