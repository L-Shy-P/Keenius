"""Keenius 的 LLM API 客户端。"""

from __future__ import annotations
from openai import OpenAI
from keenius import config


def create_client() -> OpenAI:
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    if not api_key:
        raise RuntimeError(
            "未设置 API Key。请输入 /setup 配置。\n"
            "或在 .env 文件中设置 OPENAI_API_KEY=sk-xxxxx"
        )
    return OpenAI(api_key=api_key, base_url=api_base)


def call_llm(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
    stream: bool = False,
):
    client = create_client()
    kwargs = {
        "model": model or config.get_model(),
        "messages": messages,
        "temperature": temperature if temperature is not None else config.get_config_value("temperature", 0.7),
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return client.chat.completions.create(**kwargs)
