"""Provider-agnostic agent loop, tool surface, and hard caps (M4b).

The loop (`run_agent`) depends only on `it2pr_worker.llm`'s `Provider` boundary
and the M3 `LanguageAdapter`, never on a concrete provider. All process/file
access is injectable so tests run hermetically (no network/git/subprocess/sleep).
"""

from __future__ import annotations

from .limits import LimitKind, LimitStatus, LimitTracker
from .loop import AgentResult, AgentStatus, run_agent
from .tools import (
    Filesystem,
    PathRejected,
    RealFilesystem,
    ToolContext,
    ToolResult,
    apply_patch,
    build_toolset,
    dispatch,
    edit_file,
    finish,
    read_file,
    repo_map,
    ripgrep_search,
    run_tests,
)

__all__ = [
    "AgentResult",
    "AgentStatus",
    "run_agent",
    "LimitKind",
    "LimitStatus",
    "LimitTracker",
    "ToolContext",
    "ToolResult",
    "Filesystem",
    "RealFilesystem",
    "PathRejected",
    "build_toolset",
    "dispatch",
    "ripgrep_search",
    "repo_map",
    "read_file",
    "edit_file",
    "apply_patch",
    "run_tests",
    "finish",
]
