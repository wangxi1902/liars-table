"""The agent interface.

An agent only ever sees a :class:`DecisionRequest`: its own role, the public
transcript, its private notes and the legal target set. It never gets the raw
``GameState``, so it cannot cheat by reading other players' roles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.roles import Role


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    kind: str  # kill | check | witch | speech | vote | shoot
    seat: str
    role: Role
    round: int
    legal: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    transcript: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    target: str | None = None
    save: bool = False
    text: str = ""
    claims: tuple[str, ...] = ()
    cites: tuple[str, ...] = ()


class Agent(Protocol):
    def decide(self, request: DecisionRequest) -> Decision: ...
