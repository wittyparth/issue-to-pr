"""Agent tool surface (M4, D1 mini-swe-agent-style loop).

Each tool provides (a) a `ToolSpec` (name/description/JSON-schema params) offered
to the model and (b) an implementation taking parsed arguments plus an injectable
`ToolContext` (repo_dir, runner, adapter). `build_toolset()` returns the list of
specs; `dispatch()` routes a `ToolCall` to the right impl.

CRITICAL SECURITY GUARD (Principle 1, plan M4): the diff/edit allow-list rejects
any write whose path escapes `repo_dir` OR lands under `.github/workflows/`. The
guard is enforced centrally in `dispatch()` (defense in depth: also in the write
impls) so no routing path can bypass it. A rejection returns a visible tool error
and MUST NOT modify the file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from it2pr_worker.adapters.base import LanguageAdapter, Runner, default_runner
from it2pr_worker.llm.base import ToolCall, ToolSpec

# Path prefixes (relative to repo root, lowercased) the agent may never write.
# - .github/workflows: editing CI config is the classic "force the build green"
#   attack.
# - .git: writing .git/hooks/* or .git/config (core.hooksPath/fsmonitor) yields
#   arbitrary code execution on the next git operation — a bypass of the CI guard.
_FORBIDDEN_PREFIXES: tuple[tuple[str, ...], ...] = ((".github", "workflows"), (".git",))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of a tool invocation, surfaced back to the model."""

    ok: bool
    content: str


# --- filesystem boundary ---------------------------------------------------


@runtime_checkable
class Filesystem(Protocol):
    """Narrow file boundary so tests can inject an in-memory fs if desired.

    The default is `RealFilesystem`, which operates on disk under `repo_dir`.
    """

    def read_text(self, path: Path) -> str: ...

    def write_text(self, path: Path, content: str) -> None: ...

    def exists(self, path: Path) -> bool: ...

    def walk(self, root: Path) -> list[Path]: ...


class RealFilesystem:
    """On-disk `Filesystem` implementation."""

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def exists(self, path: Path) -> bool:
        return path.exists()

    def walk(self, root: Path) -> list[Path]:
        return [p for p in sorted(root.rglob("*")) if p.is_file()]


@dataclass(slots=True)
class ToolContext:
    """Injectable dependencies for tool execution.

    `runner` runs external processes (ripgrep etc.); tests inject a fake so no
    real subprocess is spawned. `adapter` delegates `run_tests` to M3. `fs`
    defaults to `RealFilesystem` when not provided.
    """

    repo_dir: Path
    runner: Runner = default_runner
    adapter: LanguageAdapter | None = None
    fs: Filesystem | None = None


# --- path safety / allow-list ---------------------------------------------


class PathRejected(Exception):
    """Raised when a path escapes repo_dir or hits the CI allow-list."""


def _resolve_within_repo(repo_dir: Path, rel: str) -> Path:
    """Resolve `rel` under `repo_dir`, rejecting traversal outside it."""
    repo_root = repo_dir.resolve()
    candidate = (repo_root / rel).resolve()
    if candidate != repo_root and repo_root not in candidate.parents:
        raise PathRejected(f"path escapes repo_dir: {rel!r}")
    return candidate


def _reject_if_disallowed_write(repo_dir: Path, rel: str) -> Path:
    """Resolve a write target, rejecting traversal and `.github/workflows/**`.

    This is the non-negotiable safety guard. Returns the resolved path on
    success; raises `PathRejected` (never writes) on violation.
    """
    resolved = _resolve_within_repo(repo_dir, rel)
    repo_root = repo_dir.resolve()
    # Compare case-insensitively: on case-insensitive filesystems (macOS/Windows)
    # `.github/Workflows/` resolves to the same dir Actions reads, so a
    # case-sensitive check would be bypassable.
    parts = tuple(p.lower() for p in resolved.relative_to(repo_root).parts)
    for prefix in _FORBIDDEN_PREFIXES:
        if parts[: len(prefix)] == prefix:
            raise PathRejected(f"writes under {'/'.join(prefix)}/ are forbidden (allow-list)")
    return resolved


