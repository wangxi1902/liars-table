"""LangGraph 决策工作流测试：节点单测 + 完整图测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from liars_table.agents.base import DecisionRequest
from liars_table.agents.decision_graph import DecisionState, DecisionWorkflow
from liars_table.cognition import Facts
from liars_table.core.roles import Role
from liars_table.llm.base import ChatMessage, ChatResult
from liars_table.llm.schema import ActionPayload
from liars_table.memory import MemoryStore


class SequenceClient:
    """按顺序返回预设文本，并记录每次收到的消息。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0
        self.seen_messages: list[list[ChatMessage]] = []

    async def complete(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResult:
        self.seen_messages.append(list(messages))
        text = self.responses[self.calls]
        self.calls += 1
        return ChatResult(text=text)


def _request() -> DecisionRequest:
    return DecisionRequest(
        kind="vote",
        seat="P1",
        role=Role.VILLAGER,
        round=1,
        legal=("P2", "P3"),
        transcript=("[4] P2：我怀疑 P3",),
    )


def _state(**updates: Any) -> DecisionState:
    state: DecisionState = {
        "request": _request(),
        "messages": [],
        "raw_output": "",
        "payload": None,
        "attempt": 0,
        "error": "",
    }
    state.update(updates)
    return state


def _workflow(client: SequenceClient, *, max_retries: int = 1) -> DecisionWorkflow:
    return DecisionWorkflow(
        client,
        MemoryStore(),
        Facts(),
        max_retries=max_retries,
    )


def test_prepare_context_node_builds_model_messages() -> None:
    """普通节点可以脱离整张图单独测试。"""
    workflow = _workflow(SequenceClient([]))

    update = workflow.prepare_context(_state())
    messages = update["messages"]

    assert isinstance(messages, list)
    assert [message.role for message in messages] == ["system", "user"]
    assert "P1" in messages[0].content
    assert "P2" in messages[1].content


def test_conditional_edge_obeys_retry_budget() -> None:
    workflow = _workflow(SequenceClient([]), max_retries=1)

    assert workflow.route_after_validation(_state(attempt=1)) == "retry"
    assert workflow.route_after_validation(_state(attempt=2)) == "finish"
    assert (
        workflow.route_after_validation(_state(payload=ActionPayload(target="P2"))) == "finish"
    )


def test_graph_repairs_invalid_json_then_succeeds() -> None:
    """第一次解析失败后，图应走修复分支，并在第二次返回合法结果。"""
    client = SequenceClient(["这不是 JSON", '{"target": "P2"}'])
    workflow = _workflow(client)

    payload = asyncio.run(workflow.run(_request()))

    assert payload is not None and payload.target == "P2"
    assert client.calls == 2
    assert len(client.seen_messages[1]) == len(client.seen_messages[0]) + 2
    assert client.seen_messages[1][-2].role == "assistant"
    assert "只输出一个 JSON" in client.seen_messages[1][-1].content


def test_graph_stops_after_retry_budget_is_exhausted() -> None:
    client = SequenceClient(["坏结果", "还是坏结果"])
    workflow = _workflow(client)

    payload = asyncio.run(workflow.run(_request()))

    assert payload is None
    assert client.calls == 2
