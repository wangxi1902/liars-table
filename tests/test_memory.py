import asyncio
import random

from liars_table.agents.llm_agent import LLMAgent
from liars_table.agents.random_agent import RandomAgent
from liars_table.core.events import (
    DawnBroke,
    GameStarted,
    PlayerSpec,
    SeerChecked,
    Spoke,
    Voted,
)
from liars_table.core.roles import Camp, Role
from liars_table.engine import Engine
from liars_table.llm.client import MockClient
from liars_table.memory import MemoryItem, MemoryStore, dice, tokenize

# ------------------------------------------------------------------ 特征提取


def test_tokenize_extracts_seats_keywords_and_bigrams() -> None:
    tokens = tokenize("P3 说 P7 是狼人")
    assert "p3" in tokens and "p7" in tokens
    assert "狼人" in tokens
    assert "是狼" in tokens  # 二字切分


def test_dice_similarity() -> None:
    assert dice({"a", "b"}, {"a", "b"}) == 1.0
    assert dice({"a"}, {"b"}) == 0.0
    assert dice(set(), {"a"}) == 0.0
    assert 0 < dice({"a", "b"}, {"b", "c"}) < 1


# ------------------------------------------------------------------ 记忆存储


def test_recall_prefers_recent_memory() -> None:
    store = MemoryStore()
    store.add(MemoryItem(round=1, kind="speech", text="P1 说：我是好人", importance=0.45))
    store.add(MemoryItem(round=3, kind="speech", text="P9 说：我是好人", importance=0.45))

    top = store.recall("我是好人", current_round=3, k=1)
    assert top[0].round == 3


def test_recall_prefers_relevant_memory() -> None:
    store = MemoryStore()
    store.add(MemoryItem(round=2, kind="speech", text="P3 是狼人", importance=0.5))
    store.add(MemoryItem(round=2, kind="speech", text="P7 是好人", importance=0.5))

    top = store.recall("P3 是不是狼", current_round=2, k=1)
    assert "P3" in top[0].text


def test_importance_can_beat_recency() -> None:
    """验人结果（重要性 1.0）应该压过一句旧闲话（0.45）。"""
    store = MemoryStore()
    store.add(
        MemoryItem(
            round=1,
            kind="seer_checked",
            text="你查验了 P4，结果是 wolf 阵营",
            importance=1.0,
        )
    )
    store.add(MemoryItem(round=3, kind="speech", text="P6 说：我先过", importance=0.45))

    top = store.recall("随便", current_round=3, k=1)
    assert top[0].kind == "seer_checked"


def test_store_trims_to_max_items() -> None:
    store = MemoryStore(max_items=3)
    for i in range(10):
        store.add(MemoryItem(round=i, kind="speech", text=f"第{i}条", importance=0.4))
    assert len(store) == 3
    assert store.recent(1)[0].round == 9


# ------------------------------------------------------------------ 事件转记忆


def test_from_event_ignores_uninteresting_events() -> None:
    started = GameStarted(seed=1, players=(PlayerSpec("P1", "阿飞", Role.SEER),))
    assert MemoryItem.from_event(started, "P1", 0) is None


def test_from_event_formats_public_events() -> None:
    item = MemoryItem.from_event(Spoke(player="P3", text="我怀疑 P5"), "P1", 2)
    assert item is not None
    assert "P3" in item.text and "我怀疑 P5" in item.text
    assert item.about == ("P3",)

    voted = MemoryItem.from_event(Voted(voter="P1", target="P4"), "P1", 2)
    assert voted is not None and "P4" in voted.text

    dawn = MemoryItem.from_event(DawnBroke(round=2, deaths=("P6",)), "P1", 2)
    assert dawn is not None and "P6" in dawn.text


# ------------------------------------------------------------------ 可见性（防作弊）


def test_private_events_never_leak_to_other_players() -> None:
    seen: dict[str, list[str]] = {}
    holder: dict[str, Engine] = {}

    def factory(seat: str, role):
        inner = RandomAgent(random.Random(seat))

        class Spy:
            def observe(self, event, round_no: int) -> None:
                seen.setdefault(seat, []).append(event.kind)

            async def decide(self, request):
                return await inner.decide(request)

        return Spy()

    engine = Engine(agent_factory=factory, seed=5)
    holder["engine"] = engine
    asyncio.run(engine.run())

    roles = engine.state.roles
    seer = next(s for s, r in roles.items() if r is Role.SEER)
    witch = next(s for s, r in roles.items() if r is Role.WITCH)
    wolves = {s for s, r in roles.items() if r is Role.WEREWOLF}

    for seat, kinds in seen.items():
        if seat != seer:
            assert "seer_checked" not in kinds, f"{seat} 偷看到了验人结果"
        if seat != witch:
            assert "witch_acted" not in kinds, f"{seat} 偷看到了女巫用药"
        if seat not in wolves:
            assert "wolf_chose" not in kinds, f"{seat} 偷看到了狼队讨论"


# ------------------------------------------------------------------ Agent 集成


def test_llm_agent_records_memory_when_observing() -> None:
    agent = LLMAgent("P1", Role.SEER, MockClient())
    assert len(agent.memory) == 0

    agent.observe(SeerChecked(seer="P1", target="P3", camp=Camp.WOLF), 1)

    assert len(agent.memory) == 1
    item = agent.memory.recent(1)[0]
    assert item.importance == 1.0
    assert "P3" in item.text


def test_memory_grows_during_a_whole_game() -> None:
    client = MockClient(latency=0.0, seed=1)
    engine = Engine(
        agent_factory=lambda seat, role: LLMAgent(seat, role, client),
        seed=8,
    )
    asyncio.run(engine.run())

    # 每个 agent 至少记住了自己的发言和投票
    for seat, agent in engine.agents.items():
        assert len(agent.memory) > 0, f"{seat} 一条记忆都没有"
