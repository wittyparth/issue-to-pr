"""CLI entrypoint for the eval harness.

`--dry-run` renders a demonstrative `REPORT.md` from a built-in fake trigger
with representative outcomes, so the report artifact exists without needing
the deployed AWS control plane. A real run requires `--config` pointing at a
reproducibility-pinned config and a live `HttpTrigger` (not yet wired to a
CLI flag — see runner.HttpTrigger for the real trigger).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from it2pr_eval.config import DEFAULT_CONFIG, EvalConfig
from it2pr_eval.fixtures import SeedIssue, load_seed_issues
from it2pr_eval.report import write_report
from it2pr_eval.runner import RunOutcome, run_eval


@dataclass
class _SampleTrigger:
    """Deterministic fake trigger used for `--dry-run` demonstration reports."""

    def run(self, issue: SeedIssue) -> RunOutcome:
        # Deterministic-but-varied sample data keyed on issue id so --dry-run
        # output looks like a real, mixed-outcome report.
        seed = sum(ord(c) for c in issue.id)
        passed = seed % 3 != 0
        return RunOutcome(
            issue_id=issue.id,
            passed=passed,
            cost_usd=round(0.5 + (seed % 7) * 0.35, 2),
            time_to_first_action_s=float(5 + seed % 20),
            time_to_pr_s=float(120 + seed % 600),
            pr_url=f"https://github.com/{issue.repo}/pull/{issue.issue_number}"
            if passed
            else None,
            notes="sample dry-run outcome" if passed else "sample dry-run failure",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="it2pr_eval", description="Issue-to-PR eval harness")
    parser.add_argument("--config", type=str, default=None, help="Path to a JSON/TOML config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render a demonstrative report using a built-in fake trigger (no infra required)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="REPORT.md",
        help="Path to write the report to (relative to the eval/ package directory)",
    )
    args = parser.parse_args(argv)

    config = EvalConfig.from_file(args.config) if args.config else DEFAULT_CONFIG
    issues = load_seed_issues()

    if args.dry_run:
        trigger = _SampleTrigger()
    else:
        raise SystemExit(
            "A live run requires a configured HttpTrigger against deployed infra; "
            "use --dry-run to generate a demonstrative report without infra."
        )

    eval_run = run_eval(config, issues, trigger, concurrency=1)
    write_report(eval_run, config, path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
