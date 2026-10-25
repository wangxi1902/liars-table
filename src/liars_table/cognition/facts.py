"""结构化事实库：agent 眼里"场上到底发生了什么"。

为什么不用"最近 24 条原文"？
    狼人杀的关键信息是**关系和时间**，不是句子：
      - 谁在第几轮投了谁（票型能看出抱团）
      - 谁指控过谁、被谁指控（指控关系）
      - 谁声称过什么身份（对跳）
      - 谁什么时候出局
    这些用原文表达又长又难算；用结构存，一次查询就出来。

它和 memory 的区别：
    memory 是"模糊回忆"（按相关度召回几句话），facts 是"精确账本"（不丢、不错、可统计）。
    两者互补：facts 给骨架，memory 给细节。

只吃**公开事件**：死亡信息走 DawnBroke / Exiled / HunterShot，
不碰 PlayerDied（那个带死因，属于上帝视角）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import events as ev
from ..core.claims import Claim
from ..roster import PlayerInfo


@dataclass
class Facts:
    """一局游戏的事实账本。由 agent 在 observe 时增量维护。"""

    names: dict[str, str] = field(default_factory=dict)
    alive: list[str] = field(default_factory=list)
    deaths: list[tuple[str, str]] = field(default_factory=list)
    votes: dict[int, dict[str, str]] = field(default_factory=dict)
    claims: list[tuple[int, str, Claim]] = field(default_factory=list)
    accusations: dict[str, dict[str, int]] = field(default_factory=dict)
    round: int = 0

    @classmethod
    def from_roster(cls, roster: dict[str, PlayerInfo]) -> Facts:
        """用名册初始化：所有人活着、名字已知。

        为什么不从 GameStarted 事件初始化？那个事件里带着**所有身份**，
        广播给 agent 就是作弊。名册只有名字，安全。
        """
        return cls(
            names={seat: info.name for seat, info in roster.items()},
            alive=sorted(roster, key=lambda s: int(s[1:])),
        )

    # ---------------------------------------------------------------- 更新

    def observe(self, event: ev.Event) -> None:
        """吃一条公开事件，更新账本。"""
        if isinstance(event, ev.NightFell):
            self.round = event.round

        elif isinstance(event, ev.Spoke):
            for claim in event.claims:
                self.claims.append((self.round, event.player, claim))
                if claim.kind == "accuse" and claim.target:
                    per_target = self.accusations.setdefault(claim.target, {})
                    per_target[event.player] = per_target.get(event.player, 0) + 1

        elif isinstance(event, ev.Voted):
            self.votes.setdefault(self.round, {})[event.voter] = event.target

        elif isinstance(event, ev.DawnBroke):
            for seat in event.deaths:
                self._record_death(seat, f"第{event.round}夜")

        elif isinstance(event, ev.Exiled) and event.player:
            self._record_death(event.player, f"第{self.round}天被放逐")

        elif isinstance(event, ev.HunterShot) and event.target:
            self._record_death(event.target, "被猎人带走")

    def _record_death(self, seat: str, when: str) -> None:
        if seat in self.alive:
            self.alive.remove(seat)
        self.deaths.append((seat, when))

    # ---------------------------------------------------------------- 渲染

    def label(self, seat: str) -> str:
        name = self.names.get(seat)
        return f"{seat}（{name}）" if name else seat

    def short(self, seat: str) -> str:
        return self.names.get(seat, seat)

    def summary(self, recent_rounds: int = 2) -> str:
        """渲染成一段给模型看的态势摘要。控制长度，只留最近几轮票型。"""
        lines: list[str] = [f"【局势】第 {self.round} 轮"]

        if self.alive:
            lines.append("存活：" + "、".join(self.short(s) for s in self.alive))
        if self.deaths:
            gone = "、".join(f"{self.short(s)}（{when}）" for s, when in self.deaths[-6:])
            lines.append(f"出局：{gone}")

        if self.votes:
            lines.append("【票型】")
            for round_no in sorted(self.votes)[-recent_rounds:]:
                record = self.votes[round_no]
                pairs = "、".join(f"{self.short(v)}→{self.short(t)}" for v, t in record.items())
                lines.append(f"  第{round_no}轮：{pairs}")

        claims = [c for c in self.claims if c[2].kind == "claim_role"]
        if claims:
            lines.append("【身份声称】")
            for round_no, seat, claim in claims[-6:]:
                lines.append(f"  第{round_no}轮 {self.short(seat)} 自称 {claim.role}")

        if self.accusations:
            order = sorted(self.accusations.items(), key=lambda kv: -len(kv[1]))
            lines.append("【指控关系】")
            for target, accusers in order[:5]:
                who = "、".join(self.short(a) for a in accusers)
                lines.append(f"  {self.short(target)} 被 {len(accusers)} 人指控：{who}")

        return "\n".join(lines)
