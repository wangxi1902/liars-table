"""Game state and the fold that derives it from events."""

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
    seed: int = 0
    round: int = 0
    phase: Phase = Phase.SETUP
    roles: dict[str, Role] = field(default_factory=dict)
    alive: set[str] = field(default_factory=set)
    deaths: list[tuple[str, str]] = field(default_factory=list)
    witch_antidote: bool = True
    witch_poison: bool = True
    winner: Camp | None = None
    reason: str = ""

    def alive_sorted(self) -> list[str]:
        return sorted(self.alive, key=seat_key)

    def seats_with_role(self, role: Role) -> list[str]:
        return [s for s in self.alive_sorted() if self.roles[s] is role]

    def camp_of(self, seat: str) -> Camp:
        return CAMP_OF[self.roles[seat]]

    def is_alive(self, seat: str) -> bool:
        return seat in self.alive


def apply(state: GameState, event: Event) -> GameState:
    """Fold one event into ``state`` in place."""
    if isinstance(event, GameStarted):
        state.seed = event.seed
        state.roles = {p.seat: p.role for p in event.players}
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
    """Rebuild state from scratch. This is the audit path, not the hot path."""
    state = GameState()
    for event in events:
        apply(state, event)
    return state
