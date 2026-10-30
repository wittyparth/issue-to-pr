# it2pr-worker base image (M3 manifest): pinned Python + Node toolchains plus
# the env-inference/test/coverage tools the adapters shell out to. Built and
# pushed by scripts/build-and-push-worker.sh AFTER `cdk deploy` creates the
# ECR repository (see README "Deploy" section) — this image is never built at
# `cdk synth`/`cdk deploy` time (no Docker available there).
FROM python:3.12-slim

# --- OS-level toolchain: git, curl, ripgrep, ca-certificates, Node.js 20 ---
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ripgrep \
        ca-certificates \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Node package managers: corepack (pnpm) + c8 for JS/TS coverage ---
RUN corepack enable \
    && corepack prepare pnpm@9 --activate \
    && npm install -g c8@10

# --- uv: fast Python installer/resolver, also used to `uv sync` the worker ---
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# --- Python coverage tool for the PythonAdapter's coverage runs ---
RUN pip install --no-cache-dir coverage==7.6.*

WORKDIR /app/worker

# Build context is the worker/ directory (see scripts/build-and-push-worker.sh:
# `docker build -t <repo>:latest worker/`).
# Install worker dependencies first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the worker package itself and sync it in (installs the
# `it2pr-worker` console script into the project venv).
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/worker/.venv/bin:${PATH}"

ENTRYPOINT ["python", "-m", "it2pr_worker"]
