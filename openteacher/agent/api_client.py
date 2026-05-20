"""LLM API client for OpenTeacher.

Provides a thin wrapper around the OpenAI SDK for calling any
OpenAI-compatible API endpoint.
"""

from __future__ import annotations
from openai import OpenAI
from openteacher import config


def create_client() -> OpenAI:
    """Create an OpenAI client from current config."""
    api_key = config.get_api_key()
    api_base = config.get_api_base()

    if not api_key:
        raise RuntimeError(
            "未设置 API Key。请在 .env 文件中设置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY。\n"
            "示例: OPENAI_API_KEY=sk-xxxxx"
        )

    return OpenAI(api_key=api_key, base_url=api_base)


def call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
    stream: bool = True,
):
    """Call the LLM API. Returns a streaming or non-streaming completion.

    Args:
        messages: Chat messages in OpenAI format.
        tools: Optional list of tool definitions.
        model: Override model from config.
        temperature: Override temperature from config.
        max_tokens: Max tokens in response.
        stream: Whether to stream the response.
    """
    client = create_client()
    model = model or config.get_model()
    temperature = temperature if temperature is not None else config.get_config_value("temperature", 0.7)

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    return client.chat.completions.create(**kwargs)
