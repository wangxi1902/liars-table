"""游戏状态，以及“把事件折叠成状态”的 apply / replay。

核心思想：**状态不是被修改出来的，是被计算出来的。**

    state = GameState()
    for event in events:
        apply(state, event)

所有改状态的逻辑都集中在 ``apply`` 一个函数里，其他地方只准“发事件”。
这样只要事件流是对的，状态就一定是对的，回放也就一定一致。

Python 知识点：
    field(default_factory=set)
        可变的默认值必须用工厂函数。写成 ``alive: set[str] = set()`` 是经典错误：
        所有实例会共享同一个 set。``default_factory`` 每次创建新对象。
    set[str]
        集合，适合“存活玩家”这种需要频繁判断存在性的场景（O(1)）。
        ``discard`` 删除不存在的元素不会报错，比 ``remove`` 安全。
    isinstance(event, GameStarted)
        按类型分流。这里用 if/elif 而不是 match，因为可读性更好、也更好打断点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import (
    DawnBroke,
    Event,
    Exiled,
    GameEnded,
    GameStarted,
    NightFell,
    PlayerDied,
    WitchActed,
)
from .roles import CAMP_OF, Camp, Phase, Role, seat_key


@dataclass
class GameState:
    """一局游戏的完整快照。

    注意它和 Event 的区别：Event 是**不可变的历史**，GameState 是**可变的当前局面**。
    我们只在 apply 里改 GameState。
    """

    seed: int = 0
    round: int = 0
    phase: Phase = Phase.SETUP
    roles: dict[str, Role] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)  # 座位 → 名字，来自 GameStarted
    alive: set[str] = field(default_factory=set)
    deaths: list[tuple[str, str]] = field(default_factory=list)
    witch_antidote: bool = True  # 女巫的解药是否还在
    witch_poison: bool = True  # 女巫的毒药是否还在
    winner: Camp | None = None
    reason: str = ""

    def alive_sorted(self) -> list[str]:
        """按座位号排序的存活玩家。

        为什么要排序？因为 set 是无序的，同一局两次遍历顺序可能不同，
        会导致“发言顺序”和“随机种子”不稳定，测试就没法复现了。
        """
        return sorted(self.alive, key=seat_key)

    def seats_with_role(self, role: Role) -> list[str]:
        """找出当前存活玩家中拥有某身份的人（狼人可能不止一个）。"""
        return [s for s in self.alive_sorted() if self.roles[s] is role]

    def camp_of(self, seat: str) -> Camp:
        """查某个座位属于哪个阵营。"""
        return CAMP_OF[self.roles[seat]]

    def is_alive(self, seat: str) -> bool:
        """某个座位是否还活着。"""
        return seat in self.alive


def apply(state: GameState, event: Event) -> GameState:
    """把一条事件折叠进状态（原地修改并返回）。

    这是整个项目**唯一**允许修改 GameState 的地方。
    新增一种事件时，只需要在这里补一个分支。
    """
    if isinstance(event, GameStarted):
        state.seed = event.seed
        state.roles = {p.seat: p.role for p in event.players}
        state.names = {p.seat: p.name for p in event.players}
        state.alive = set(state.roles)
        state.phase = Phase.SETUP
    elif isinstance(event, NightFell):
        state.round = event.round
        state.phase = Phase.NIGHT
    elif isinstance(event, DawnBroke):
        state.phase = Phase.DAWN
    elif isinstance(event, PlayerDied):
        state.alive.discard(event.player)
        state.deaths.append((event.player, event.cause))
    elif isinstance(event, WitchActed):
        # 药一旦用掉就永久消耗，这是规则，不是状态机的副作用
        if event.save:
            state.witch_antidote = False
        if event.poison is not None:
            state.witch_poison = False
    elif isinstance(event, Exiled):
        state.phase = Phase.VOTING
    elif isinstance(event, GameEnded):
        state.winner = event.winner
        state.reason = event.reason
        state.phase = Phase.ENDED
    return state


def replay(events: list[Event]) -> GameState:
    """从零重放整局，得到最终状态。

    这是“审计路径”，不在热路径上，所以性能不重要、正确性最重要。
    测试里用它来验证：引擎边打边算的状态 == 重放事件得到的状态。
    """
    state = GameState()
    for event in events:
        apply(state, event)
    return state
