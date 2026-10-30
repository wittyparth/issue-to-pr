"""Select and construct a concrete `Provider` from run configuration.

Config source for now is environment variables (api keys come from Secrets
Manager in prod — handled later, out of scope for M4a):
  - LLM_PROVIDER: "openrouter" (default) | "openai-compatible" | "anthropic"
  - LLM_MODEL: model identifier (required)
  - LLM_BASE_URL: required only for "openai-compatible"
  - API key: OPENROUTER_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY
             (selected by provider)
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from it2pr_worker.llm.anthropic import AnthropicProvider
from it2pr_worker.llm.base import Provider
from it2pr_worker.llm.openai_compatible import OpenAICompatibleProvider
from it2pr_worker.llm.openrouter import OpenRouterProvider

__all__ = ["FactoryConfigError", "build_provider"]

_DEFAULT_PROVIDER = "openrouter"


class FactoryConfigError(ValueError):
    """Raised when required LLM configuration is missing or invalid."""


def build_provider(
    config: Mapping[str, str] | None = None,
    *,
    http: httpx.Client | None = None,
) -> Provider:
    """Build the configured `Provider`. `config` defaults to `os.environ`."""
    source = config if config is not None else os.environ
    client = http if http is not None else httpx.Client()

    provider_name = source.get("LLM_PROVIDER", _DEFAULT_PROVIDER).strip().lower()
    model = source.get("LLM_MODEL")
    if not model:
        raise FactoryConfigError("LLM_MODEL is required")

    if provider_name == "openrouter":
        api_key = _require(source, "OPENROUTER_API_KEY")
        return OpenRouterProvider(model=model, api_key=api_key, http=client)

    if provider_name == "openai-compatible":
        api_key = _require(source, "OPENAI_API_KEY")
        base_url = source.get("LLM_BASE_URL")
        if not base_url:
            raise FactoryConfigError("LLM_BASE_URL is required for openai-compatible provider")
        return OpenAICompatibleProvider(
            base_url=base_url, model=model, api_key=api_key, http=client
        )

    if provider_name == "anthropic":
        api_key = _require(source, "ANTHROPIC_API_KEY")
        return AnthropicProvider(model=model, api_key=api_key, http=client)

    raise FactoryConfigError(f"Unknown LLM_PROVIDER: {provider_name!r}")


def _require(source: Mapping[str, str], key: str) -> str:
    value = source.get(key)
    if not value:
        raise FactoryConfigError(f"{key} is required")
    return value
