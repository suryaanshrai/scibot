"""
LLM configuration — registry, factory, and listing.

Usage:
    from app.config.llm_model import get_llm, list_llms

    # Default (from env)
    llm = get_llm()

    # Explicit config
    llm = get_llm({
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
        "temperature": 0.5,
        "max_tokens": 2048,
    })
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.config.settings import (
    ANTHROPIC_API_KEY,
    COHERE_API_KEY,
    DEEPSEEK_API_KEY,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_TEMPERATURE,
    GOOGLE_API_KEY,
    GROQ_API_KEY,
    HUGGINGFACEHUB_API_TOKEN,
    IBM_API_KEY,
    IBM_PROJECT_ID,
    IBM_URL,
    MISTRAL_API_KEY,
    OLLAMA_BASE_URL,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
    XAI_API_KEY,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps provider identifier → importable package (internal; not exposed to callers).
_PROVIDER_PACKAGES: dict[str, str] = {
    "openai": "langchain_openai",
    "anthropic": "langchain_anthropic",
    "google_genai": "langchain_google_genai",
    "groq": "langchain_groq",
    "ollama": "langchain_ollama",
    "mistral": "langchain_mistralai",
    "cohere": "langchain_cohere",
    "deepseek": "langchain_deepseek",
    "xai": "langchain_xai",
    "ibm": "langchain_ibm",
    "openrouter": "langchain_openrouter",
    "huggingface": "langchain_huggingface",
}

_LLM_REGISTRY: list[dict[str, Any]] = [
    {
        "provider": "openai",
        "human_name": "OpenAI",
        "default_model": "gpt-5.4",
        "models": [
            {"id": "gpt-5.4", "name": "GPT-5.4"},
            {"id": "gpt-5.4-pro", "name": "GPT-5.4 Pro"},
            {"id": "gpt-5-mini", "name": "GPT-5 Mini"},
            {"id": "gpt-5-nano", "name": "GPT-5 Nano"},
            {"id": "gpt-5", "name": "GPT-5"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "gpt-4.1-nano", "name": "GPT-4.1 Nano"},
            {"id": "o3", "name": "o3"},
            {"id": "o4-mini", "name": "o4 Mini"},
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        ],
    },
    {
        "provider": "anthropic",
        "human_name": "Anthropic",
        "default_model": "claude-haiku-4-5",
        "models": [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5"},
            {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet"},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
        ],
    },
    {
        "provider": "google_genai",
        "human_name": "Google Gemini",
        "default_model": "gemini-2.5-flash",
        "models": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
            {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite"},
            {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro (Preview)"},
            {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash (Preview)"},
        ],
    },
    {
        "provider": "groq",
        "human_name": "Groq",
        "default_model": "llama-3.3-70b-versatile",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant"},
            {"id": "openai/gpt-oss-120b", "name": "OpenAI GPT OSS 120B"},
            {"id": "openai/gpt-oss-20b", "name": "OpenAI GPT OSS 20B"},
            {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout (Preview)"},
            {"id": "moonshotai/kimi-k2-instruct-0905", "name": "Kimi K2 (Preview)"},
            {"id": "qwen/qwen3-32b", "name": "Qwen3 32B (Preview)"},
        ],
    },
    {
        "provider": "ollama",
        "human_name": "Ollama (local)",
        "default_model": "llama3.2",
        "models": [
            {"id": "llama3.2", "name": "Llama 3.2"},
            {"id": "llama3.1", "name": "Llama 3.1"},
            {"id": "mistral", "name": "Mistral"},
            {"id": "qwen2.5", "name": "Qwen 2.5"},
            {"id": "phi4", "name": "Phi-4"},
            {"id": "gemma3", "name": "Gemma 3"},
            {"id": "deepseek-r1", "name": "DeepSeek R1"},
        ],
    },
    {
        "provider": "mistral",
        "human_name": "Mistral AI",
        "default_model": "mistral-small-latest",
        "models": [
            {"id": "mistral-large-latest", "name": "Mistral Large 3"},
            {"id": "mistral-medium-3-1", "name": "Mistral Medium 3.1"},
            {"id": "mistral-small-latest", "name": "Mistral Small 3.2"},
            {"id": "magistral-medium-latest", "name": "Magistral Medium"},
            {"id": "magistral-small-latest", "name": "Magistral Small"},
            {"id": "codestral-latest", "name": "Codestral"},
            {"id": "ministral-8b-latest", "name": "Ministral 8B"},
            {"id": "ministral-3b-latest", "name": "Ministral 3B"},
        ],
    },
    {
        "provider": "cohere",
        "human_name": "Cohere",
        "default_model": "command-a-03-2025",
        "models": [
            {"id": "command-a-03-2025", "name": "Command A"},
            {"id": "command-r7b-12-2024", "name": "Command R7B"},
            {"id": "command-a-reasoning-08-2025", "name": "Command A Reasoning"},
            {"id": "command-a-vision-07-2025", "name": "Command A Vision"},
            {"id": "command-r-plus-08-2024", "name": "Command R+"},
            {"id": "command-r-08-2024", "name": "Command R"},
        ],
    },
    {
        "provider": "deepseek",
        "human_name": "DeepSeek",
        "default_model": "deepseek-chat",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
        ],
    },
    {
        "provider": "xai",
        "human_name": "xAI (Grok)",
        "default_model": "grok-4",
        "models": [
            {"id": "grok-4", "name": "Grok 4"},
            {"id": "grok-4-0709", "name": "Grok 4 (July 2025)"},
            {"id": "grok-4-fast-reasoning", "name": "Grok 4 Fast (Reasoning)"},
            {"id": "grok-4-fast-non-reasoning", "name": "Grok 4 Fast"},
            {"id": "grok-code-fast-1", "name": "Grok Code Fast"},
            {"id": "grok-3", "name": "Grok 3"},
            {"id": "grok-3-mini", "name": "Grok 3 Mini"},
        ],
    },
    {
        "provider": "ibm",
        "human_name": "IBM watsonx.ai",
        "default_model": "ibm/granite-3-3-8b-instruct",
        "models": [
            {"id": "ibm/granite-3-3-8b-instruct", "name": "Granite 3.3 8B Instruct"},
            {"id": "ibm/granite-3-3-2b-instruct", "name": "Granite 3.3 2B Instruct"},
            {"id": "ibm/granite-3-8b-instruct", "name": "Granite 3 8B Instruct"},
            {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout (watsonx)"},
            {"id": "meta-llama/llama-4-maverick-17b-128e-instruct-fp8", "name": "Llama 4 Maverick (watsonx)"},
            {"id": "meta-llama/llama-3-3-70b-instruct", "name": "Llama 3.3 70B (watsonx)"},
            {"id": "mistralai/mistral-medium-2505", "name": "Mistral Medium 3 (watsonx)"},
        ],
    },
    {
        "provider": "openrouter",
        "human_name": "OpenRouter",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "models": [
            {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B"},
            {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
            {"id": "anthropic/claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "openai/gpt-5.4", "name": "GPT-5.4"},
            {"id": "deepseek/deepseek-chat-v3-0324", "name": "DeepSeek V3"},
            {"id": "mistralai/mistral-large-2411", "name": "Mistral Large"},
        ],
    },
    {
        "provider": "huggingface",
        "human_name": "Hugging Face",
        "default_model": "HuggingFaceH4/zephyr-7b-beta",
        "models": [
            {"id": "HuggingFaceH4/zephyr-7b-beta", "name": "Zephyr 7B Beta"},
            {"id": "mistralai/Mistral-7B-Instruct-v0.3", "name": "Mistral 7B Instruct v0.3"},
            {"id": "microsoft/Phi-3-mini-4k-instruct", "name": "Phi-3 Mini 4K Instruct"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_available(provider: str) -> bool:
    pkg = _PROVIDER_PACKAGES.get(provider)
    return pkg is not None and importlib.util.find_spec(pkg) is not None


def _get_registry_entry(provider: str) -> dict[str, Any]:
    for entry in _LLM_REGISTRY:
        if entry["provider"] == provider:
            return entry
    supported = [e["provider"] for e in _LLM_REGISTRY]
    raise ValueError(
        f"Unsupported LLM provider: '{provider}'. "
        f"Supported providers: {supported}"
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm(config: dict[str, Any] | None = None) -> Any:
    """
    Return an initialised LangChain chat model.

    Parameters
    ----------
    config : dict, optional
        Supported keys (all optional; env vars used as fallback):

        Core:
          provider    – one of the providers in the registry (default: env DEFAULT_LLM_PROVIDER)
          model       – model identifier string
          temperature – float between 0 and 2
          max_tokens  – int
          api_key     – override the provider API key from env
          base_url    – override the provider base URL (Ollama, OpenAI-compatible)

        Common optional:
          streaming   – bool; enable token streaming (default: False)
          timeout     – float; request timeout in seconds
          max_retries – int; number of retries on transient errors

        OpenAI-specific:
          organization – str; OpenAI organization ID

        Google Gemini-specific:
          vertex_project  – str; Google Cloud project ID for Vertex AI
          vertex_location – str; Vertex AI region (e.g. "us-central1")
          convert_system_message_to_human – bool; required for some older Gemini models

        Ollama-specific:
          keep_alive      – str; how long the model stays loaded (e.g. "5m", "-1")
          ollama_format   – str; response format override (e.g. "json")

        Mistral-specific:
          safe_mode – bool; enable Mistral content filtering

        IBM-specific:
          ibm_url         – watsonx endpoint URL
          ibm_project_id  – watsonx project ID

        HuggingFace-specific:
          huggingface_endpoint_url – custom inference endpoint URL

        extra_kwargs – dict; any additional keyword arguments passed directly to the
                       provider's constructor, merged last (can override named params)
    """
    cfg = config or {}

    provider = cfg.get("provider") or DEFAULT_LLM_PROVIDER or "openai"
    entry = _get_registry_entry(provider)

    model = cfg.get("model") or DEFAULT_LLM_MODEL or entry["default_model"]

    raw_temp = cfg.get("temperature")
    if raw_temp is None and DEFAULT_LLM_TEMPERATURE is not None:
        raw_temp = DEFAULT_LLM_TEMPERATURE
    temperature = float(raw_temp) if raw_temp is not None else 0.7

    raw_max_tokens = cfg.get("max_tokens") or DEFAULT_LLM_MAX_TOKENS
    max_tokens = int(raw_max_tokens) if raw_max_tokens is not None else None

    streaming: bool = bool(cfg.get("streaming", False))
    timeout: float | None = cfg.get("timeout")
    max_retries: int | None = cfg.get("max_retries")
    extra_kwargs: dict[str, Any] = cfg.get("extra_kwargs") or {}

    # ── OpenAI ────────────────────────────────────────────────────────────────
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "api_key": cfg.get("api_key") or OPENAI_API_KEY,
            "base_url": cfg.get("base_url") or None,
            "streaming": streaming,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if cfg.get("organization"):
            kwargs["organization"] = cfg["organization"]
        kwargs.update(extra_kwargs)
        return ChatOpenAI(**kwargs)

    # ── Anthropic ─────────────────────────────────────────────────────────────
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens or 1024,
            "api_key": cfg.get("api_key") or ANTHROPIC_API_KEY,
            "streaming": streaming,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        kwargs.update(extra_kwargs)
        return ChatAnthropic(**kwargs)

    # ── Google Gemini ─────────────────────────────────────────────────────────
    if provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "google_api_key": cfg.get("api_key") or GOOGLE_API_KEY,
            "streaming": streaming,
        }
        if cfg.get("vertex_project"):
            kwargs["project"] = cfg["vertex_project"]
        if cfg.get("vertex_location"):
            kwargs["location"] = cfg["vertex_location"]
        if cfg.get("convert_system_message_to_human"):
            kwargs["convert_system_message_to_human"] = True
        if timeout is not None:
            kwargs["request_timeout"] = timeout
        kwargs.update(extra_kwargs)
        return ChatGoogleGenerativeAI(**kwargs)

    # ── Groq ──────────────────────────────────────────────────────────────────
    if provider == "groq":
        from langchain_groq import ChatGroq

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "groq_api_key": cfg.get("api_key") or GROQ_API_KEY,
            "streaming": streaming,
        }
        if timeout is not None:
            kwargs["request_timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        kwargs.update(extra_kwargs)
        return ChatGroq(**kwargs)

    # ── Ollama ────────────────────────────────────────────────────────────────
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        kwargs = {
            "model": model,
            "temperature": temperature,
            "num_predict": max_tokens,
            "base_url": cfg.get("base_url") or OLLAMA_BASE_URL,
            "streaming": streaming,
        }
        if cfg.get("keep_alive"):
            kwargs["keep_alive"] = cfg["keep_alive"]
        if cfg.get("ollama_format"):
            kwargs["format"] = cfg["ollama_format"]
        kwargs.update(extra_kwargs)
        return ChatOllama(**kwargs)

    # ── Mistral ───────────────────────────────────────────────────────────────
    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "mistral_api_key": cfg.get("api_key") or MISTRAL_API_KEY,
            "streaming": streaming,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if cfg.get("safe_mode"):
            kwargs["safe_mode"] = True
        kwargs.update(extra_kwargs)
        return ChatMistralAI(**kwargs)

    # ── Cohere ────────────────────────────────────────────────────────────────
    if provider == "cohere":
        from langchain_cohere import ChatCohere

        return ChatCohere(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            cohere_api_key=cfg.get("api_key") or COHERE_API_KEY,
            streaming=streaming,
            **extra_kwargs,
        )

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=cfg.get("api_key") or DEEPSEEK_API_KEY,
            streaming=streaming,
            **extra_kwargs,
        )

    # ── xAI ───────────────────────────────────────────────────────────────────
    if provider == "xai":
        from langchain_xai import ChatXAI

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "xai_api_key": cfg.get("api_key") or XAI_API_KEY,
            "streaming": streaming,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        kwargs.update(extra_kwargs)
        return ChatXAI(**kwargs)

    # ── IBM watsonx.ai ────────────────────────────────────────────────────────
    if provider == "ibm":
        from langchain_ibm import ChatWatsonx

        return ChatWatsonx(
            model_id=model,
            url=cfg.get("ibm_url") or IBM_URL,
            project_id=cfg.get("ibm_project_id") or IBM_PROJECT_ID,
            apikey=cfg.get("api_key") or IBM_API_KEY,
            params={
                "temperature": temperature,
                **({"max_new_tokens": max_tokens} if max_tokens else {}),
            },
            **extra_kwargs,
        )

    # ── OpenRouter ────────────────────────────────────────────────────────────
    if provider == "openrouter":
        from langchain_openrouter import ChatOpenRouter

        return ChatOpenRouter(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            openrouter_api_key=cfg.get("api_key") or OPENROUTER_API_KEY,
            streaming=streaming,
            **extra_kwargs,
        )

    # ── Hugging Face ──────────────────────────────────────────────────────────
    if provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

        endpoint = HuggingFaceEndpoint(
            repo_id=model,
            temperature=temperature,
            max_new_tokens=max_tokens or 512,
            huggingfacehub_api_token=cfg.get("api_key") or HUGGINGFACEHUB_API_TOKEN,
            endpoint_url=cfg.get("huggingface_endpoint_url") or None,
            streaming=streaming,
            **extra_kwargs,
        )
        return ChatHuggingFace(llm=endpoint)

    # Should never reach here — _get_registry_entry raises first
    raise ValueError(f"Unsupported LLM provider: '{provider}'")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_llms() -> list[dict[str, Any]]:
    """
    Return all LLM providers whose integration package is currently installed.

    Each entry contains:
      provider     – provider identifier string
      human_name   – display name
      default_model – default model ID
      models       – list of {id, name} dicts
    """
    return [
        {
            "provider": entry["provider"],
            "human_name": entry["human_name"],
            "default_model": entry["default_model"],
            "models": entry["models"],
        }
        for entry in _LLM_REGISTRY
        if _is_available(entry["provider"])
    ]
