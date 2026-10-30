# Issue-to-PR — common tasks. Run `just` to list.
set shell := ["bash", "-uc"]

default:
    @just --list

# Install all JS + Python deps
install:
    pnpm install
    uv sync --directory worker
    uv sync --directory eval

# Typecheck TS packages
typecheck:
    pnpm -r typecheck

# Lint everything
lint:
    pnpm -r lint
    uv run --directory worker ruff check .
    uv run --directory eval ruff check .

# Run all tests (TS + Python)
test:
    pnpm -r test
    uv run --directory worker pytest -q
    uv run --directory eval pytest -q

# Synthesize the CDK stack
synth:
    pnpm --filter @it2pr/infra synth

# Full local gate (what CI runs)
ci: typecheck lint test synth
