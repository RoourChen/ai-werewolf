"""Model providers.

A :class:`Provider` turns a structured :class:`Prompt` into a text reply. The
default implementation speaks the OpenAI ``/chat/completions`` dialect (which
OpenAI, DeepSeek, MiMo, Groq, OpenRouter and most local servers expose), and
:class:`MockProvider` answers offline and deterministically for tests and CI.

Unlike ad-hoc string trailers, the offline hint travels as a first-class
``Prompt.hint`` field, which real providers simply ignore.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

PRESETS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mimo": "https://api.xiaomimimo.com/v1",
    "mimo-token-plan": "https://token-plan-cn.xiaomimimo.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class ProviderError(RuntimeError):
    """Raised when a provider cannot return a completion."""


@dataclass
class Prompt:
    """A chat turn plus an optional offline hint."""

    system: str
    user: str
    hint: dict = field(default_factory=dict)


class Provider(ABC):
    """Anything that can answer a chat prompt with text."""

    @abstractmethod
    def complete(self, prompt: Prompt) -> str:
        """Return the assistant reply for ``prompt``."""


@dataclass
class ModelConfig:
    """Connection settings for an OpenAI-compatible endpoint."""

    base_url: str
    api_key: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 600
    timeout: float = 60.0

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env") -> ModelConfig:
        """Build a config from ``AIWEREWOLF_*`` environment variables."""
        if env_file is not None:
            _load_dotenv(Path(env_file))

        api_key = os.environ.get("AIWEREWOLF_API_KEY", "")
        model = os.environ.get("AIWEREWOLF_MODEL", "")
        base_url = os.environ.get("AIWEREWOLF_BASE_URL", "")
        preset = os.environ.get("AIWEREWOLF_PROVIDER", "")

        if not base_url and preset:
            if preset not in PRESETS:
                raise ProviderError(
                    f"unknown AIWEREWOLF_PROVIDER {preset!r}; "
                    f"known: {', '.join(sorted(PRESETS))}"
                )
            base_url = PRESETS[preset]
        if not (base_url and api_key and model):
            raise ProviderError(
                "missing model config: set AIWEREWOLF_API_KEY, AIWEREWOLF_MODEL and "
                "AIWEREWOLF_BASE_URL (or AIWEREWOLF_PROVIDER). See .env.example."
            )
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            temperature=float(os.environ.get("AIWEREWOLF_TEMPERATURE", 0.8)),
            max_tokens=int(os.environ.get("AIWEREWOLF_MAX_TOKENS", 600)),
        )


class OpenAICompatProvider(Provider):
    """Calls any endpoint that implements OpenAI ``/chat/completions``."""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def complete(self, prompt: Prompt) -> str:
        import httpx  # imported lazily so the offline path needs no dependency

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
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
            raise ProviderError(
                f"{exc.response.status_code} from {self.config.base_url}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"provider call failed: {exc}") from exc


def _load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader — ``KEY=VALUE`` lines, existing vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
