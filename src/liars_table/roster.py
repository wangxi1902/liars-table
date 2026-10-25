"""座位与名字/头像的映射。

为什么从 ``api/naming.py`` 挪出来？
    名字不只给前端看——prompt 里要让 AI 互相称呼名字，复盘里要显示名字。
    它现在是**跨层共享**的东西，放在 api 层会造成"引擎反向依赖 Web 层"。

确定性：同一个 seed、同一个座位，名字永远一样（刷新、重跑、回放都对得上）。
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

#: 20 个中文代号。每局从中随机抽 9 个（不重复），
#: 所以每局的人名组合都不一样，但同一 seed 一定抽出同一组。
NAMES: list[str] = [
    "老K",
    "阿岩",
    "小北",
    "铁头",
    "十三",
    "土豆",
    "冷面",
    "阿飞",
    "包子",
    "大熊",
    "老白",
    "阿鬼",
    "三炮",
    "小满",
    "钉子",
    "黑桃",
    "老猫",
    "阿水",
    "秃子",
    "二两",
]

#: emoji 头像池
EMOJIS: list[str] = [
    "🐺",
    "🦊",
    "🐼",
    "🐯",
    "🦁",
    "🐸",
    "🐙",
    "🦉",
    "🐗",
    "🐵",
    "🐶",
    "🐱",
]

_SEAT = re.compile(r"P(\d+)")
_SEAT_EXACT = re.compile(r"^[pP](\d+)$")


@dataclass(frozen=True, slots=True)
class PlayerInfo:
    seat: str
    name: str
    emoji: str
    hue: int

    def as_payload(self) -> dict:
        return asdict(self)


def hue_of(name: str) -> int:
    """由名字算稳定色相（0~359）。不能用 hash()，那个每个进程都变。"""
    return (sum(ord(ch) for ch in name) * 37) % 360


def build_roster(seed: int, seats: int = 9) -> dict[str, PlayerInfo]:
    """生成一局的名册，key 是座位（P1…Pn）。

    注意用 ``sample`` 而不是 ``shuffle``：**一局之内名字不能重复**。
    20 个名字里抽 9 个，每局组合都不同，但同 seed 必定同一组——
    这就是"随机分配 + 绑定后不变"。
    """
    rng = random.Random(seed * 7919 + 17)
    chosen = rng.sample(NAMES, min(seats, len(NAMES)))
    emojis = rng.sample(EMOJIS, min(seats, len(EMOJIS)))

    roster: dict[str, PlayerInfo] = {}
    for index in range(seats):
        name = chosen[index] if index < len(chosen) else f"玩家{index + 1}"
        roster[f"P{index + 1}"] = PlayerInfo(
            seat=f"P{index + 1}",
            name=name,
            emoji=emojis[index] if index < len(emojis) else "🙂",
            hue=hue_of(name),
        )
    return roster


def name_of(roster: dict[str, PlayerInfo], seat: str) -> str:
    info = roster.get(seat)
    return info.name if info else seat


def substitute(text: str, roster: dict[str, PlayerInfo]) -> str:
    """把文本里的 P3 换成"阿飞"。给 prompt、复盘、前端共用。"""

    def repl(match: re.Match[str]) -> str:
        seat = f"P{int(match.group(1))}"
        return name_of(roster, seat)

    return _SEAT.sub(repl, text)


def seat_of(value: str | None, roster: dict[str, PlayerInfo]) -> str | None:
    """把模型给的"P3"或"阿飞"统一成 P3。认不出来返回 None。

    为什么需要它？一旦 prompt 里出现名字，模型就会用名字回答，
    而引擎内部只有座位号。这里做一次归一化。
    """
    if not value:
        return None
    text = str(value).strip()

    exact = _SEAT_EXACT.match(text)
    if exact:
        return f"P{int(exact.group(1))}"

    # "P3（阿飞）" 这种混合写法：优先取座位号
    found = _SEAT.search(text)
    if found:
        seat = f"P{int(found.group(1))}"
        if seat in roster or not roster:
            return seat

    # 只有名字：反查座位
    for seat, info in roster.items():
        if info.name == text:
            return seat

    return None
