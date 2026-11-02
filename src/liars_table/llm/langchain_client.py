"""LangChain ChatModel 到项目 ``ChatClient`` 协议的适配器。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .base import ChatMessage, ChatResult


class LangChainChatClient:
    """复用 LangChain 标准模型接口，同时不让框架类型进入 Agent 层。"""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        default_max_tokens: int = 800,
        allow_temperature: bool = True,
    ) -> None:
        self._model = model
        self.default_max_tokens = default_max_tokens
        self.allow_temperature = allow_temperature
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        meta: dict[str, Any] | None = None,
        json_mode: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.8,
    ) -> ChatResult:
        self.calls += 1
        kwargs: dict[str, Any] = {"max_tokens": max_tokens or self.default_max_tokens}
        if self.allow_temperature:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._model.ainvoke(
            [_to_langchain_message(message) for message in messages],
            config={"metadata": dict(meta or {})},
            **kwargs,
        )
        prompt_tokens, completion_tokens = _token_usage(response)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        return ChatResult(
            text=response.text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class DeepSeekClient(LangChainChatClient):
    """通过 LangChain 的 OpenAI 兼容适配器调用 DeepSeek。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-flash",
        *,
        timeout: float = 40.0,
        max_retries: int = 2,
        thinking: bool = False,
        max_tokens: int = 800,
    ) -> None:
        if not api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY，请在 .env 里配置，或改用 mock 模式")

        chat_model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
        )
        super().__init__(
            chat_model,
            default_max_tokens=max_tokens,
            allow_temperature=not thinking,
        )


def _to_langchain_message(message: ChatMessage) -> BaseMessage:
    message_type = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }.get(message.role)
    if message_type is None:
        raise ValueError(f"不支持的消息角色：{message.role!r}")
    return message_type(content=message.content)


def _token_usage(message: BaseMessage) -> tuple[int, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
