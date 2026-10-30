"""Provider-agnostic LLM layer.

Public surface: the base types/protocol (what the M4b agent loop depends on),
the concrete providers, and the factory that selects one from config.
"""

from __future__ import annotations

from it2pr_worker.llm.anthropic import AnthropicProvider, ModelPrice
from it2pr_worker.llm.base import (
    LLMResponse,
    Message,
    Provider,
    ToolCall,
    ToolSpec,
    Usage,
)
from it2pr_worker.llm.factory import FactoryConfigError, build_provider
from it2pr_worker.llm.openai_compatible import OpenAICompatibleProvider
from it2pr_worker.llm.openrouter import OpenRouterProvider

__all__ = [
    "Message",
    "ToolSpec",
    "ToolCall",
    "Usage",
    "LLMResponse",
    "Provider",
    "OpenRouterProvider",
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "ModelPrice",
    "build_provider",
    "FactoryConfigError",
]