# --- tool implementations --------------------------------------------------


def ripgrep_search(pattern: str, path: str | None, ctx: ToolContext) -> ToolResult:
    """Search the repo with ripgrep via the injectable runner.

    Falls back gracefully to a visible message if `rg` is missing rather than
    crashing the loop.
    """
    target = path or "."
    try:
        _resolve_within_repo(ctx.repo_dir, target)
    except PathRejected as exc:
        return ToolResult(ok=False, content=str(exc))
    # `--no-config` disables user rg config; `--regexp <pat>` binds the pattern as
    # a value (not a positional that could be read as a flag like `-f`/`--pre`);
    # `--` stops flag parsing before the path. Prevents ripgrep argument injection
    # from the model-controlled pattern/path.
    argv: Sequence[str] = [
        "rg",
        "--no-config",
        "--line-number",
        "--no-heading",
        "--regexp",
        pattern,
        "--",
        target,
    ]
    try:
        result = ctx.runner(argv, cwd=ctx.repo_dir)
    except FileNotFoundError:
        return ToolResult(ok=False, content="ripgrep (rg) is not available")
    if result.returncode not in (0, 1):
        return ToolResult(ok=False, content=(result.stderr or "ripgrep failed").strip())
    matches = result.stdout.strip()
    if not matches:
        return ToolResult(ok=True, content="no matches")
    return ToolResult(ok=True, content=matches)


_REPO_MAP_EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def repo_map(ctx: ToolContext) -> ToolResult:
    """Compact listing of files in the repo (simple walk, no hard tree-sitter dep)."""
    fs = ctx.fs or RealFilesystem()
    repo_root = ctx.repo_dir.resolve()
    files = fs.walk(repo_root)
    rels = []
    for p in files:
        if _REPO_MAP_EXCLUDED_DIRS.intersection(p.parts):
            continue
        try:
            # A symlink (e.g. a venv's interpreter, a pnpm store link) can
            # resolve to a real path outside repo_root; skip it rather than
            # letting relative_to raise and abort the whole listing.
            rels.append(str(p.resolve().relative_to(repo_root)))
        except ValueError:
            continue
    if not rels:
        return ToolResult(ok=True, content="(empty repo)")
    return ToolResult(ok=True, content="\n".join(sorted(rels)))


def read_file(
    path: str, start: int | None, end: int | None, ctx: ToolContext
) -> ToolResult:
    """Read a file within repo_dir; rejects path traversal outside repo_dir."""
    fs = ctx.fs or RealFilesystem()
    try:
        resolved = _resolve_within_repo(ctx.repo_dir, path)
    except PathRejected as exc:
        return ToolResult(ok=False, content=str(exc))
    if not fs.exists(resolved):
        return ToolResult(ok=False, content=f"file not found: {path}")
    text = fs.read_text(resolved)
    if start is None and end is None:
        return ToolResult(ok=True, content=text)
    lines = text.splitlines()
    lo = (start - 1) if start else 0
    hi = end if end else len(lines)
    lo = max(lo, 0)
    return ToolResult(ok=True, content="\n".join(lines[lo:hi]))


def edit_file(path: str, old_str: str, new_str: str, ctx: ToolContext) -> ToolResult:
    """Replace `old_str` with `new_str` in a file, enforcing the allow-list.

    Rejects traversal and any write under `.github/workflows/` without touching
    the file.
    """
    fs = ctx.fs or RealFilesystem()
    try:
        resolved = _reject_if_disallowed_write(ctx.repo_dir, path)
    except PathRejected as exc:
        return ToolResult(ok=False, content=str(exc))
    if not fs.exists(resolved):
        return ToolResult(ok=False, content=f"file not found: {path}")
    text = fs.read_text(resolved)
    if old_str not in text:
        return ToolResult(ok=False, content=f"old_str not found in {path}")
    fs.write_text(resolved, text.replace(old_str, new_str, 1))
    return ToolResult(ok=True, content=f"edited {path}")


