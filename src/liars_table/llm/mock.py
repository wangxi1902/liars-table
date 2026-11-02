"""无需网络的模型替身，用于测试、演示和并发基准。"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Sequence
from typing import Any

from .base import ChatMessage, ChatResult


class MockClient:
    """根据决策类型生成合法 JSON，不调用任何真实模型。"""

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
        max_tokens: int | None = None,
        temperature: float = 0.8,
    ) -> ChatResult:
        self.calls += 1
        if self.latency > 0:
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
        prompt_tokens = sum(len(message.content) // 3 for message in messages)
        completion_tokens = len(text) // 3
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        return ChatResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _speech_payload(
        self, messages: Sequence[ChatMessage], meta: dict[str, Any]
    ) -> dict[str, Any]:
        if self.rng.random() < 0.12:
            payload = {
                "text": "我是预言家，昨晚验到了狼，大家跟我走。",
                "claims": [{"kind": "claim_role", "role": "seer"}],
                "cites": self._pick_cites(messages),
            }
            payload["basis"] = self._basis_payload(messages, meta)
            return payload

        current_seat = str(meta.get("seat", ""))
        content = messages[-1].content if messages else ""
        others = sorted(
            {
                candidate
                for candidate in re.findall(r"P\d+", content)
                if candidate != current_seat
            }
        )
        claims: list[dict[str, Any]] = []
        if others and self.rng.random() < 0.6:
            claims.append({"kind": "accuse", "target": self.rng.choice(others)})

        return {
            "text": self._speech_text(),
            "claims": claims,
            "cites": self._pick_cites(messages),
            "basis": self._basis_payload(messages, meta, others),
        }

    def _basis_payload(
        self,
        messages: Sequence[ChatMessage],
        meta: dict[str, Any],
        candidates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Mock也生成结构化依据，确保离线演示能走通完整展示链路。"""
        current_seat = str(meta.get("seat", ""))
        content = messages[-1].content if messages else ""
        seats = candidates or sorted(
            seat for seat in set(re.findall(r"P\d+", content)) if seat != current_seat
        )
        if not seats:
            return {"assessments": []}
        evidence = [
            {"event_id": event_id, "kind": "behavior"}
            for event_id in self._pick_cites(messages)
        ]
        return {
            "assessments": [
                {
                    "seat": self.rng.choice(seats),
                    "suspicion": self.rng.randint(45, 85),
                    "evidence": evidence,
                }
            ]
        }

    def _pick_cites(self, messages: Sequence[ChatMessage]) -> list[int]:
        if not messages:
            return []
        # 旧时间线使用[12]，个体对话记忆使用#12；Mock同时识别两种稳定编号。
        matches = re.findall(r"\[(\d+)\]|#(\d+)", messages[-1].content)
        ids = [int(square or hash_style) for square, hash_style in matches]
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
