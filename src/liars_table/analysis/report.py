"""赛后复盘：把事件流变成可核对的分析结果。

分析只依赖**结构化数据**（事件、断言、引用），不调用模型。
这样做的好处是：结论可复现、可测试，也不会被模型的第二次幻觉污染。

目前能算出来的东西：
    - 谁指控了谁、被指控了多少次（指控矩阵）
    - 谁公开声称了什么身份、和真实身份是否相符（谎报检测）
    - 谁在引用自己的发言（无意义引用）
    - 整体引用率（发言是否"有据可查"）

Python 知识点：
    ``defaultdict(int)``
        访问不存在的键时自动给 0，省掉 ``if key not in d`` 的样板。
    ``dict.fromkeys(x)``
        用来去重并保持顺序。
    ``@property``
        ``exposed`` / ``citation_rate`` 是算出来的，不是存下来的。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..core.events import Spoke
from ..core.roles import ROLE_ZH, Role, seat_key
from ..engine import GameResult

#: 身份的内部值（seer/witch…）转中文，报告里要给人看
ROLE_ZH_BY_VALUE: dict[str, str] = {role.value: label for role, label in ROLE_ZH.items()}


@dataclass
class PlayerReport:
    """一个玩家的复盘数据。"""

    seat: str
    role: Role
    survived: bool
    name: str = ""
    speeches: int = 0
    cited: int = 0
    accused: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    accused_by: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    role_claims: list[str] = field(default_factory=list)

    @property
    def citation_rate(self) -> float:
        return self.cited / self.speeches if self.speeches else 0.0

    @property
    def exposed(self) -> bool:
        """是否声称过与自己真实身份不符的身份。

        注意：这不一定是"错"。狼人悍跳预言家是战术，村民诈身份也是战术。
        报告只负责指出"他说了自己不是的身份"，判断交给读者。
        """
        return any(claim != self.role.value for claim in self.role_claims)


@dataclass
class GameReport:
    """一局游戏的完整复盘。"""

    seed: int
    winner: str
    reason: str
    rounds: int
    players: list[PlayerReport]
    issues: list[str]
    total_speeches: int
    cited_speeches: int

    @property
    def citation_rate(self) -> float:
        return self.cited_speeches / self.total_speeches if self.total_speeches else 0.0


def build_report(result: GameResult) -> GameReport:
    """从对局结果生成复盘数据。"""
    state = result.state
    players = {
        seat: PlayerReport(
            seat=seat,
            name=state.names.get(seat, seat),
            role=state.roles[seat],
            survived=state.is_alive(seat),
        )
        for seat in sorted(state.roles, key=seat_key)
    }

    issues: list[str] = []
    total = 0
    cited = 0

    for index, event in enumerate(result.events):
        if not isinstance(event, Spoke):
            continue

        total += 1
        author = players[event.player]
        author.speeches += 1
        if event.cites:
            cited += 1
            author.cited += 1

        for claim in event.claims:
            if claim.kind == "accuse" and claim.target in players:
                author.accused[claim.target] += 1
                players[claim.target].accused_by[event.player] += 1
            elif claim.kind == "claim_role" and claim.role:
                author.role_claims.append(claim.role)

        # 引用自己说过的话：说明这条"证据"没有任何信息量
        for cite in event.cites:
            if 0 <= cite < len(result.events):
                target_event = result.events[cite]
                if isinstance(target_event, Spoke) and target_event.player == event.player:
                    issues.append(f"{event.player} 在第 {index} 号发言里引用了自己的话（[{cite}]）")

    for player in players.values():
        if player.exposed:
            claimed = "、".join(
                ROLE_ZH_BY_VALUE.get(value, value) for value in dict.fromkeys(player.role_claims)
            )
            issues.append(
                f"{player.seat}（真实身份：{ROLE_ZH[player.role]}）公开声称自己是：{claimed}"
            )
        if len(set(player.role_claims)) > 1:
            issues.append(f"{player.seat} 前后声称了不同身份，说法自相矛盾")

    # 预言家不跳身份 = 好人阵营失去信息源。
    # 注意要排除"压根没轮到发言就死了"的情况，那种不算打错。
    seer = next((p for p in players.values() if p.role is Role.SEER), None)
    if seer is not None and seer.speeches > 0 and not seer.role_claims:
        issues.append(f"{seer.seat} 是预言家但全程没有公开跳身份，好人阵营等于放弃信息源")

    if total and cited / total < 0.5:
        issues.append(f"整体引用率偏低：{cited}/{total} 条发言带证据（{cited / total:.0%}）")

    return GameReport(
        seed=state.seed,
        winner=state.winner.value if state.winner else "unknown",
        reason=state.reason,
        rounds=state.round,
        players=list(players.values()),
        issues=issues,
        total_speeches=total,
        cited_speeches=cited,
    )
