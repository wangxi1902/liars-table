from liars_table.analysis import render_html
from liars_table.core.claims import Claim
from liars_table.core.events import (
    GameEnded,
    GameStarted,
    PlayerDied,
    PlayerSpec,
    SeerChecked,
    Spoke,
    WolfChose,
)
from liars_table.core.roles import Camp, Role
from liars_table.core.state import replay
from liars_table.engine import GameResult


def make_result() -> GameResult:
    players = (
        PlayerSpec("P1", "阿飞", Role.WEREWOLF),
        PlayerSpec("P2", "老K", Role.SEER),
        PlayerSpec("P3", "小北", Role.VILLAGER),
    )
    events = [
        GameStarted(seed=7, players=players),
        WolfChose(wolf="P1", target="P3"),
        SeerChecked(seer="P2", target="P1", camp=Camp.WOLF),
        PlayerDied(player="P3", cause="wolf"),
        Spoke(
            player="P1",
            text="我是好人<script>alert(1)</script>",
            claims=(Claim("accuse", target="P2"),),
        ),
        Spoke(player="P2", text="P1 是狼", claims=(Claim("accuse", target="P1"),)),
        GameEnded(winner=Camp.WOLF, reason="测试"),
    ]
    return GameResult(state=replay(events), events=events, transcript=[])


def test_html_is_self_contained() -> None:
    page = render_html(make_result())
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page and "<script>" in page
    assert "http://" not in page and "https://" not in page, "不能依赖外部资源"


def test_html_escapes_model_text() -> None:
    """模型输出可能带 HTML，必须转义，否则报告页会被注入。"""
    page = render_html(make_result())
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_private_events_render_in_god_mode_only() -> None:
    page = render_html(make_result())
    assert 'class="line private"' in page
    assert "查验" in page, "上帝视角内容应该存在于 HTML 中（默认由 CSS 隐藏）"


def test_accusation_matrix_has_numbers() -> None:
    page = render_html(make_result())
    assert "指控矩阵" in page
    assert "rgba(255,107,107" in page


def test_winner_and_players_are_present() -> None:
    page = render_html(make_result())
    assert "wolf" in page
    assert "P1" in page and "P2" in page and "P3" in page
