"""Node language adapter: pnpm/yarn/npm install, package.json test script, c8 coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path

from it2pr_worker.adapters.base import (
    CoverageToolAbsentError,
    Runner,
    TestResult,
    default_runner,
)

_COVERAGE_PCT_RE = re.compile(r"All files\s*\|\s*([\d.]+)")


class NodeAdapter:
    name = "node"

    def detect(self, repo_dir: Path) -> bool:
        return (repo_dir / "package.json").exists()

    def _package_manager(self, repo_dir: Path) -> str:
        if (repo_dir / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (repo_dir / "yarn.lock").exists():
            return "yarn"
        return "npm"

    def install(self, repo_dir: Path, *, runner: Runner = default_runner) -> None:
        pm = self._package_manager(repo_dir)
        if pm == "npm":
            argv = ["npm", "ci", "--prefix", str(repo_dir)]
        else:
            argv = [pm, "install", "--dir", str(repo_dir)]
        runner(argv)

    def _has_test_script(self, repo_dir: Path) -> bool:
        package_json = repo_dir / "package.json"
        if not package_json.exists():
            return False
        try:
            data = json.loads(package_json.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        return bool(data.get("scripts", {}).get("test"))

    def test_command(self, repo_dir: Path) -> list[str]:
        pm = self._package_manager(repo_dir)
        if pm == "npm":
            return ["npm", "test", "--prefix", str(repo_dir)]
        return [pm, "test", "--dir", str(repo_dir)]

    def run_tests(self, repo_dir: Path, *, runner: Runner = default_runner) -> TestResult:
        result = runner(self.test_command(repo_dir))
        output = (result.stdout or "") + (result.stderr or "")
        return TestResult(passed=result.returncode == 0, output_tail=output[-4000:])

    def coverage(self, repo_dir: Path, *, runner: Runner = default_runner) -> float | None:
        pm = self._package_manager(repo_dir)
        if pm == "npm":
            argv = ["npx", "c8", "--reporter=text", "npm", "test", "--prefix", str(repo_dir)]
        else:
            argv = ["npx", "c8", "--reporter=text", pm, "test", "--dir", str(repo_dir)]

        result = runner(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 and (
            "command not found" in combined.lower() or "not found" in combined.lower()
        ):
            raise CoverageToolAbsentError("c8 not available in repo environment")

        return self._parse_coverage_percent(combined)

    @staticmethod
    def _parse_coverage_percent(output: str) -> float | None:
        match = _COVERAGE_PCT_RE.search(output)
        if not match:
            return None
        return float(match.group(1))
