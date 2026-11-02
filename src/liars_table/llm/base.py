"""模型调用边界使用的项目内类型。

Agent 只依赖这组小接口，不直接依赖 LangChain。这样规则和业务层可以继续使用
轻量 Mock，也可以在基础设施层替换不同模型提供商。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """一条与具体模型 SDK 无关的聊天消息。"""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    """一次逻辑模型调用的文本和 token 用量。"""

    text: str
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatClient(Protocol):
    """LLM Agent 使用的最小异步模型协议。"""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        meta: dict[str, Any] | None = None,
        json_mode: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.8,
    ) -> ChatResult:
        """完成一次模型调用；``meta`` 只用于日志和测试，不进入 Prompt。"""
        ...
