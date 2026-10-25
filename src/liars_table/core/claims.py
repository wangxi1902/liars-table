"""发言里的"断言"：把自由文本变成机器可核对的结构。

为什么需要这个？
    模型说的话是自然语言，"P3 是狼"和"我觉得 P3 有问题"对机器来说是两串字符。
    但复盘要做的是：**核对**——他说自己是什么身份？他指控了谁？
    所以这里把发言中的结论抽成 ``Claim``，让后续分析可以按字段处理。

两条抽取路径：
    1. 优先用结构化数据（模型按 schema 返回 {"kind": "accuse", "target": "P3"}）
    2. 兜底用正则从文本里猜（防模型不听话，也兼容旧的自由文本）

Python 知识点：
    ``"Claim | None"`` 作为返回值：解析失败返回 None，让调用方决定跳过。
    ``re`` 的命名分组 ``(?P<name>...)``：比下标更可读。
    类方法里 ``return cls(...)`` 而不是 ``Claim(...)``：子类也能正确构造。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: 中文说法 → 内部身份名
ROLE_WORDS: dict[str, str] = {
    "预言家": "seer",
    "女巫": "witch",
    "猎人": "hunter",
    "村民": "villager",
    "平民": "villager",
    "狼人": "werewolf",
    "狼": "werewolf",
}

_SEAT = re.compile(r"^[pP](\d+)$")
_SELF_ROLE = re.compile(r"我是\s*(预言家|女巫|猎人|村民|平民|狼人)")
_ACCUSE = re.compile(r"(?P<seat>[pP]\d+)\s*(?:是|就是|应该是|肯定是)\s*(?:狼人|狼|坏人|悍跳)")


@dataclass(frozen=True, slots=True)
class Claim:
    """一条断言。

    只有两种，够用了：
        accuse      —— 指控某人（target）
        claim_role  —— 声称自己是某个身份（role）
    """

    kind: str
    target: str | None = None
    role: str | None = None

    def describe(self) -> str:
        """给报告用的中文描述。"""
        if self.kind == "accuse" and self.target:
            return f"指控 {self.target}"
        if self.kind == "claim_role" and self.role:
            return f"自称 {self.role}"
        return f"{self.kind}"

    @classmethod
    def from_raw(cls, raw: Any) -> Claim | None:
        """把一个 dict 或一段文本转成 Claim。无法识别就返回 None。"""
        if isinstance(raw, dict):
            return cls._from_dict(raw)
        if isinstance(raw, str):
            return cls._from_text(raw)
        return None

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> Claim | None:
        kind = str(raw.get("kind", "")).strip().lower()
        if kind == "accuse":
            target = _normalize_seat(raw.get("target"))
            if target:
                return cls("accuse", target=target)
            # 可能是名字（"阿飞"）：core 层不认识名字，先原样保留，
            # 由 LLMAgent 用名册换算成座位号；换算不出来会被丢掉。
            raw_target = raw.get("target")
            if isinstance(raw_target, str) and raw_target.strip():
                return cls("accuse", target=raw_target.strip())
            return None
        if kind == "claim_role":
            role = ROLE_WORDS.get(str(raw.get("role", "")).strip())
            return cls("claim_role", role=role) if role else None
        return None

    @classmethod
    def _from_text(cls, text: str) -> Claim | None:
        """兜底：从自然语言里猜。覆盖常见的两种说法。"""
        claims = extract_claims(text)
        return claims[0] if claims else None


def extract_claims(text: str) -> tuple[Claim, ...]:
    """从一段自然语言里抽出所有能识别的断言。

    为什么需要它？
        模型经常"嘴上说了、字段里没写"：文本里有"我是预言家"，
        ``claims`` 数组却是空的。复盘只读结构化字段就会漏掉这句关键声明。
        这个函数把文本再扫一遍，作为**第二数据源**。
    """
    found: list[Claim] = []

    self_role = _SELF_ROLE.search(text)
    if self_role:
        role = ROLE_WORDS.get(self_role.group(1))
        if role:
            found.append(Claim("claim_role", role=role))

    for match in _ACCUSE.finditer(text):
        target = _normalize_seat(match.group("seat"))
        if target:
            found.append(Claim("accuse", target=target))

    return tuple(found)


def _normalize_seat(value: Any) -> str | None:
    """把 ``p3`` / ``P3`` / `` 3 `` 统一成 ``P3``。"""
    if value is None:
        return None
    text = str(value).strip()
    match = _SEAT.match(text)
    if match:
        return f"P{int(match.group(1))}"
    return None
