from __future__ import annotations

import pytest

from it2pr_worker.llm.anthropic import AnthropicProvider
from it2pr_worker.llm.factory import FactoryConfigError, build_provider
from it2pr_worker.llm.openai_compatible import OpenAICompatibleProvider
from it2pr_worker.llm.openrouter import OpenRouterProvider


def test_selects_openrouter_by_default() -> None:
    config = {"LLM_MODEL": "anthropic/claude-3.5-sonnet", "OPENROUTER_API_KEY": "sk-or-x"}

    provider = build_provider(config)

    assert isinstance(provider, OpenRouterProvider)
    assert provider.model == "anthropic/claude-3.5-sonnet"
    assert provider.api_key == "sk-or-x"


def test_selects_openrouter_explicitly() -> None:
    config = {
        "LLM_PROVIDER": "openrouter",
        "LLM_MODEL": "openai/gpt-4o",
        "OPENROUTER_API_KEY": "sk-or-x",
    }

    provider = build_provider(config)

    assert isinstance(provider, OpenRouterProvider)


def test_selects_openai_compatible() -> None:
    config = {
        "LLM_PROVIDER": "openai-compatible",
        "LLM_MODEL": "deepseek-chat",
        "LLM_BASE_URL": "https://api.deepseek.com/v1",
        "OPENAI_API_KEY": "sk-deepseek-x",
    }

    provider = build_provider(config)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.deepseek.com/v1"
    assert provider.model == "deepseek-chat"


def test_selects_anthropic() -> None:
    config = {
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": "claude-3-5-sonnet-20241022",
        "ANTHROPIC_API_KEY": "sk-ant-x",
    }

    provider = build_provider(config)

    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-3-5-sonnet-20241022"


def test_missing_model_raises() -> None:
    config = {"OPENROUTER_API_KEY": "sk-or-x"}

    with pytest.raises(FactoryConfigError, match="LLM_MODEL"):
        build_provider(config)


def test_missing_api_key_raises() -> None:
    config = {"LLM_PROVIDER": "openrouter", "LLM_MODEL": "openai/gpt-4o"}

    with pytest.raises(FactoryConfigError, match="OPENROUTER_API_KEY"):
        build_provider(config)


def test_openai_compatible_missing_base_url_raises() -> None:
    config = {
        "LLM_PROVIDER": "openai-compatible",
        "LLM_MODEL": "deepseek-chat",
        "OPENAI_API_KEY": "sk-x",
    }

    with pytest.raises(FactoryConfigError, match="LLM_BASE_URL"):
        build_provider(config)


def test_unknown_provider_raises() -> None:
    config = {"LLM_PROVIDER": "bedrock", "LLM_MODEL": "whatever"}

    with pytest.raises(FactoryConfigError, match="Unknown LLM_PROVIDER"):
        build_provider(config)
