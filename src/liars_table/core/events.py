"""不可变事件（Event）的定义。

为什么要有“事件”？
    最直观的写法是直接改状态：``state.alive.remove("P3")``。
    但这样写有两个致命问题：
      1. 出 bug 后无法复盘——你不知道第 3 轮到底发生了什么；
      2. 想做“如果那轮投了别人会怎样”的反事实推演，无从下手。

    本项目的做法：把所有动作记成一条条**不可变事件**，
    当前局面 = 按顺序“重放”这些事件算出来的结果：
        events = [GameStarted, NightFell, WolfKilled, PlayerDied, ...]
        state  = replay(events)

    好处：回放、审计、复盘、反事实推演全部免费获得。

Python 知识点（本文件集中演示）：
    @dataclass(frozen=True, slots=True)
        - dataclass：自动生成 __init__ / __repr__ / __eq__，省掉大量样板代码
        - frozen=True：对象创建后属性不可改，从语言层面保证“事件不可变”
        - slots=True：限制对象只能有声明过的属性，内存更省，写错属性名会立刻报错
    ClassVar[str]
        - 声明“这是类变量，不属于任何一个实例”，dataclass 不会把它算成构造参数
    asdict(self)
        - 把 dataclass 递归转换成普通 dict，方便写 JSON 落盘
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .claims import Claim
from .roles import Camp, Role


@dataclass(frozen=True, slots=True)
class Event:
    """所有事件的基类。

    这里只做两件事：声明一个 ``kind`` 类变量用于序列化，以及提供 ``to_dict``。
    注意 ``kind`` 用 ``ClassVar`` 标注——它不是字段，所以不会出现在构造函数里。
    """

    kind: ClassVar[str] = "event"

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典，例如写 JSONL 事件流。"""
        data: dict[str, Any] = asdict(self)
        data["kind"] = self.kind
        return data


@dataclass(frozen=True, slots=True)
class PlayerSpec:
    """开局时每个座位的身份与名字。

    名字写进事件而不是只放内存：这样回放、复盘、报告都能还原
    "P3 当时叫阿飞"这件事——绑定关系是**游戏记录的一部分**，不是临时变量。
    """

    seat: str
    name: str
    role: Role


@dataclass(frozen=True, slots=True)
class GameStarted(Event):
    """开局。之后所有事件都建立在这份身份分配之上。"""

    kind: ClassVar[str] = "game_started"
    seed: int
    players: tuple[PlayerSpec, ...]


@dataclass(frozen=True, slots=True)
class NightFell(Event):
    """天黑，进入第 N 夜。回合数是靠这个事件推进的。"""

    kind: ClassVar[str] = "night_fell"
    round: int


@dataclass(frozen=True, slots=True)
class WolfTalk(Event):
    """狼队夜聊的一句话。私有事件：只有狼人能看到。

    和 WolfChose 的区别：Talk 是"说出来的意见"（可以有理由、可以反对队友），
    Chose 是"最终投给谁"。分开记，复盘时才能看出狼队内部的博弈。
    """

    kind: ClassVar[str] = "wolf_talk"
    wolf: str
    text: str


@dataclass(frozen=True, slots=True)
class WolfChose(Event):
    """单个狼人的提议。私有事件：只有狼人能看到。"""

    kind: ClassVar[str] = "wolf_chose"
    wolf: str
    target: str


@dataclass(frozen=True, slots=True)
class WolfKilled(Event):
    """狼人多数决后最终确定的刀口。"""

    kind: ClassVar[str] = "wolf_killed"
    target: str


@dataclass(frozen=True, slots=True)
class SeerChecked(Event):
    """预言家验人结果。私有事件：只有预言家能看到。"""

    kind: ClassVar[str] = "seer_checked"
    seer: str
    target: str
    camp: Camp


@dataclass(frozen=True, slots=True)
class WitchActed(Event):
    """女巫的用药决定。私有事件：只有女巫能看到。

    ``save`` 和 ``poison`` 不可能同时为真——规则不允许一夜间既救人又毒人。
    """

    kind: ClassVar[str] = "witch_acted"
    witch: str
    save: bool
    poison: str | None


@dataclass(frozen=True, slots=True)
class DawnBroke(Event):
    """天亮，公布昨夜出局名单。空元组表示平安夜。"""

    kind: ClassVar[str] = "dawn_broke"
    round: int
    deaths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerDied(Event):
    """某个玩家出局。``cause`` 取值：wolf / poison / vote / hunter。"""

    kind: ClassVar[str] = "player_died"
    player: str
    cause: str


@dataclass(frozen=True, slots=True)
class Spoke(Event):
    """一次发言。

    ``claims`` 和 ``cites`` 是为复盘准备的：
      - claims：这句话里声称了什么（例如“P3 是狼”）
      - cites ：引用了哪几条事件作为依据。**必须是事件编号**（整数），
                由引擎校验：编造出来的编号会被直接丢掉。
    有了它们，赛后才能画出“谁在撒谎、哪句话露的馅”。
    """

    kind: ClassVar[str] = "spoke"
    player: str
    text: str
    claims: tuple[Claim, ...] = ()
    cites: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Voted(Event):
    """一张选票。"""

    kind: ClassVar[str] = "voted"
    voter: str
    target: str


@dataclass(frozen=True, slots=True)
class Exiled(Event):
    """投票结果。``player`` 为 None 表示平票、无人出局。

    ``tally`` 存的是 (座位, 票数) 的排序结果，方便前端直接画柱状图。
    """

    kind: ClassVar[str] = "exiled"
    player: str | None
    tally: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class HunterShot(Event):
    """猎人开枪。target 为 None 表示无人可带。"""

    kind: ClassVar[str] = "hunter_shot"
    hunter: str
    target: str | None


@dataclass(frozen=True, slots=True)
class GameEnded(Event):
    """游戏结束。"""

    kind: ClassVar[str] = "game_ended"
    winner: Camp
    reason: str
