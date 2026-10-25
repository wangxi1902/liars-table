import asyncio
import json

from liars_table.agents.base import DecisionRequest
from liars_table.agents.llm_agent import LLMAgent
from liars_table.core.claims import Claim
from liars_table.core.events import GameEnded
from liars_table.core.roles import Role
from liars_table.engine import Engine
from liars_table.llm.client import ChatResult, MockClient
from liars_table.llm.schema import parse_action


def request_for(kind: str = "vote", legal: tuple[str, ...] = ("P2", "P3")) -> DecisionRequest:
    return DecisionRequest(kind=kind, seat="P1", role=Role.VILLAGER, round=1, legal=legal)


# ------------------------------------------------------------------ 解析层


def test_parse_plain_json() -> None:
    payload = parse_action('{"target": "P3"}')
    assert payload is not None and payload.target == "P3"


def test_parse_fenced_json() -> None:
    text = '好的，我的选择是：\n```json\n{"target": "P5", "claims": ["P5是狼"]}\n```'
    payload = parse_action(text)
    assert payload is not None
    assert payload.target == "P5"
    assert payload.claims == (Claim("accuse", target="P5"),)


def test_parse_garbage_returns_none() -> None:
    assert parse_action("我觉得应该投 P3") is None
    assert parse_action("") is None


def test_parse_tolerates_string_claims() -> None:
    payload = parse_action('{"target": "P2", "claims": "P2是狼"}')
    assert payload is not None and payload.claims == (Claim("accuse", target="P2"),)


# ------------------------------------------------------------------ Agent 层


class AlwaysBadClient:
    """永远返回非 JSON，用来验证降级路径。"""

    async def complete(self, messages, **kwargs):
        return ChatResult(text="我不太确定，隨便投一个吧")


def test_agent_returns_empty_decision_when_output_is_garbage() -> None:
    agent = LLMAgent("P1", Role.VILLAGER, AlwaysBadClient())
    decision = asyncio.run(agent.decide(request_for()))
    assert decision.target is None
    assert decision.text == ""


def test_agent_retries_then_parses() -> None:
    """第一次返回垃圾、第二次返回合法 JSON，应该能拿到结果。"""

    class FlakyClient:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChatResult(text="嗯……")
            return ChatResult(text='{"target": "P2"}')

    client = FlakyClient()
    agent = LLMAgent("P1", Role.VILLAGER, client)
    decision = asyncio.run(agent.decide(request_for()))
    assert decision.target == "P2"
    assert client.calls == 2


def test_mock_game_terminates_without_network() -> None:
    """整局跑在 MockClient 上：不需要 key，也不联网。"""
    client = MockClient(latency=0.0, seed=1)
    engine = Engine(agent_factory=lambda seat, role: LLMAgent(seat, role, client), seed=4)
    result = asyncio.run(engine.run())

    assert result.state.winner is not None
    assert isinstance(result.events[-1], GameEnded)
    assert client.calls > 0


def test_parallel_votes_are_emitted_in_seat_order() -> None:
    """并发之后事件顺序仍然确定：同一天的投票事件必须按座位号排。"""
    client = MockClient(latency=0.0, seed=2)
    engine = Engine(agent_factory=lambda seat, role: LLMAgent(seat, role, client), seed=9)
    result = asyncio.run(engine.run())

    rounds: list[list[str]] = []
    current: list[str] = []
    for event in result.events:
        if event.kind == "voted":
            current.append(event.voter)
        elif event.kind == "exiled":
            rounds.append(current)
            current = []

    assert rounds, "一局里至少应该有一轮投票"
    for voters in rounds:
        assert voters == sorted(voters, key=lambda s: int(s[1:])), "投票事件顺序被打乱了"


def test_events_remain_json_serialisable_with_llm_agent() -> None:
    client = MockClient(latency=0.0, seed=3)
    engine = Engine(agent_factory=lambda seat, role: LLMAgent(seat, role, client), seed=6)
    result = asyncio.run(engine.run())
    json.dumps([e.to_dict() for e in result.events], ensure_ascii=False)


def test_agent_recovers_claims_from_text_when_field_is_empty() -> None:
    """模型常常"嘴上说了、字段没写"，必须从文本里补出来。"""

    class TextOnlyClient:
        async def complete(self, messages, **kwargs):
            return ChatResult(text='{"text": "我是预言家，P3 是狼", "claims": []}')

    agent = LLMAgent("P1", Role.SEER, TextOnlyClient())
    decision = asyncio.run(agent.decide(request_for(kind="speech")))

    kinds = {claim.kind for claim in decision.claims}
    assert "claim_role" in kinds
    assert "accuse" in kinds


def test_agent_merges_text_claims_even_when_json_claims_exist() -> None:
    """真机跑出来的坑：JSON 里有 accuse、文本里有"我是预言家"，
    旧逻辑只在 claims 为空时兜底，于是身份声明被丢掉了。"""

    class PartialClient:
        async def complete(self, messages, **kwargs):
            return ChatResult(
                text='{"text": "我是预言家，P3 是狼", '
                '"claims": [{"kind": "accuse", "target": "P3"}]}'
            )

    agent = LLMAgent("P1", Role.SEER, PartialClient())
    decision = asyncio.run(agent.decide(request_for(kind="speech")))

    kinds = {claim.kind for claim in decision.claims}
    assert "accuse" in kinds, "JSON 里的指控不能丢"
    assert "claim_role" in kinds, "文本里的身份声明必须补进来"