def apply_patch(path: str, content: str, ctx: ToolContext) -> ToolResult:
    """Overwrite a file with `content`, enforcing the allow-list.

    Rejects traversal and any write under `.github/workflows/` without touching
    the file.
    """
    fs = ctx.fs or RealFilesystem()
    try:
        resolved = _reject_if_disallowed_write(ctx.repo_dir, path)
    except PathRejected as exc:
        return ToolResult(ok=False, content=str(exc))
    fs.write_text(resolved, content)
    return ToolResult(ok=True, content=f"wrote {path}")


def run_tests(ctx: ToolContext) -> ToolResult:
    """Delegate to the injected M3 `LanguageAdapter.run_tests`."""
    if ctx.adapter is None:
        return ToolResult(ok=False, content="no language adapter configured")
    result = ctx.adapter.run_tests(ctx.repo_dir, runner=ctx.runner)
    status = "passed" if result.passed else "failed"
    return ToolResult(ok=result.passed, content=f"tests {status}\n{result.output_tail}")


def finish(summary: str) -> ToolResult:
    """Terminal tool: the model calls this to end the loop with a rationale."""
    return ToolResult(ok=True, content=summary)


# --- tool specs ------------------------------------------------------------

FINISH_TOOL = "finish"


def build_toolset() -> list[ToolSpec]:
    """Return the JSON-schema `ToolSpec`s offered to the model."""
    return [
        ToolSpec(
            name="ripgrep_search",
            description="Search the repository for a regex pattern using ripgrep.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex to search for."},
                    "path": {
                        "type": "string",
                        "description": "Optional path within the repo to scope the search.",
                    },
                },
                "required": ["pattern"],
            },
        ),
        ToolSpec(
            name="repo_map",
            description="List the files in the repository as a compact tree.",
            parameters={"type": "object", "properties": {}},
        ),
        ToolSpec(
            name="read_file",
            description="Read a file within the repo, optionally a line range.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer", "description": "1-based start line."},
                    "end": {"type": "integer", "description": "Inclusive end line."},
                },
                "required": ["path"],
            },
        ),
        ToolSpec(
            name="edit_file",
            description=(
                "Replace old_str with new_str in a file. "
                "Writes under .github/workflows/ are forbidden."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"},
                },
                "required": ["path", "old_str", "new_str"],
            },
        ),
        ToolSpec(
            name="apply_patch",
            description=(
                "Overwrite a file with the given content. "
                "Writes under .github/workflows/ are forbidden."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        ToolSpec(
            name="run_tests",
            description="Run the repository's test suite and report pass/fail.",
            parameters={"type": "object", "properties": {}},
        ),
        ToolSpec(
            name=FINISH_TOOL,
            description="End the task, providing a summary of what was done and why.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                },
                "required": ["summary"],
            },
        ),
    ]


def dispatch(tool_call: ToolCall, ctx: ToolContext) -> ToolResult:
    """Route a `ToolCall` to its implementation, enforcing the allow-list centrally.

    Unknown tools and malformed arguments return a visible tool error rather than
    raising, so the model can react.
    """
    name = tool_call.name
    args = tool_call.arguments or {}
    try:
        if name == "ripgrep_search":
            return ripgrep_search(args["pattern"], args.get("path"), ctx)
        if name == "repo_map":
            return repo_map(ctx)
        if name == "read_file":
            return read_file(args["path"], args.get("start"), args.get("end"), ctx)
        if name == "edit_file":
            # Central allow-list enforcement (defense in depth; impl re-checks).
            try:
                _reject_if_disallowed_write(ctx.repo_dir, args["path"])
            except PathRejected as exc:
                return ToolResult(ok=False, content=str(exc))
            return edit_file(args["path"], args["old_str"], args["new_str"], ctx)
        if name == "apply_patch":
            try:
                _reject_if_disallowed_write(ctx.repo_dir, args["path"])
            except PathRejected as exc:
                return ToolResult(ok=False, content=str(exc))
            return apply_patch(args["path"], args["content"], ctx)
        if name == "run_tests":
            return run_tests(ctx)
        if name == FINISH_TOOL:
            return finish(args.get("summary", ""))
    except KeyError as exc:
        return ToolResult(ok=False, content=f"missing argument: {exc}")
    return ToolResult(ok=False, content=f"unknown tool: {name}")
