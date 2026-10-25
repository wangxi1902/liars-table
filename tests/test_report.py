from liars_table.analysis import build_report, render_markdown
from liars_table.core.claims import Claim
from liars_table.core.events import GameEnded, GameStarted, PlayerSpec, Spoke
from liars_table.core.roles import Camp, Role
from liars_table.core.state import replay
from liars_table.engine import GameResult
from liars_table.llm.schema import parse_action

# ------------------------------------------------------------------ 断言解析


def test_claim_from_structured_dict() -> None:
    claim = Claim.from_raw({"kind": "accuse", "target": "p3"})
    assert claim == Claim("accuse", target="P3"), "座位号要统一成大写"


def test_claim_from_role_dict() -> None:
    claim = Claim.from_raw({"kind": "claim_role", "role": "预言家"})
    assert claim == Claim("claim_role", role="seer")


def test_claim_from_text_fallback() -> None:
    assert Claim.from_raw("我是预言家，昨晚验了 P3") == Claim("claim_role", role="seer")
    assert Claim.from_raw("P5 肯定是狼") == Claim("accuse", target="P5")


def test_claim_returns_none_for_noise() -> None:
    assert Claim.from_raw("我先过") is None
    assert Claim.from_raw({"kind": "unknown"}) is None
    assert Claim.from_raw(42) is None


def test_schema_parses_structured_claims() -> None:
    payload = parse_action(
        '{"text": "我验了 P3", "claims": [{"kind": "accuse", "target": "P3"}]}'
    )
    assert payload is not None
    assert payload.claims == (Claim("accuse", target="P3"),)


# ------------------------------------------------------------------ 复盘


def make_result() -> GameResult:
    """手工造一局最小对局，方便断言。

    时间线：
        [0] 开局
        [1] P1 自称预言家（实际是狼）
        [2] P1 发言，引用了 [1]（引用自己）
        [3] P3 指控 P1
        [4] 结束
    """
    players = (
        PlayerSpec("P1", "阿飞", Role.WEREWOLF),
        PlayerSpec("P2", "老K", Role.SEER),
        PlayerSpec("P3", "小北", Role.VILLAGER),
    )
    events = [
        GameStarted(seed=99, players=players),
        Spoke(player="P1", text="我是预言家", claims=(Claim("claim_role", role="seer"),)),
        Spoke(player="P1", text="P2 是狼", claims=(Claim("accuse", target="P2"),), cites=(1,)),
        Spoke(player="P3", text="P1 有问题", claims=(Claim("accuse", target="P1"),), cites=(2,)),
        GameEnded(winner=Camp.WOLF, reason="测试"),
    ]
    return GameResult(state=replay(events), events=events, transcript=[])


def test_report_counts_accusations() -> None:
    report = build_report(make_result())
    by_seat = {p.seat: p for p in report.players}

    assert by_seat["P1"].accused["P2"] == 1
    assert by_seat["P2"].accused_by["P1"] == 1
    assert by_seat["P1"].accused_by["P3"] == 1


def test_report_flags_false_role_claim() -> None:
    report = build_report(make_result())
    p1 = next(p for p in report.players if p.seat == "P1")
    assert p1.exposed, "狼人自称预言家应该被标记出来"
    assert any("P1" in issue and "预言家" in issue for issue in report.issues)


def test_report_flags_self_citation() -> None:
    report = build_report(make_result())
    assert any("引用了自己的话" in issue for issue in report.issues)


def test_report_marks_survivors() -> None:
    report = build_report(make_result())
    assert all(p.survived for p in report.players), "这局没有死亡事件，应全部存活"


def test_markdown_contains_key_sections() -> None:
    markdown = render_markdown(build_report(make_result()))
    assert "# 复盘报告" in markdown
    assert "## 指控矩阵" in markdown
    assert "## 身份声称" in markdown
    assert "## 问题清单" in markdown
    assert "P1" in markdown
