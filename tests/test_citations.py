import asyncio
import random
import re

from liars_table.agents.llm_agent import LLMAgent
from liars_table.agents.random_agent import RandomAgent
from liars_table.core import events as ev
from liars_table.core.events import Spoke
from liars_table.engine import Engine
from liars_table.llm.client import MockClient


def run_game(seed: int):
    engine = Engine(
        agent_factory=lambda seat, role: RandomAgent(random.Random(f"{seed}:{seat}")),
        seed=seed,
    )
    return asyncio.run(engine.run())


def test_every_log_line_is_numbered() -> None:
    result = run_game(3)
    assert result.transcript, "战报不应该为空"
    for line in result.transcript:
        assert re.match(r"^\[\d+\] ", line), f"缺少编号：{line}"


def test_numbers_match_event_indexes() -> None:
    """编号必须落在事件列表范围内，否则引用会全部错位。"""
    result = run_game(4)
    for line in result.transcript:
        seq = int(line[1 : line.index("]")])
        assert 0 <= seq < len(result.events), f"编号越界：{line}"


def test_private_events_do_not_enter_the_public_log() -> None:
    result = run_game(6)
    joined = "\n".join(result.transcript)
    assert "查验" not in joined, "预言家验人结果泄露到公开时间线"
    assert "提议袭击" not in joined, "狼人讨论泄露到公开时间线"
    assert "使用解药" not in joined, "女巫用药泄露到公开时间线"


def test_cites_always_point_to_existing_events() -> None:
    result = run_game(5)
    total = len(result.events)
    for event in result.events:
        if isinstance(event, Spoke):
            for cite in event.cites:
                assert 0 <= cite < total


def test_normalize_cites_extracts_digits_and_drops_invalid() -> None:
    engine = Engine(agent_factory=lambda seat, role: RandomAgent(), seed=0)
    for i in range(5):
        engine.emit(ev.NightFell(round=i))

    cleaned = engine._normalize_cites(("999", "[3]", "第2条", "3"))
    assert cleaned == (3, 2), "越界的应丢掉，重复的应去重，顺序要保留"


def test_mock_agent_produces_citations_sometimes() -> None:
    """假模型也会引用，用来验证整条链路；至少要出现一次。"""
    client = MockClient(latency=0.0, seed=2)
    engine = Engine(agent_factory=lambda seat, role: LLMAgent(seat, role, client), seed=10)
    result = asyncio.run(engine.run())

    cited = [e for e in result.events if isinstance(e, Spoke) and e.cites]
    assert cited, "整局没有任何一条发言带引用，引用链路可能断了"
    for event in cited:
        assert all(isinstance(c, int) for c in event.cites)
