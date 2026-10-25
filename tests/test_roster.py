import asyncio
import json

from liars_table.agents.base import DecisionRequest
from liars_table.agents.llm_agent import LLMAgent
from liars_table.agents.prompts import build_messages
from liars_table.core.roles import Role
from liars_table.llm.client import ChatResult
from liars_table.roster import NAMES, build_roster, seat_of, substitute


def test_name_pool_has_twenty_entries() -> None:
    assert len(NAMES) == 20
    assert len(set(NAMES)) == 20, "名字池不能有重复"


def test_roster_picks_unique_names_from_the_pool() -> None:
    roster = build_roster(11, 9)
    names = [info.name for info in roster.values()]
    assert len(names) == 9
    assert len(set(names)) == 9, "一局之内名字不能重复"
    assert set(names) <= set(NAMES)


def test_different_seeds_pick_different_name_sets() -> None:
    a = {info.name for info in build_roster(1, 9).values()}
    b = {info.name for info in build_roster(2, 9).values()}
    assert a != b


def test_roster_is_deterministic() -> None:
    a = build_roster(7, 9)
    b = build_roster(7, 9)
    assert {seat: info.name for seat, info in a.items()} == {
        seat: info.name for seat, info in b.items()
    }


def test_roster_differs_by_seed() -> None:
    a = [info.name for info in build_roster(1, 9).values()]
    b = [info.name for info in build_roster(2, 9).values()]
    assert a != b, "不同 seed 应该洗出不同顺序"


def test_substitute_replaces_seats_with_names() -> None:
    roster = build_roster(3, 9)
    name = roster["P3"].name
    assert substitute("P3：我怀疑 P5", roster) == f"{name}：我怀疑 {roster['P5'].name}"


def test_seat_of_accepts_seat_name_and_mixed() -> None:
    roster = build_roster(4, 9)
    name = roster["P3"].name
    assert seat_of("P3", roster) == "P3"
    assert seat_of("p3", roster) == "P3"
    assert seat_of(name, roster) == "P3"
    assert seat_of(f"P3（{name}）", roster) == "P3"
    assert seat_of("不存在的人", roster) is None


def test_prompt_contains_names() -> None:
    roster = build_roster(5, 9)
    request = DecisionRequest(
        kind="speech",
        seat="P1",
        role=Role.VILLAGER,
        round=1,
        context={"alive": ["P1", "P2", "P3"]},
    )
    messages = build_messages(request, roster=roster)
    system, user = messages[0].content, messages[1].content
    assert roster["P1"].name in system
    assert roster["P2"].name in user


class NameAnsweringClient:
    """故意用名字回答，验证 LLMAgent 能换算回座位号。"""

    def __init__(self, name: str) -> None:
        self.name = name

    async def complete(self, messages, **kwargs):
        return ChatResult(
            text=json.dumps(
                {
                    "target": self.name,
                    "claims": [{"kind": "accuse", "target": self.name}],
                }
            )
        )


def test_agent_maps_name_back_to_seat() -> None:
    roster = build_roster(6, 9)
    name = roster["P3"].name
    agent = LLMAgent("P1", Role.VILLAGER, NameAnsweringClient(name), roster=roster)

    request = DecisionRequest(
        kind="vote", seat="P1", role=Role.VILLAGER, round=1, legal=("P2", "P3")
    )
    decision = asyncio.run(agent.decide(request))

    assert decision.target == "P3", "名字必须被换算回座位号"
    assert decision.claims[0].target == "P3"
