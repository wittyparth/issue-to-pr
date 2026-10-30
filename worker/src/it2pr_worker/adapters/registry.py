"""Select the appropriate language adapter for a repo, or fast-fail.

Unsupported-repo fast-fail (pre-mortem #1): if neither Python nor Node is
detected, return a structured InferenceFailure. Posting the issue comment
for this failure is wired in M5; here we only produce the structured result.
"""

from __future__ import annotations

from pathlib import Path

from it2pr_worker.adapters.base import (
    InferenceFailure,
    InferenceFailureReason,
    LanguageAdapter,
)
from it2pr_worker.adapters.node_adapter import NodeAdapter
from it2pr_worker.adapters.python_adapter import PythonAdapter


def select_adapter(repo_dir: Path) -> LanguageAdapter | InferenceFailure:
    adapters: list[LanguageAdapter] = [PythonAdapter(), NodeAdapter()]
    for adapter in adapters:
        if adapter.detect(repo_dir):
            return adapter
    return InferenceFailure(
        reason=InferenceFailureReason.UNSUPPORTED_REPO,
        detail=f"No supported language toolchain detected in {repo_dir}",
    )
