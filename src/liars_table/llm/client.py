"""LLM 客户端的兼容入口与创建工厂。

具体职责分别放在 ``base``、``mock`` 和 ``langchain_client``，现有调用方仍可从
本模块导入原来的名字。
"""

from __future__ import annotations

from .base import ChatClient, ChatMessage, ChatResult
from .langchain_client import DeepSeekClient, LangChainChatClient
from .mock import MockClient


def build_client(
    *,
    mock: bool,
    latency: float,
    api_key: str = "",
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-flash",
    thinking: bool = False,
    max_tokens: int = 800,
) -> ChatClient:
    """按配置创建离线 Mock 或基于 LangChain 的真实客户端。"""
    if mock:
        return MockClient(latency=latency)
    return DeepSeekClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        thinking=thinking,
        max_tokens=max_tokens,
    )


__all__ = [
    "ChatClient",
    "ChatMessage",
    "ChatResult",
    "DeepSeekClient",
    "LangChainChatClient",
    "MockClient",
    "build_client",
]
