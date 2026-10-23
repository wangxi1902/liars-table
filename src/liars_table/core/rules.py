"""Pure rules: who wins, how votes tally. No I/O, no randomness."""

from __future__ import annotations

from collections import Counter

from .roles import Camp, Role
from .state import GameState


def wolves_alive(state: GameState) -> list[str]:
    return [s for s in state.alive_sorted() if state.roles[s] is Role.WEREWOLF]


def good_alive(state: GameState) -> list[str]:
    return [s for s in state.alive_sorted() if state.roles[s] is not Role.WEREWOLF]


def check_winner(state: GameState) -> tuple[Camp, str] | None:
    """Return ``(camp, reason)`` when the game is decided, else ``None``."""
    wolves = len(wolves_alive(state))
    good = len(good_alive(state))
    if wolves == 0:
        return Camp.GOOD, "狼人全部出局"
    if wolves >= good:
        return Camp.WOLF, f"狼人({wolves})不少于好人({good})"
    return None


def tally(votes: dict[str, str]) -> list[tuple[str, int]]:
    """Vote counts, highest first, then by seat."""
    counts = Counter(votes.values())
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def top_voted(votes: dict[str, str]) -> str | None:
    """The single most-voted seat, or ``None`` when the vote is tied."""
    counts = Counter(votes.values())
    if not counts:
        return None
    best = max(counts.values())
    leaders = [seat for seat, n in counts.items() if n == best]
    return leaders[0] if len(leaders) == 1 else None
