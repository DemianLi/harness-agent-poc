"""LLM provider abstraction for Claude, OpenAI, Azure OpenAI, and Gemini.

Contract
--------
`create_llm()` MUST return a `BaseChatModel` that supports `.bind_tools()`,
`.invoke()` and `.stream()`, with `streaming=True`. Provider resolution order:
explicit `provider` arg > `[llm].provider` in config.toml > env auto-detect
(`AZURE_OPENAI_API_KEY` present -> "azure") > "claude" default.
Model resolution order: `[llm].model` in config.toml > `DEFAULT_MODELS[provider]`
(azure has no static default; it always requires `AZURE_OPENAI_DEPLOYMENT`).

Error taxonomy
--------------
- `ProviderUnknownError` — an unrecognised provider string was requested.
- `ProviderConfigError`  — a required credential/endpoint env var is missing.
  Both are raised eagerly at `create_llm()` time (fail fast, before any
  network call), never surfaced as a bare `KeyError`/`ValueError` to callers.

Retry contract (see `invoke_with_retry`)
-----------------------------------------
Transient provider errors (timeouts, connection errors, HTTP 429/5xx) are
retried up to `MAX_RETRIES` times with exponential backoff starting at
`RETRY_BACKOFF_BASE_S` seconds. Non-transient errors (bad request / content
filter / auth failures) are NOT retried — they are re-raised immediately so
the caller can degrade gracefully instead of wasting retry budget.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage

# Load .env from project root on import
load_dotenv(Path(__file__).parent.parent.parent / ".env")

Provider = Literal["claude", "openai", "azure", "gemini"]

# Default models per provider (azure uses deployment name from env)
DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "gemini": "gemini-2.0-flash",
}

# Config file location
CONFIG_PATH = Path.home() / ".harness-agent" / "config.toml"

# Retry policy for `invoke_with_retry`. Values are conservative defaults for
# an interactive CLI session (a human is waiting), not a batch pipeline.
MAX_RETRIES = 2
RETRY_BACKOFF_BASE_S = 1.0

# HTTP status codes considered transient and therefore retryable.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """Base class for provider configuration/selection errors."""


class ProviderUnknownError(ProviderError):
    """Raised when an unrecognised provider name is requested."""


class ProviderConfigError(ProviderError):
    """Raised when a required credential or endpoint is missing for a provider."""


def load_config() -> dict:
    """Load config from ~/.harness-agent/config.toml. Returns empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
        return tomllib.loads(CONFIG_PATH.read_text())
    else:
        import tomli
        return tomli.loads(CONFIG_PATH.read_text())


def get_default_provider() -> str:
    """Return the default provider from config, falling back to 'azure' if env is set."""
    config = load_config()
    configured = config.get("llm", {}).get("provider")
    if configured:
        return configured
    # Auto-detect azure if env vars are present
    if os.getenv("AZURE_OPENAI_API_KEY"):
        return "azure"
    return "claude"


def create_llm(provider: str | None = None) -> BaseChatModel:
    """Create and return a chat model for the given provider.

    Args:
        provider: One of 'claude', 'openai', 'azure', 'gemini'.
                  If None, auto-detects from config or environment.

    Returns:
        A LangChain chat model instance.
    """
    if provider is None:
        provider = get_default_provider()

    config = load_config()
    model_override = config.get("llm", {}).get("model")

    if provider == "azure":
        from langchain_openai import AzureChatOpenAI

        endpoint = _require_env("AZURE_OPENAI_ENDPOINT", provider)
        api_key = _require_env("AZURE_OPENAI_API_KEY", provider)
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        deployment = model_override or _require_env("AZURE_OPENAI_DEPLOYMENT", provider)

        return AzureChatOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            api_key=api_key,
            streaming=True,
        )

    elif provider == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_override or DEFAULT_MODELS["claude"],
            streaming=True,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_override or DEFAULT_MODELS["openai"],
            streaming=True,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_override or DEFAULT_MODELS["gemini"],
            streaming=True,
        )

    else:
        raise ProviderUnknownError(
            f"Unknown provider: {provider!r}. Choose from: claude, openai, azure, gemini"
        )


def _require_env(var_name: str, provider: str) -> str:
    """Return an env var's value or raise `ProviderConfigError` with an actionable message."""
    value = os.getenv(var_name)
    if not value:
        raise ProviderConfigError(
            f"Provider {provider!r} requires the {var_name} environment variable, "
            f"but it is not set. Add it to your .env file (see .env.example)."
        )
    return value


def ensure_config_exists(provider: str = "azure") -> None:
    """Create default config file if it doesn't exist."""
    if CONFIG_PATH.exists():
        return

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = f'[llm]\nprovider = "{provider}"\nmodel = ""\n'
    CONFIG_PATH.write_text(content)


def invoke_with_retry(
    model: BaseChatModel,
    messages: list[AnyMessage],
    max_retries: int = MAX_RETRIES,
) -> Any:
    """Invoke a chat model, retrying transient failures with exponential backoff.

    Contract: retries only on errors that look transient (timeouts, connection
    errors, or an HTTP status in `_RETRYABLE_STATUS_CODES`). Anything else
    (bad request, content filter, auth failure) is re-raised on the first
    attempt so the caller can degrade gracefully instead of burning retry
    budget on an error that will never succeed.
    """
    attempt = 0
    while True:
        try:
            return model.invoke(messages)
        except Exception as e:
            if attempt >= max_retries or not _is_retryable(e):
                raise
            delay = RETRY_BACKOFF_BASE_S * (2 ** attempt)
            time.sleep(delay)
            attempt += 1


def _is_retryable(e: Exception) -> bool:
    """Classify whether an exception from any supported provider SDK is transient."""
    status = getattr(e, "status_code", None) or getattr(
        getattr(e, "response", None), "status_code", None
    )
    if status is not None:
        return status in _RETRYABLE_STATUS_CODES
    # No status code on the exception (e.g. a raw network error) — treat
    # connection/timeout errors as transient by class name, to avoid a hard
    # dependency on every provider SDK's exception hierarchy.
    return type(e).__name__ in {"APIConnectionError", "APITimeoutError", "Timeout", "ConnectionError"}
