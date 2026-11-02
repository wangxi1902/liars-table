import asyncio
import random

from liars_table.agents.llm_agent import LLMAgent
from liars_table.agents.random_agent import RandomAgent
from liars_table.core.events import WolfTalk
from liars_table.core.roles import Role
from liars_table.engine import Engine
from liars_table.llm.client import MockClient


def test_speech_order_covers_everyone_and_varies() -> None:
    engine = Engine(agent_factory=lambda seat, role: RandomAgent(), seed=3)
    engine.state.alive = {"P1", "P2", "P3", "P4"}

    orders = {tuple(engine._speech_order()) for _ in range(40)}

    for order in orders:
        assert sorted(order) == ["P1", "P2", "P3", "P4"], "每个人只能出现一次"
    assert len(orders) > 1, "起点应该是随机的"


def test_speech_order_is_deterministic_for_same_seed() -> None:
    def first_order(seed: int) -> list[str]:
        engine = Engine(agent_factory=lambda seat, role: RandomAgent(), seed=seed)
        engine.state.alive = {"P1", "P2", "P3"}
        return engine._speech_order()

    assert first_order(7) == first_order(7)


def test_wolves_discuss_in_order_and_see_previous_talks() -> None:
    # 只记录"第一次狼聊"时的记录长度：第一夜三个狼都在，
    # 后面的夜里可能有狼已经出局，长度就不代表顺序了。
    first_night: dict[str, int] = {}

    def factory(seat: str, role):
        inner = RandomAgent(random.Random(seat))

        class Spy:
            def observe(self, event, round_no: int, event_id: int | None = None) -> None:
                return None

            async def decide(self, request):
                if request.kind == "wolf_talk" and seat not in first_night:
                    first_night[seat] = len(request.context.get("wolf_chat") or [])
                return await inner.decide(request)

        return Spy()

    engine = Engine(agent_factory=factory, seed=5)
    asyncio.run(engine.run())

    wolves = sorted(seat for seat, role in engine.state.roles.items() if role is Role.WEREWOLF)
    assert len(wolves) == 3

    # 第一个狼看到空记录，第二个看到 1 条，第三个看到 2 条
    assert first_night[wolves[0]] == 0
    assert first_night[wolves[1]] == 1
    assert first_night[wolves[2]] == 2


def test_wolf_talk_events_only_reach_wolves() -> None:
    seen: dict[str, list[str]] = {}

    def factory(seat: str, role):
        inner = RandomAgent(random.Random(seat))

        class Spy:
            def observe(self, event, round_no: int, event_id: int | None = None) -> None:
                if isinstance(event, WolfTalk):
                    seen.setdefault(seat, []).append(event.text)

            async def decide(self, request):
                return await inner.decide(request)

        return Spy()

    engine = Engine(agent_factory=factory, seed=6)
    asyncio.run(engine.run())

    wolves = {seat for seat, role in engine.state.roles.items() if role is Role.WEREWOLF}
    for seat, texts in seen.items():
        assert seat in wolves, f"{seat} 不是狼，却看到了狼队夜聊"
        assert texts, "狼人应该收到自己的夜聊记录"


def test_wolf_talk_appears_in_mock_game() -> None:
    client = MockClient(latency=0.0, seed=1)
    engine = Engine(agent_factory=lambda seat, role: LLMAgent(seat, role, client), seed=8)
    result = asyncio.run(engine.run())

    talks = [event for event in result.events if isinstance(event, WolfTalk)]
    assert talks, "每夜都应该产生狼队夜聊"
