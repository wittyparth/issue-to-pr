"""Run configuration loaded from task-environment overrides.

The dispatcher (M2) launches the Fargate task with run metadata only — repo,
issue number, installation id, run id, branch, event kind — never secrets.
This module loads and validates that metadata. No tokens or private keys
belong here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED_VARS = (
    "REPO_FULL_NAME",
    "ISSUE_NUMBER",
    "INSTALLATION_ID",
    "RUN_ID",
    "BRANCH",
    "EVENT_KIND",
)


class ConfigError(ValueError):
    """Raised when required run-configuration environment variables are missing or invalid."""


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Run metadata passed to the worker via task-environment overrides.

    Deliberately excludes secrets: the worker mints its own installation
    token at start (see token.py) rather than receiving one via env.
    """

    repo_full_name: str
    issue_number: int
    installation_id: int
    run_id: str
    branch: str
    event_kind: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RunConfig:
        source = env if env is not None else os.environ

        missing = [name for name in _REQUIRED_VARS if not source.get(name)]
        if missing:
            raise ConfigError(
                f"Missing required run-config environment variable(s): {', '.join(missing)}"
            )

        repo_full_name = source["REPO_FULL_NAME"]
        if "/" not in repo_full_name:
            raise ConfigError(
                f"REPO_FULL_NAME must be in 'owner/repo' form, got: {repo_full_name!r}"
            )

        try:
            issue_number = int(source["ISSUE_NUMBER"])
        except ValueError as exc:
            raise ConfigError(
                f"ISSUE_NUMBER must be an integer, got: {source['ISSUE_NUMBER']!r}"
            ) from exc

        try:
            installation_id = int(source["INSTALLATION_ID"])
        except ValueError as exc:
            raise ConfigError(
                f"INSTALLATION_ID must be an integer, got: {source['INSTALLATION_ID']!r}"
            ) from exc

        return cls(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            installation_id=installation_id,
            run_id=source["RUN_ID"],
            branch=source["BRANCH"],
            event_kind=source["EVENT_KIND"],
        )
