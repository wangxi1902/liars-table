"""解析模型输出。

LLM 返回的东西永远不可信：可能带 markdown 代码块、可能多说一句"好的"、
可能字段名拼错。这个模块负责把"文本"变成"结构化 Action"，失败就返回 None，
让上层决定重试还是兜底。

Python 知识点：
    Pydantic BaseModel
        对模型输出做运行时校验；字段类型不合法时拒绝整次结果，由上层重试。
    isinstance(x, str) / isinstance(x, (int, float))
        运行时类型判断，用于把模型返回的松散结构强制成我们要的类型。
    re.sub
        正则替换。这里用来剥掉 ```json ... ``` 这种代码围栏。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from ..core.claims import Claim

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class ActionPayload(BaseModel):
    """模型输出解析后的统一结构。字段缺失时用默认值，多余字段忽略。"""

    model_config = ConfigDict(extra="ignore", frozen=True, arbitrary_types_allowed=True)

    target: str | None = None
    save: StrictBool = False
    text: str = ""
    claims: tuple[Claim, ...] = ()
    cites: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionPayload:
        target = data.get("target")
        if not isinstance(target, str) or not target.strip():
            target = None

        text = data.get("text")
        if not isinstance(text, str):
            text = ""

        return cls.model_validate(
            {
                "target": target.strip() if target else None,
                "save": data.get("save", False),
                "text": text.strip(),
                "claims": _as_claims(data.get("claims")),
                "cites": _as_str_tuple(data.get("cites")),
            }
        )


def _as_claims(value: Any) -> tuple[Claim, ...]:
    """把模型给的 claims 变成结构化断言。

    模型可能给 {"kind": "accuse", "target": "P3"}，也可能偷懒给字符串 "P3是狼"，
    甚至给一个字符串而不是数组。三种都接住。
    """
    if value is None:
        return ()
    items = value if isinstance(value, (list, tuple)) else [value]
    parsed = (Claim.from_raw(item) for item in items)
    return tuple(claim for claim in parsed if claim is not None)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把任意输入转成字符串元组。模型有时会给字符串而不是数组。"""
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return ()


def _extract_json(text: str) -> str | None:
    """从一段可能很脏的文本里抠出 JSON 对象。"""
    if not text:
        return None
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    match = _OBJECT.search(text)
    return match.group(0) if match else text.strip()


def parse_action(text: str) -> ActionPayload | None:
    """解析成功返回 ActionPayload，失败返回 None（由上层决定重试/兜底）。"""
    candidate = _extract_json(text)
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return ActionPayload.from_dict(data)
    except (TypeError, ValueError, ValidationError):
        return None
