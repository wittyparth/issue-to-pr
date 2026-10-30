# Issue-to-PR Eval Report

Model: `anthropic/claude-sonnet-4-20250514` · Temperature: `0.0` · Prompt version: `issue-to-pr-v1`

## Per-Issue Results

| Issue | Language | Difficulty | Result | Cost | Time-to-first-action | Time-to-PR |
|---|---|---|---|---|---|---|
| node-easy-01 | node | easy | PASS | $0.50 | 8.0s | 563.0s |
| node-easy-02 | node | easy | FAIL | $0.85 | 9.0s | 564.0s |
| node-hard-01 | node | hard | PASS | $1.20 | 9.0s | 544.0s |
| node-hard-02 | node | hard | PASS | $1.55 | 10.0s | 545.0s |
| node-med-01 | node | med | PASS | $1.20 | 24.0s | 439.0s |
| node-med-02 | node | med | PASS | $1.55 | 5.0s | 440.0s |
| py-easy-01 | python | easy | PASS | $0.50 | 19.0s | 374.0s |
| py-easy-02 | python | easy | FAIL | $0.85 | 20.0s | 375.0s |
| py-hard-01 | python | hard | PASS | $1.20 | 20.0s | 355.0s |
| py-hard-02 | python | hard | PASS | $1.55 | 21.0s | 356.0s |
| py-med-01 | python | med | PASS | $1.20 | 15.0s | 250.0s |
| py-med-02 | python | med | PASS | $1.55 | 16.0s | 251.0s |

## Summary

- Pass rate: 10/12 (floor: 8) — **PASS**
- Total cost: $13.70
- Mean cost per PR: $1.14
- p50 time-to-PR: 407.0s
- Raw time-to-PR distribution (s): 250.0s, 251.0s, 355.0s, 356.0s, 374.0s, 375.0s, 439.0s, 440.0s, 544.0s, 545.0s, 563.0s, 564.0s
- Mean time-to-first-action: 14.7s

## Comparison

- vs Cursor Background Agents: _placeholder — fill in after a live run on shared issues (pass rate, cost/PR, time-to-PR for Cursor Background Agents vs this harness at model=anthropic/claude-sonnet-4-20250514, prompt=issue-to-pr-v1)._
