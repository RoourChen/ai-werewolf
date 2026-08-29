"""AI/LLM adapter layer: providers, the offline mock and prompt personas."""

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.persona import build_prompt
from ai_werewolf.ai.provider import (
    PRESETS,
    ModelConfig,
    OpenAICompatProvider,
    Prompt,
    Provider,
    ProviderError,
)

__all__ = [
    "MockProvider",
    "build_prompt",
    "PRESETS",
    "ModelConfig",
    "OpenAICompatProvider",
    "Prompt",
    "Provider",
    "ProviderError",
]
