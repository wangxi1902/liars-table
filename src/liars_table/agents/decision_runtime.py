"""Agent 决策运行时的数据模型：动态预算、执行轨迹与最终结果。

为什么单独放在这个模块？
    LangGraph 负责“怎样走节点”，本模块负责“这次允许使用多少资源、执行时发生了什么”。
    两者分开后，预算可以来自环境变量、CLI、API 或某个座位的专属配置，而不需要
    修改图中的节点代码。

Python 知识点：
    @dataclass(frozen=True, slots=True)
        自动生成初始化和比较方法；frozen 防止预算在运行中被修改，slots 能及时发现
        拼错字段名的问题。
    Mapping
        表示“只需要像字典一样读取”的对象。调用方可以传 dict，但策略本身不会依赖
        dict 的修改方法。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from ..llm.schema import ActionPayload
from .base import DecisionRequest


class TraceStatus(StrEnum):
    """一个决策节点当前处于什么状态。"""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class TraceVisibility(StrEnum):
    """轨迹允许展示给谁；当前节点只产生不含私密内容的 PUBLIC 轨迹。"""

    PUBLIC = "public"
    PRIVATE = "private"
    GOD = "god"


@dataclass(frozen=True, slots=True)
class DecisionBudget:
    """一次 Agent 决策可以使用的资源上限。

    ``max_completion_tokens`` 是单次模型回复上限，不包含输入 Prompt。整个决策的
    调用总次数由 ``max_model_calls`` 另行限制，避免把两个概念混在一起。
    """

    max_seconds: float = 5.0
    max_steps: int = 8
    max_model_calls: int = 2
    max_completion_tokens: int = 800
    max_retries: int = 1

    def __post_init__(self) -> None:
        """尽早拒绝无意义配置，而不是等游戏跑到一半才出错。"""
        if self.max_seconds <= 0:
            raise ValueError("max_seconds 必须大于 0")
        if self.max_steps <= 0:
            raise ValueError("max_steps 必须大于 0")
        if self.max_model_calls <= 0:
            raise ValueError("max_model_calls 必须大于 0")
        if self.max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens 必须大于 0")
        if self.max_retries < 0:
            raise ValueError("max_retries 不能小于 0")


@dataclass(frozen=True, slots=True)
class DecisionBudgetPolicy:
    """根据当前请求动态选择预算。

    优先级从高到低：座位+决策类型、决策类型、座位、本局默认值。调用方只需要
    构造不同映射，不需要修改任何 LangGraph 节点。
    """

    default: DecisionBudget = field(default_factory=DecisionBudget)
    by_kind: Mapping[str, DecisionBudget] = field(default_factory=dict)
    by_seat: Mapping[str, DecisionBudget] = field(default_factory=dict)
    by_seat_and_kind: Mapping[tuple[str, str], DecisionBudget] = field(default_factory=dict)

    def resolve(self, request: DecisionRequest) -> DecisionBudget:
        """返回这次请求最终使用的预算。"""
        exact = self.by_seat_and_kind.get((request.seat, request.kind))
        if exact is not None:
            return exact
        by_kind = self.by_kind.get(request.kind)
        if by_kind is not None:
            return by_kind
        by_seat = self.by_seat.get(request.seat)
        return by_seat if by_seat is not None else self.default


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """可安全记录和展示的一条结构化决策轨迹。"""

    seat: str
    decision_kind: str
    node: str
    status: TraceStatus
    summary: str
    elapsed_ms: int
    steps_used: int
    model_calls: int
    visibility: TraceVisibility = TraceVisibility.PUBLIC

    def to_dict(self) -> dict[str, Any]:
        """转成 API/WebSocket 可以直接序列化的字典。"""
        return asdict(self)


TraceSink = Callable[[DecisionTrace], None]


@dataclass(frozen=True, slots=True)
class DecisionRunResult:
    """一次决策图执行完成后，交给 LLMAgent 的结果和统计。"""

    payload: ActionPayload | None
    budget: DecisionBudget
    traces: tuple[DecisionTrace, ...]
    timed_out: bool
    error: str
    steps_used: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int


@dataclass(slots=True)
class DecisionRunMetrics:
    """一次图运行独享的内部计数器，超时取消后仍保留已完成记录。"""

    started_at: float = field(default_factory=time.perf_counter)
    steps_used: int = 0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    traces: list[DecisionTrace] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def to_result(
        self,
        payload: ActionPayload | None,
        budget: DecisionBudget,
        *,
        timed_out: bool,
        error: str,
    ) -> DecisionRunResult:
        """把运行中的可变计数快照成不可变结果。"""
        return DecisionRunResult(
            payload=payload,
            budget=budget,
            traces=tuple(self.traces),
            timed_out=timed_out,
            error=error,
            steps_used=self.steps_used,
            model_calls=self.model_calls,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )
