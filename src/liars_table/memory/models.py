"""记忆单元：Agent "记住"的最小单位。

一条记忆不是原始事件，而是**经过裁剪和打分的事件描述**：
    - 只保留这个 agent 当时能看到的那部分（可见性由引擎裁决）
    - 带上重要性分数（验人结果比一句闲话重要得多）

为什么不直接把 Event 存进记忆？
    因为 Event 是"系统视角"的完整结构，而记忆是"玩家视角"的自然语言。
    Agent 需要的是"第2夜队友提议刀P6"，而不是一个 frozen dataclass。

Python 知识点：
    classmethod 作为工厂
        ``from_event`` 是"从事件造记忆"的工厂方法，返回 None 表示"这条不用记"。
    tuple[str, ...]
        不可变序列。这里用 tuple 而不是 list，是为了让 MemoryItem 可以 frozen。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import events as ev
from ..core.roles import CAUSE_ZH


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """一条记忆。

    字段说明：
        round       发生在第几轮（用来算"新近度"）
        kind        事件类型（speech / vote / seer_checked …）
        text        给模型看的自然语言描述
        importance  重要性 0~1，人为设定的启发式分数
        about       涉及哪些座位，用于后续做关系图
    """

    round: int
    kind: str
    text: str
    importance: float
    about: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_event(cls, event: ev.Event, seat: str, round_no: int) -> MemoryItem | None:
        """把一个事件翻译成"这个座位视角"的记忆。返回 None 表示忽略。"""
        if isinstance(event, ev.WolfChose):
            return cls(
                round_no,
                "wolf_proposal",
                f"队友 {event.wolf} 提议袭击 {event.target}",
                0.7,
                (event.wolf, event.target),
            )

        if isinstance(event, ev.WolfTalk):
            return cls(
                round_no,
                "wolf_talk",
                f"队友 {event.wolf} 说：{event.text}",
                0.6,
                (event.wolf,),
            )

        if isinstance(event, ev.WolfKilled):
            return cls(round_no, "wolf_kill", f"狼队决定袭击 {event.target}", 0.85, (event.target,))

        if isinstance(event, ev.SeerChecked):
            return cls(
                round_no,
                "seer_checked",
                f"你查验了 {event.target}，结果是 {event.camp.value} 阵营",
                1.0,
                (event.target,),
            )

        if isinstance(event, ev.WitchActed):
            parts = []
            if event.save:
                parts.append("你使用了解药救人")
            if event.poison is not None:
                parts.append(f"你对 {event.poison} 使用毒药")
            text = "，".join(parts) if parts else "你今晚没有用药"
            return cls(round_no, "witch_acted", text, 0.9, (event.poison,) if event.poison else ())

        if isinstance(event, ev.Spoke):
            return cls(
                round_no,
                "speech",
                f"{event.player} 说：{event.text}",
                0.45,
                (event.player,),
            )
        if isinstance(event, ev.Voted):
            return cls(
                round_no,
                "vote",
                f"{event.voter} 把票投给了 {event.target}",
                0.5,
                (event.voter, event.target),
            )

        if isinstance(event, ev.Exiled):
            if event.player is None:
                text = "投票平票，本轮无人出局"
                about: tuple[str, ...] = ()
            else:
                text = f"{event.player} 被投票放逐"
                about = (event.player,)
            return cls(round_no, "exiled", text, 0.95, about)

        if isinstance(event, ev.PlayerDied):
            cause = CAUSE_ZH.get(event.cause, event.cause)
            return cls(round_no, "death", f"{event.player} 出局（{cause}）", 0.9, (event.player,))

        if isinstance(event, ev.HunterShot):
            target = event.target or "无人"
            return cls(
                round_no,
                "hunter_shot",
                f"猎人 {event.hunter} 开枪带走 {target}",
                0.8,
                (event.hunter,),
            )

        if isinstance(event, ev.DawnBroke):
            if event.deaths:
                text = f"第{event.round}天天亮，出局：{'、'.join(event.deaths)}"
            else:
                text = f"第{event.round}天天亮，是平安夜"
            return cls(round_no, "dawn", text, 0.8, event.deaths)

        return None
