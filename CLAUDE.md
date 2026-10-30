# OMC Workflow Guide

Command/agent cheat sheet for this project. Use per phase.

## Setup / health
- `/oh-my-claudecode:omc-setup` — install/repair/update OMC config
- `/oh-my-claudecode:omc-doctor` — diagnose install issues
- `/oh-my-claudecode:mcp-setup` — add/configure MCP servers

## 1. Requirements & brainstorming (before touching code)
- `superpowers:brainstorming` (auto-triggers on creative/feature work)
- `oh-my-claudecode:deep-interview` — Socratic requirements gathering, gates on ambiguity
- `oh-my-claudecode:analyst` agent — requirements/pre-planning consult

## 2. Architecture & planning
- `oh-my-claudecode:architect` agent (Opus, read-only) — strategic design/debugging advisor
- `/oh-my-claudecode:plan` — planning skill, optional interview mode
- `superpowers:writing-plans` — turn a spec into a concrete stepped plan file
- `/oh-my-claudecode:ralplan` — consensus gate before big `/team`/`/autopilot` runs

## 3. Execution
- `/oh-my-claudecode:autopilot` — full autonomous idea-to-code for a well-scoped task
- `/oh-my-claudecode:team` — N agents on one shared task list, real parallelism
- `superpowers:subagent-driven-development` — dispatch independent plan-tasks to subagents
- `/oh-my-claudecode:ultragoal` — durable multi-goal plan+ledger, survives session restarts
- `/oh-my-claudecode:ultrawork` — high-throughput parallel execution (heavy, large batches only)
- `superpowers:test-driven-development` — auto-triggers, write test first
- `superpowers:using-git-worktrees` — isolate feature work in its own worktree

## 4. Tracking
- native `TaskCreate` / `TaskList` / `TaskUpdate` / `TaskGet` — per-session task board
- `.omc/plans`, `.omc/research`, `.omc/handoffs` — auto-persisted artifacts
- `/oh-my-claudecode:wiki` — durable markdown knowledge base, query before decisions, write after
- `/oh-my-claudecode:project-session-manager` — worktree-based session manager tied to issues/PRs

## 5. Debugging
- `superpowers:systematic-debugging` — auto-triggers on any bug/failure
- `oh-my-claudecode:debugger` or `oh-my-claudecode:tracer` agent — root cause

## 6. Review / quality gate (never self-approve)
- `/code-review [low|medium|high|xhigh|max|ultra]` — correctness + cleanup review of diff
- `/security-review` — OWASP-style pass on pending changes
- `superpowers:requesting-code-review` / `receiving-code-review` — review protocol
- `/simplify` — reuse/efficiency cleanup pass (not bug-hunting)
- `/oh-my-claudecode:merge-readiness` — final gate before calling a task done
- `/verify` — actually run the app and confirm behavior, not just tests

## 7. Finishing
- `superpowers:finishing-a-development-branch` — decide merge/PR/cleanup once done and green
- `/oh-my-claudecode:release` — release-rule-aware release assistant

## Token/cost control (already configured)
- `~/.claude/.omc-config.json`: `defaultExecutionMode: ""` — no auto multi-agent burn on generic words, trigger modes explicitly
- `~/.config/claude-omc/config.jsonc` — per-agent haiku overrides for cheap agents (qa-tester, git-master, document-specialist)
- Lean MCP set: context7, exa, lyzr, OMC bridge only (filesystem/github MCP removed — redundant/broken)
- No playwright — heavy token cost, not enabled

## Typical big-feature flow
`brainstorming`/`deep-interview` → `architect` + you → `writing-plans`/`plan` → `ralplan` gate →
`ultragoal` (persist) + `team`/`autopilot` (execute) with `TaskCreate` tracking →
`test-driven-development` throughout → `code-review high` + `security-review` → `verify` →
`merge-readiness` → `finishing-a-development-branch`.
