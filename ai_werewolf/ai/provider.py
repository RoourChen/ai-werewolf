"""Model providers.

A :class:`Provider` turns a structured :class:`Prompt` into a text reply. The
default implementation speaks the OpenAI ``/chat/completions`` dialect (which
OpenAI, DeepSeek, MiMo, Groq, OpenRouter and most local servers expose), and
:class:`MockProvider` answers offline and deterministically for tests and CI.

The real provider records per-call latency and token usage into a
:class:`ModelRunStats` so a finished game can report the actual provider and
model, cost and latency percentiles — without ever exposing the API key.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

PRESETS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "mimo": "https://api.xiaomimimo.com/v1",
    "mimo-token-plan": "https://token-plan-cn.xiaomimimo.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

#: Estimated price in RMB per 1K tokens (configurable later; DeepSeek-like).
INPUT_PRICE_PER_1K = 0.001
OUTPUT_PRICE_PER_1K = 0.002
COST_ANOMALY_THRESHOLD = 2.0  # RMB, flag as anomaly


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
    max_tokens: int = 1200
    timeout: float = 20.0
    thinking: bool = False
    response_format: dict | None = None

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
        json_mode = os.environ.get("AIWEREWOLF_JSON_MODE", "1") not in ("0", "false", "no")
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            temperature=float(os.environ.get("AIWEREWOLF_TEMPERATURE", 0.8)),
            max_tokens=int(os.environ.get("AIWEREWOLF_MAX_TOKENS", 1200)),
            timeout=float(os.environ.get("AIWEREWOLF_TIMEOUT", 20.0)),
            thinking=os.environ.get("AIWEREWOLF_THINKING", "0") in ("1", "true", "yes"),
            response_format={"type": "json_object"} if json_mode else None,
        )


@dataclass
class ModelRunStats:
    """Aggregated latency / usage / failure stats for one model run (no key)."""

    provider: str = "mock"
    model: str = ""
    calls: int = 0
    retries: int = 0
    latency_ms: list[float] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failures: dict[str, int] = field(default_factory=dict)

    def record_success(self, latency_ms: float, prompt_tokens: int, completion_tokens: int) -> None:
        self.calls += 1
        self.latency_ms.append(round(latency_ms, 1))
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    def record_failure(self, kind: str) -> None:
        self.failures[kind] = self.failures.get(kind, 0) + 1

    def p50_ms(self) -> float:
        return _percentile(self.latency_ms, 50)

    def p95_ms(self) -> float:
        return _percentile(self.latency_ms, 95)

    def estimated_cost(self) -> float:
        return (
            self.prompt_tokens / 1000 * INPUT_PRICE_PER_1K
            + self.completion_tokens / 1000 * OUTPUT_PRICE_PER_1K
        )

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "calls": self.calls,
            "retries": self.retries,
            "p50_ms": self.p50_ms(),
            "p95_ms": self.p95_ms(),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost": round(self.estimated_cost(), 4),
            "failures": dict(self.failures),
        }


class OpenAICompatProvider(Provider):
    """Calls any endpoint that implements OpenAI ``/chat/completions``."""

    name = "openai-compatible"

    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.stats = ModelRunStats(provider=self.name, model=config.model)

    def complete(self, prompt: Prompt) -> str:
        import httpx  # imported lazily so the offline path needs no dependency

        payload: dict = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            # DeepSeek expects a ThinkingOptions struct, not a boolean.
            "thinking": {"type": "enabled" if self.config.thinking else "disabled"},
        }
        if self.config.response_format is not None:
            payload["response_format"] = self.config.response_format
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                start = time.perf_counter()
                resp = httpx.post(
                    f"{self.config.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout,
                )
                latency = (time.perf_counter() - start) * 1000.0
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                self.stats.record_success(
                    latency,
                    int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)),
                )
                return data["choices"][0]["message"]["content"] or ""
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 500
                if status >= 500 and attempt == 1:
                    self.stats.retries += 1
                    last_error = exc
                    continue
                self.stats.record_failure(f"http_{status}")
                raise ProviderError(
                    f"{status} from {self.config.base_url}: {_safe_text(exc)}"
                ) from exc
            except httpx.HTTPError as exc:
                self.stats.record_failure(type(exc).__name__)
                if attempt == 1:
                    self.stats.retries += 1
                    last_error = exc
                    continue
                raise ProviderError(f"provider call failed: {exc}") from exc
            except (KeyError, IndexError, ValueError) as exc:
                self.stats.record_failure("bad_response")
                raise ProviderError(f"provider call failed: {exc}") from exc
        raise ProviderError(f"provider call failed after retry: {last_error}")


def _safe_text(exc: object) -> str:
    try:
        response = getattr(exc, "response", None)
        return response.text[:200] if response is not None else str(exc)
    except Exception:  # noqa: BLE001
        return str(exc)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    low = int(k)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


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
