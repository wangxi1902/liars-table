"""动态决策预算和安全 Trace 数据模型测试。"""

from __future__ import annotations

import pytest

from liars_table.agents.base import DecisionRequest
from liars_table.agents.decision_runtime import (
    DecisionBudget,
    DecisionBudgetPolicy,
    DecisionTrace,
    TraceStatus,
)
from liars_table.core.roles import Role


def _request(*, seat: str = "P1", kind: str = "vote") -> DecisionRequest:
    return DecisionRequest(kind=kind, seat=seat, role=Role.VILLAGER, round=1)


def test_budget_rejects_invalid_limits() -> None:
    """错误配置应在开局前失败，不能运行到某个节点才暴露。"""
    with pytest.raises(ValueError, match="max_seconds"):
        DecisionBudget(max_seconds=0)
    with pytest.raises(ValueError, match="max_retries"):
        DecisionBudget(max_retries=-1)


def test_policy_resolves_dynamic_overrides_by_priority() -> None:
    default = DecisionBudget(max_seconds=5)
    seat = DecisionBudget(max_seconds=7)
    speech = DecisionBudget(max_seconds=9)
    exact = DecisionBudget(max_seconds=12)
    policy = DecisionBudgetPolicy(
        default=default,
        by_seat={"P3": seat},
        by_kind={"speech": speech},
        by_seat_and_kind={("P3", "speech"): exact},
    )

    assert policy.resolve(_request()).max_seconds == 5
    assert policy.resolve(_request(seat="P3")).max_seconds == 7
    assert policy.resolve(_request(kind="speech")).max_seconds == 9
    assert policy.resolve(_request(seat="P3", kind="speech")).max_seconds == 12


def test_trace_payload_contains_only_structured_summary() -> None:
    trace = DecisionTrace(
        seat="P2",
        decision_kind="vote",
        node="prepare_context",
        status=TraceStatus.COMPLETED,
        summary="已准备公开上下文",
        elapsed_ms=12,
        steps_used=1,
        model_calls=0,
    )

    payload = trace.to_dict()
    assert payload["status"] == "completed"
    assert "messages" not in payload
    assert "raw_output" not in payload
