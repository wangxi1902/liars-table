"""Roles, camps and phases. Pure data, no behaviour."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    VILLAGER = "villager"


class Camp(StrEnum):
    WOLF = "wolf"
    GOOD = "good"


class Phase(StrEnum):
    SETUP = "setup"
    NIGHT = "night"
    DAWN = "dawn"
    DISCUSSION = "discussion"
    VOTING = "voting"
    ENDED = "ended"


CAMP_OF: dict[Role, Camp] = {
    Role.WEREWOLF: Camp.WOLF,
    Role.SEER: Camp.GOOD,
    Role.WITCH: Camp.GOOD,
    Role.HUNTER: Camp.GOOD,
    Role.VILLAGER: Camp.GOOD,
}

ROLE_ZH: dict[Role, str] = {
    Role.WEREWOLF: "狼人",
    Role.SEER: "预言家",
    Role.WITCH: "女巫",
    Role.HUNTER: "猎人",
    Role.VILLAGER: "村民",
}

#: Standard 9-player board: 3 wolves, 3 specials, 3 villagers.
TEMPLATE_9: tuple[Role, ...] = (
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.SEER,
    Role.WITCH,
    Role.HUNTER,
    Role.VILLAGER,
    Role.VILLAGER,
    Role.VILLAGER,
)


def seat_key(seat: str) -> int:
    """Sort ``P10`` after ``P9`` instead of before ``P2``."""
    try:
        return int(seat[1:])
    except ValueError:
        return 0
