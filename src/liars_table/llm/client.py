"""LLM 客户端：一个异步接口，两种实现（真调用 / 假调用）。

为什么要先定接口？
    因为你想让代码在没有 API key 的情况下也能跑、能测。
    于是定义 ``ChatClient`` 协议，真实现负责联网，假实现负责睡觉和返回 stub。
    Agent 只依赖协议，不关心背后是谁——这就是"依赖倒置"。

Python 知识点：
    async def / await
        ``async def`` 定义一个协程函数。调用它不会立刻执行，而是返回一个协程对象；
        只有 ``await`` 它（或交给 asyncio.gather）才真正开始跑。
        遇到 ``await asyncio.sleep(...)`` 时，事件循环会把 CPU 让给别的协程——
        这就是"单线程也能并发等 IO"的原理。
    Protocol
        见 agents/base.py 的说明。这里再强调一次：不用继承，实现方法即可。
    asyncio.sleep vs time.sleep
        ``asyncio.sleep`` 会让出控制权（并发友好）；
        ``time.sleep`` 会把整个线程卡死（并发失效）。这是新手最常犯的错。
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """一条对话消息。role 只有 system / user / assistant 三种。"""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    """一次调用的结果，顺便带上 token 用量（用来算钱）。"""

    text: str
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0



class ChatClient(Protocol):
    """所有客户端都要满足的接口。"""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        meta: dict[str, Any] | None = None,
        json_mode: bool = True,
        max_tokens: int = 400,
        temperature: float = 0.8,
    ) -> ChatResult:
        """发一轮对话，返回模型输出。

        ``meta`` 是给测试和日志用的旁路信息（例如本次决策的类型、合法目标），
        **不会**发给模型。真客户端忽略它，假客户端靠它生成合法回复。
        """
        ...


class MockClient:
    """不联网的假客户端：用来在没有 key 时跑通全链路、跑测试、演示并发。

    它按 ``meta["kind"]`` 造一个合法 JSON 回复，所以引擎不会因为"模型乱说"而崩。
    ``latency`` 模拟网络耗时——这是演示异步收益的关键：延迟越大，并发优势越明显。
    """

    def __init__(self, latency: float = 0.0, seed: int = 0) -> None:
        self.latency = latency
        self.rng = random.Random(seed)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        meta: dict[str, Any] | None = None,
        json_mode: bool = True,
        max_tokens: int = 400,
        temperature: float = 0.8,
    ) -> ChatResult:
        self.calls += 1
        if self.latency > 0:
            # 注意：这里必须是 asyncio.sleep，换成 time.sleep 就变成串行了
            await asyncio.sleep(self.latency)

        meta = meta or {}
        kind = meta.get("kind")
        legal: list[str] = list(meta.get("legal") or [])

        if kind == "speech":
            payload: dict[str, Any] = self._speech_payload(messages, meta)
        elif kind == "witch":
            payload = {"save": False}
            if legal and self.rng.random() < 0.12:
                payload["target"] = self.rng.choice(legal)
        else:
            payload = {"target": self.rng.choice(legal)} if legal else {}

        text = json.dumps(payload, ensure_ascii=False)
        self.prompt_tokens += sum(len(m.content) // 3 for m in messages)
        self.completion_tokens += len(text) // 3
        return ChatResult(
            text=text,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )

    def _speech_payload(
        self, messages: Sequence[ChatMessage], meta: dict[str, Any]
    ) -> dict[str, Any]:
        """假发言：偶尔跳预言家、偶尔指控一个人，用来验证"断言"链路。

        注意这是测试替身的行为，不代表真实模型的输出质量。
        """
        if self.rng.random() < 0.12:
            return {
                "text": "我是预言家，昨晚验到了狼，大家跟我走。",
                "claims": [{"kind": "claim_role", "role": "seer"}],
                "cites": self._pick_cites(messages),
            }

        seat = str(meta.get("seat", ""))
        content = messages[-1].content if messages else ""
        others = sorted({s for s in re.findall(r"P\d+", content) if s != seat})
        claims: list[dict[str, Any]] = []
        if others and self.rng.random() < 0.6:
            claims.append({"kind": "accuse", "target": self.rng.choice(others)})

        return {
            "text": self._speech_text(),
            "claims": claims,
            "cites": self._pick_cites(messages),
        }

    def _pick_cites(self, messages: Sequence[ChatMessage]) -> list[int]:
        """假客户端也要"引用"：从 prompt 里抓几个事件编号，模拟真实模型的行为。

        这样即使不联网，也能验证"引用 → 校验 → 落库"这条链路是通的。
        """
        if not messages:
            return []
        ids = [int(x) for x in re.findall(r"\[(\d+)\]", messages[-1].content)]
        if not ids or self.rng.random() > 0.6:
            return []
        return [self.rng.choice(ids)]

    def _speech_text(self) -> str:
        templates = [
            "我先过，听听后面怎么说。",
            "昨晚的信息太少了，我暂时不站边。",
            "我觉得有人一直在带节奏，先记一下。",
            "我这边没有额外信息，按逻辑投票。",
        ]
        return self.rng.choice(templates)


class DeepSeekClient:
    """真实的 DeepSeek 客户端（OpenAI 兼容接口）。

    失败重试策略：指数退避（0.8s、1.6s…）。为什么要重试？
    因为网络抖动、限流（429）、服务端 5xx 都是暂时的，
    重试一次往往就成功了；但重试不能无限做，否则一局游戏会被拖死。
    """

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
            raise RuntimeError("缺少 DEEPSEEK_API_KEY，请在 .env 里配置，或改用 --mock")

        # 延迟导入：只有真正要用真模型时才需要装 openai 包
        from openai import AsyncOpenAI

        self.model = model
        self.max_retries = max_retries
        self.thinking = thinking
        self.max_tokens = max_tokens
        self.calls = 0
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
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
        # thinking 必须通过 extra_body 传，这是 OpenAI SDK 的转义通道。
        # 为什么要显式关闭？两个原因：
        #   1. 默认是 enabled 且 effort=high，思维链会吃掉 max_tokens，
        #      导致 JSON 被截断、解析失败（表现为 agent“沉默”）。
        #   2. 思考模式下 temperature 不生效，9 个 agent 会输出高度雷同。
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self.max_tokens,
            "extra_body": {"thinking": {"type": "enabled" if self.thinking else "disabled"}},
        }
        if not self.thinking:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.calls += 1
            try:
                response = await self._client.chat.completions.create(**kwargs)
            except Exception as exc:  # 边界处兜底：网络/限流/超时都可能发生
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(0.8 * (2**attempt))
                continue

            choice = response.choices[0]
            text = choice.message.content or ""
            usage = response.usage
            if usage is not None:
                self.prompt_tokens += usage.prompt_tokens
                self.completion_tokens += usage.completion_tokens
            return ChatResult(
                text=text,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            )

        raise RuntimeError(f"DeepSeek 调用失败（已重试 {self.max_retries} 次）: {last_error}")


def build_client(
    *,
    mock: bool,
    latency: float,
    api_key: str = "",
    model: str = "deepseek-flash",
    thinking: bool = False,
    max_tokens: int = 800,
) -> ChatClient:
    """按配置创建客户端。CLI 和测试都从这里拿实例。"""
    if mock:
        return MockClient(latency=latency)
    return DeepSeekClient(
        api_key=api_key,
        model=model,
        thinking=thinking,
        max_tokens=max_tokens,
    )
