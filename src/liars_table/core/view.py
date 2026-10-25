"""把事件翻译成"公开时间线"的一行文本。

为什么单独放一个文件？
    同一份事件流有三种读者：
      1. 命令行：要彩色、要分组（cli.py 自己处理）
      2. Agent  ：要**带编号**的公开时间线（本文件）
      3. 记忆   ：要"我这个视角"的描述（memory/models.py）
    三种需求混在一起会让格式化逻辑长成一团，所以拆开。

关键设计：**编号就是事件在 events 列表里的下标**。
    不额外维护一个自增 ID，是因为事件列表本身就是追加的、不可变的，
    下标天然稳定；回放时也一样能对上。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import events as ev
from .roles import CAUSE_ZH


@dataclass(frozen=True, slots=True)
class LogLine:
    """公开时间线的一行：编号 + 文本。"""

    seq: int
    text: str


def describe_public(event: ev.Event) -> str | None:
    """把公开事件翻译成一行文本；私有事件返回 None（不进公开时间线）。

    注意 ``PlayerDied`` 返回 None：夜里谁死了、怎么死的，要等天亮才公布。
    死亡的公开叙述由 ``DawnBroke``（夜里）和 ``Exiled``（投票）负责。
    """
    if isinstance(event, ev.GameStarted):
        return "游戏开始"

    if isinstance(event, ev.NightFell):
        return f"第 {event.round} 夜"

    if isinstance(event, ev.DawnBroke):
        if event.deaths:
            return f"天亮，出局：{'、'.join(event.deaths)}"
        return "天亮，平安夜"

    if isinstance(event, ev.Spoke):
        suffix = ""
        if event.cites:
            suffix = f"（引用 {','.join(str(c) for c in event.cites)}）"
        return f"{event.player}：{event.text}{suffix}"

    if isinstance(event, ev.Voted):
        return f"{event.voter} 投给 {event.target}"

    if isinstance(event, ev.Exiled):
        if event.player is None:
            return "投票平票，无人出局"
        return f"{event.player} 被投票放逐"

    if isinstance(event, ev.HunterShot):
        target = event.target or "无人"
        return f"猎人 {event.hunter} 开枪带走 {target}"

    if isinstance(event, ev.GameEnded):
        return f"游戏结束，{event.winner.value} 阵营获胜"

    # PlayerDied / WolfChose / WolfKilled / SeerChecked / WitchActed 都不公开
    return None


def cause_text(cause: str) -> str:
    """死因中文描述，给需要展示细节的地方用。"""
    return CAUSE_ZH.get(cause, cause)
