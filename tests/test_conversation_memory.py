"""个体化最近发言、旧摘要与自我承诺测试。"""

from liars_table.agents.base import DecisionRequest
from liars_table.agents.prompts import build_messages
from liars_table.cognition import ConversationMemory, ConversationMemoryConfig, SuspicionLedger
from liars_table.core.claims import Claim
from liars_table.core.events import SeerChecked, Spoke
from liars_table.core.roles import Camp, Role
from liars_table.memory import MemoryItem


def _memory(observer: str = "P1") -> ConversationMemory:
    return ConversationMemory(
        observer=observer,
        config=ConversationMemoryConfig(
            recent_speeches=2,
            own_recent_speeches=1,
            max_sources_per_speaker=3,
            max_self_commitments=4,
            excerpt_chars=30,
        ),
    )


def _speech(player: str, text: str, *claims: Claim) -> Spoke:
    return Spoke(player=player, text=text, claims=tuple(claims))


def test_recent_overflow_is_compressed_by_speaker() -> None:
    memory = _memory()
    memory.observe(_speech("P2", "第一条完整发言", Claim("accuse", target="P3")), 1, 10)
    memory.observe(_speech("P3", "第二条完整发言"), 1, 11)
    memory.observe(_speech("P2", "第三条把第一条挤出工作记忆"), 1, 12)

    assert [record.event_id for record in memory.recent] == [11, 12]
    digest = memory.digests["P2"]
    assert list(digest.source_summaries) == [10]
    assert digest.accusations == {"P3": 1}


def test_own_speech_keeps_recent_text_and_long_term_commitments() -> None:
    memory = _memory(observer="P1")
    memory.observe(_speech("P1", "我是预言家", Claim("claim_role", role="seer")), 1, 20)
    memory.observe(_speech("P1", "我现在怀疑P3", Claim("accuse", target="P3")), 2, 30)

    assert [record.event_id for record in memory.own_recent] == [30]
    assert [(item.kind, item.value) for item in memory.self_commitments] == [
        ("claim_role", "seer"),
        ("accuse", "P3"),
    ]


def test_private_event_is_not_stored_as_public_conversation() -> None:
    memory = _memory()
    memory.observe(SeerChecked(seer="P1", target="P2", camp=Camp.WOLF), 1, 8)

    assert memory.recent == []
    assert memory.digests == {}


def test_prompt_contains_full_recent_compressed_old_and_personal_score() -> None:
    memory = _memory()
    suspicion = SuspicionLedger(observer="P1")
    memory.observe(_speech("P2", "旧发言", Claim("accuse", target="P3")), 1, 10)
    memory.observe(_speech("P3", "最近发言一"), 1, 11)
    memory.observe(_speech("P2", "最近发言二"), 1, 12)
    suspicion.observe(_speech("P2", "无依据指控", Claim("accuse", target="P3")), 1, 10)

    text = memory.render_prompt(suspicion)

    assert "最近完整发言" in text and "#11" in text and "#12" in text
    assert "更早发言的个人压缩记忆" in text and "来源#10" in text
    assert "狼人嫌疑：42/100" in text


def test_each_agent_has_an_independent_memory() -> None:
    first = _memory(observer="P1")
    second = _memory(observer="P2")
    event = _speech("P3", "公开发言")

    first.observe(event, 1, 5)

    assert [record.event_id for record in first.recent] == [5]
    assert second.recent == []


def test_prompt_uses_personal_conversation_memory_instead_of_raw_window() -> None:
    memory = _memory()
    memory.observe(_speech("P2", "结构化记忆里的发言"), 1, 10)
    request = DecisionRequest(
        kind="speech",
        seat="P1",
        role=Role.VILLAGER,
        round=1,
        context={"alive": ("P1", "P2")},
        transcript=("[99] 不应重复注入的原始窗口",),
    )

    messages = build_messages(request, conversation_memory=memory)
    content = messages[-1].content

    assert "#10 P2：结构化记忆里的发言" in content
    assert "不应重复注入的原始窗口" not in content


def test_public_speech_is_not_duplicated_by_generic_memory_recall() -> None:
    memory = _memory()
    memory.observe(_speech("P2", "只应出现一次的发言"), 1, 10)
    recalled = (
        MemoryItem(1, "speech", "P2 说：只应出现一次的发言", 0.5, ("P2",)),
        MemoryItem(1, "dawn", "天亮后P3出局", 0.8, ("P3",)),
    )
    request = DecisionRequest(
        kind="speech",
        seat="P1",
        role=Role.VILLAGER,
        round=1,
        context={"alive": ("P1", "P2")},
    )

    content = build_messages(
        request,
        memories=recalled,
        conversation_memory=memory,
    )[-1].content

    assert content.count("只应出现一次的发言") == 1
    assert "天亮后P3出局" in content
