"""身份硬规则与可选策略分离测试。"""

from liars_table.agents.base import DecisionRequest
from liars_table.agents.prompts import build_messages
from liars_table.agents.role_guidance import (
    OPTIONAL_STRATEGY_IDEAS,
    ROLE_RULES,
    render_role_guidance,
)
from liars_table.core.roles import Role


def test_every_role_has_rules_and_optional_ideas() -> None:
    assert set(ROLE_RULES) == set(Role)
    assert set(OPTIONAL_STRATEGY_IDEAS) == set(Role)
    assert all(ROLE_RULES[role] for role in Role)


def test_guidance_explicitly_allows_no_strategy() -> None:
    text = render_role_guidance(Role.VILLAGER)

    assert "身份固定规则" in text
    assert "可选策略空间" in text
    assert "不是指令" in text
    assert "全部拒绝" in text
    assert "身份伪装" in text


def test_seer_rules_no_longer_force_immediate_reveal() -> None:
    rules = "".join(ROLE_RULES[Role.SEER])
    guidance = render_role_guidance(Role.SEER)

    assert "必须立刻" not in guidance
    assert "毫无价值" not in guidance
    assert "由你结合局势决定" in rules


def test_private_notes_are_information_not_mandatory_tactics() -> None:
    request = DecisionRequest(
        kind="speech",
        seat="P1",
        role=Role.SEER,
        round=2,
        context={"alive": ("P1", "P2")},
        notes=("你查验P2是狼人阵营",),
    )

    messages = build_messages(request)
    combined = "\n".join(message.content for message in messages)

    assert "现在就应该跳出来" not in combined
    assert "必须用起来" not in combined
    assert "收益和风险" in combined
