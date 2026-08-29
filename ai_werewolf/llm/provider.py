"""LLM provider abstraction.

AI狼人杀 never hard-codes a vendor. A *provider* is anything that can turn a
list of chat messages into a string of text. The default implementation speaks
the OpenAI ``/chat/completions`` dialect, which every major endpoint — OpenAI,
DeepSeek, Xiaomi MiMo, Groq, OpenRouter, local servers — exposes. Swap
providers by changing one environment variable.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

# Known OpenAI-compatible endpoints. Pick one with AIWEREWOLF_PROVIDER, or set
# AIWEREWOLF_BASE_URL directly for anything else.
PRESETS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.xiaomimimo.com/v1",
    "mimo-token-plan": "https://token-plan-cn.xiaomimimo.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class LLMError(RuntimeError):
    """Raised when a provider cannot return a completion."""


@dataclass
class LLMConfig:
    """Connection settings for an OpenAI-compatible endpoint."""

    base_url: str
    api_key: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 600
    timeout: float = 60.0

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env") -> LLMConfig:
        """Build a config from environment variables.

        Reads ``AIWEREWOLF_API_KEY``, ``AIWEREWOLF_MODEL`` and either
        ``AIWEREWOLF_BASE_URL`` or ``AIWEREWOLF_PROVIDER`` (a key of
        :data:`PRESETS`). A ``.env`` file in the working directory is loaded
        first if present.
        """
        if env_file is not None:
            _load_dotenv(Path(env_file))

        api_key = os.environ.get("AIWEREWOLF_API_KEY", "")
        model = os.environ.get("AIWEREWOLF_MODEL", "")
        base_url = os.environ.get("AIWEREWOLF_BASE_URL", "")
        provider = os.environ.get("AIWEREWOLF_PROVIDER", "")

        if not base_url and provider:
            if provider not in PRESETS:
                raise LLMError(
                    f"unknown AIWEREWOLF_PROVIDER {provider!r}; "
                    f"known: {', '.join(sorted(PRESETS))}"
                )
            base_url = PRESETS[provider]
        if not (base_url and api_key and model):
            raise LLMError(
                "missing LLM config: set AIWEREWOLF_API_KEY, AIWEREWOLF_MODEL and "
                "AIWEREWOLF_BASE_URL (or AIWEREWOLF_PROVIDER). See .env.example."
            )
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            temperature=float(os.environ.get("AIWEREWOLF_TEMPERATURE", 0.8)),
            max_tokens=int(os.environ.get("AIWEREWOLF_MAX_TOKENS", 600)),
        )


class LLMProvider(ABC):
    """Anything that can answer a chat completion."""

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the assistant's reply to ``messages`` as plain text."""


class OpenAICompatProvider(LLMProvider):
    """Calls any endpoint that implements OpenAI ``/chat/completions``."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete(self, messages: list[dict[str, str]]) -> str:
        import httpx  # imported lazily so the mock path needs no dependency

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        try:
            resp = httpx.post(
                f"{self.config.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.config.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"{exc.response.status_code} from {self.config.base_url}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"provider call failed: {exc}") from exc


def _load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader — ``KEY=VALUE`` lines, existing vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
