"""Immutable domain events.

Every state change in a game is one of these. Replaying the list rebuilds the
entire game, which is what makes replay, audit and counterfactual analysis
possible later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .roles import Camp, Role


@dataclass(frozen=True, slots=True)
class Event:
    kind: ClassVar[str] = "event"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = asdict(self)
        data["kind"] = self.kind
        return data


@dataclass(frozen=True, slots=True)
class PlayerSpec:
    seat: str
    role: Role


@dataclass(frozen=True, slots=True)
class GameStarted(Event):
    kind: ClassVar[str] = "game_started"
    seed: int
    players: tuple[PlayerSpec, ...]


@dataclass(frozen=True, slots=True)
class NightFell(Event):
    kind: ClassVar[str] = "night_fell"
    round: int


@dataclass(frozen=True, slots=True)
class WolfChose(Event):
    """A single wolf's proposal. Private: only wolves may see it."""

    kind: ClassVar[str] = "wolf_chose"
    wolf: str
    target: str


@dataclass(frozen=True, slots=True)
class WolfKilled(Event):
    kind: ClassVar[str] = "wolf_killed"
    target: str


@dataclass(frozen=True, slots=True)
class SeerChecked(Event):
    """Private: only the seer may see it."""

    kind: ClassVar[str] = "seer_checked"
    seer: str
    target: str
    camp: Camp


@dataclass(frozen=True, slots=True)
class WitchActed(Event):
    """Private: only the witch may see it."""

    kind: ClassVar[str] = "witch_acted"
    witch: str
    save: bool
    poison: str | None


@dataclass(frozen=True, slots=True)
class DawnBroke(Event):
    kind: ClassVar[str] = "dawn_broke"
    round: int
    deaths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerDied(Event):
    kind: ClassVar[str] = "player_died"
    player: str
    cause: str  # wolf | poison | vote | hunter


@dataclass(frozen=True, slots=True)
class Spoke(Event):
    kind: ClassVar[str] = "spoke"
    player: str
    text: str
    claims: tuple[str, ...] = ()
    cites: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Voted(Event):
    kind: ClassVar[str] = "voted"
    voter: str
    target: str


@dataclass(frozen=True, slots=True)
class Exiled(Event):
    kind: ClassVar[str] = "exiled"
    player: str | None
    tally: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class HunterShot(Event):
    kind: ClassVar[str] = "hunter_shot"
    hunter: str
    target: str | None


@dataclass(frozen=True, slots=True)
class GameEnded(Event):
    kind: ClassVar[str] = "game_ended"
    winner: Camp
    reason: str
