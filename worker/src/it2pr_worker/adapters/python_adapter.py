"""Python language adapter: uv/pip install, pytest, coverage.py."""

from __future__ import annotations

import re
from pathlib import Path

from it2pr_worker.adapters.base import (
    CoverageToolAbsentError,
    Runner,
    TestResult,
    default_runner,
)

_COVERAGE_PCT_RE = re.compile(r"TOTAL\s+.*?(\d+(?:\.\d+)?)%\s*$", re.MULTILINE)


class PythonAdapter:
    name = "python"

    def detect(self, repo_dir: Path) -> bool:
        return any(
            (repo_dir / marker).exists()
            for marker in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")
        )

    def _use_uv(self, repo_dir: Path) -> bool:
        return (repo_dir / "uv.lock").exists() or (repo_dir / "pyproject.toml").exists()

    def install(self, repo_dir: Path, *, runner: Runner = default_runner) -> None:
        if self._use_uv(repo_dir):
            runner(["uv", "sync", "--directory", str(repo_dir)])
        else:
            runner(["pip", "install", "-r", str(repo_dir / "requirements.txt")])

    def test_command(self, repo_dir: Path) -> list[str]:
        if self._use_uv(repo_dir):
            return ["uv", "run", "--directory", str(repo_dir), "pytest", "-q"]
        return ["pytest", "-q"]

    def run_tests(self, repo_dir: Path, *, runner: Runner = default_runner) -> TestResult:
        result = runner(self.test_command(repo_dir))
        output = (result.stdout or "") + (result.stderr or "")
        return TestResult(passed=result.returncode == 0, output_tail=output[-4000:])

    def coverage(self, repo_dir: Path, *, runner: Runner = default_runner) -> float | None:
        if self._use_uv(repo_dir):
            run_argv = [
                "uv",
                "run",
                "--directory",
                str(repo_dir),
                "coverage",
                "run",
                "-m",
                "pytest",
                "-q",
            ]
            report_argv = ["uv", "run", "--directory", str(repo_dir), "coverage", "report"]
        else:
            run_argv = ["coverage", "run", "-m", "pytest", "-q"]
            report_argv = ["coverage", "report"]

        run_result = runner(run_argv)
        combined = (run_result.stdout or "") + (run_result.stderr or "")
        if run_result.returncode != 0 and (
            "No module named coverage" in combined or "not found" in combined.lower()
        ):
            raise CoverageToolAbsentError("coverage.py not available in repo environment")

        report_result = runner(report_argv)
        report_output = (report_result.stdout or "") + (report_result.stderr or "")
        if report_result.returncode != 0 and (
            "No module named coverage" in report_output
            or "not found" in report_output.lower()
        ):
            raise CoverageToolAbsentError("coverage.py not available in repo environment")

        return self._parse_coverage_percent(report_output)

    @staticmethod
    def _parse_coverage_percent(report_output: str) -> float | None:
        match = _COVERAGE_PCT_RE.search(report_output)
        if not match:
            return None
        return float(match.group(1))
