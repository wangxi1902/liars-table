"""The rules engine.

Design rule: the engine owns the *flow*, agents only own the *decisions*.
Every step is an event, so replays and counterfactuals come for free.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .agents.base import Agent, Decision, DecisionRequest
from .core import events as ev
from .core.roles import CAMP_OF, TEMPLATE_9, Camp, Phase, Role
from .core.rules import check_winner, tally, top_voted
from .core.state import GameState, apply


@dataclass
class GameResult:
    state: GameState
    events: list[ev.Event]
    transcript: list[str]


class Engine:
    def __init__(
        self,
        agent_factory: Callable[[str, Role], Agent],
        roles: Sequence[Role] = TEMPLATE_9,
        seed: int = 0,
        max_rounds: int = 20,
        on_event: Callable[[ev.Event], None] | None = None,
    ) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        role_list = list(roles)
        self.rng.shuffle(role_list)

        self._roles = role_list
        self._factory = agent_factory
        self._max_rounds = max_rounds
        self._on_event = on_event

        self.state = GameState()
        self.events: list[ev.Event] = []
        self.transcript: list[str] = []
        self.notes: dict[str, list[str]] = {}
        self.agents: dict[str, Agent] = {}

    # ------------------------------------------------------------------ plumbing

    def emit(self, event: ev.Event) -> ev.Event:
        self.events.append(event)
        apply(self.state, event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def _note(self, seat: str, text: str) -> None:
        self.notes.setdefault(seat, []).append(text)

    def _ask(
        self,
        seat: str,
        kind: str,
        legal: Sequence[str],
        context: dict | None = None,
    ) -> Decision:
        request = DecisionRequest(
            kind=kind,
            seat=seat,
            role=self.state.roles[seat],
            round=self.state.round,
            legal=tuple(legal),
            context=dict(context or {}),
            transcript=tuple(self.transcript[-24:]),
            notes=tuple(self.notes.get(seat, ())[-12:]),
        )
        decision = self.agents[seat].decide(request)
        if decision.target is not None and decision.target not in legal:
            return replace(decision, target=None)
        return decision

    def _pick(self, seat: str, kind: str, legal: Sequence[str], context: dict | None = None) -> str:
        if not legal:
            raise RuntimeError(f"no legal target for {kind!r} ({seat})")
        decision = self._ask(seat, kind, legal, context)
        return decision.target if decision.target is not None else self.rng.choice(list(legal))

    def _majority(self, votes: dict[str, str], fallback: Sequence[str]) -> str:
        counts = Counter(votes.values())
        if not counts:
            return self.rng.choice(list(fallback))
        best = max(counts.values())
        leaders = [seat for seat, n in counts.items() if n == best]
        return self.rng.choice(leaders)

    # ------------------------------------------------------------------ game flow

    def run(self) -> GameResult:
        specs = tuple(ev.PlayerSpec(f"P{i}", role) for i, role in enumerate(self._roles, start=1))
        self.emit(ev.GameStarted(seed=self.seed, players=specs))
        for spec in specs:
            self.agents[spec.seat] = self._factory(spec.seat, spec.role)

        while self.state.winner is None and self.state.round < self._max_rounds:
            night_deaths = self._night()
            if self.state.winner is not None:
                break
            self._day(night_deaths)

        if self.state.winner is None:
            self.emit(
                ev.GameEnded(winner=Camp.WOLF, reason=f"超过 {self._max_rounds} 轮，判狼人胜")
            )
        return GameResult(state=self.state, events=self.events, transcript=self.transcript)

    def _night(self) -> list[tuple[str, str]]:
        self.emit(ev.NightFell(round=self.state.round + 1))
        round_no = self.state.round

        wolves = self.state.seats_with_role(Role.WEREWOLF)
        prey = [s for s in self.state.alive_sorted() if s not in wolves]
        proposals = {}
        for wolf in wolves:
            teammates = [s for s in wolves if s != wolf]
            target = self._pick(wolf, "kill", prey, {"teammates": teammates})
            proposals[wolf] = target
            self.emit(ev.WolfChose(wolf=wolf, target=target))
        victim = self._majority(proposals, prey)
        self.emit(ev.WolfKilled(target=victim))

        self._seer_turn(round_no)
        saved, poison = self._witch_turn(victim, round_no)

        deaths: list[tuple[str, str]] = []
        if not saved:
            deaths.append((victim, "wolf"))
        if poison is not None:
            deaths.append((poison, "poison"))

        killed: list[tuple[str, str]] = []
        for seat, cause in deaths:
            if self.state.is_alive(seat):
                self._kill(seat, cause)
                killed.append((seat, cause))
        killed.extend(self._hunter_chain([seat for seat, _ in killed]))

        winner = check_winner(self.state)
        if winner is not None:
            self._end(winner)
        return killed

    def _seer_turn(self, round_no: int) -> None:
        seers = self.state.seats_with_role(Role.SEER)
        if not seers:
            return
        seer = seers[0]
        legal = [s for s in self.state.alive_sorted() if s != seer]
        if not legal:
            return
        target = self._pick(seer, "check", legal)
        camp = CAMP_OF[self.state.roles[target]]
        self.emit(ev.SeerChecked(seer=seer, target=target, camp=camp))
        self._note(seer, f"第{round_no}夜查验：{target} 属于 {camp.value} 阵营")

    def _witch_turn(self, victim: str, round_no: int) -> tuple[bool, str | None]:
        witches = self.state.seats_with_role(Role.WITCH)
        if not witches:
            return False, None
        witch = witches[0]
        legal = [s for s in self.state.alive_sorted() if s != witch]
        context = {
            "victim": victim,
            "has_antidote": self.state.witch_antidote,
            "has_poison": self.state.witch_poison,
        }
        decision = self._ask(witch, "witch", legal, context)
        saved = bool(decision.save and self.state.witch_antidote)
        poison = decision.target if self.state.witch_poison else None
        if poison is not None and poison not in legal:
            poison = None
        if saved:
            poison = None  # 同一夜不能既用解药又用毒药
        self.emit(ev.WitchActed(witch=witch, save=saved, poison=poison))

        note = f"第{round_no}夜：被袭击的是 {victim}"
        if saved:
            note += "，你使用了解药"
        if poison is not None:
            note += f"，你对 {poison} 使用了毒药"
        self._note(witch, note)
        return saved, poison

    def _kill(self, seat: str, cause: str) -> None:
        self.emit(ev.PlayerDied(player=seat, cause=cause))

    def _hunter_chain(self, dead_seats: list[str]) -> list[tuple[str, str]]:
        extra: list[tuple[str, str]] = []
        for seat in dead_seats:
            if self.state.roles.get(seat) is not Role.HUNTER:
                continue
            legal = self.state.alive_sorted()
            if not legal:
                self.emit(ev.HunterShot(hunter=seat, target=None))
                continue
            target = self._pick(seat, "shoot", legal)
            self.emit(ev.HunterShot(hunter=seat, target=target))
            if self.state.is_alive(target):
                self._kill(target, "hunter")
                extra.append((target, "hunter"))
        return extra

    def _day(self, night_deaths: list[tuple[str, str]]) -> None:
        seats = [seat for seat, _ in night_deaths]
        self.state.phase = Phase.DAWN
        self.emit(ev.DawnBroke(round=self.state.round, deaths=tuple(seats)))
        if seats:
            self.transcript.append(f"【第{self.state.round}天】昨晚出局：{'、'.join(seats)}")
        else:
            self.transcript.append(f"【第{self.state.round}天】平安夜")

        self.state.phase = Phase.DISCUSSION
        for seat in self.state.alive_sorted():
            decision = self._ask(seat, "speech", (), {"alive": self.state.alive_sorted()})
            text = decision.text.strip() or "（沉默）"
            self.emit(
                ev.Spoke(player=seat, text=text, claims=decision.claims, cites=decision.cites)
            )
            self.transcript.append(f"{seat}：{text}")

        self.state.phase = Phase.VOTING
        votes: dict[str, str] = {}
        for seat in self.state.alive_sorted():
            legal = [s for s in self.state.alive_sorted() if s != seat]
            if not legal:
                break
            target = self._pick(seat, "vote", legal)
            votes[seat] = target
            self.emit(ev.Voted(voter=seat, target=target))
            self.transcript.append(f"{seat} 投给 {target}")

        exiled = top_voted(votes)
        self.emit(ev.Exiled(player=exiled, tally=tuple(tally(votes))))
        if exiled is None:
            self.transcript.append("平票，本轮无人出局")
        else:
            self._kill(exiled, "vote")
            self.transcript.append(f"{exiled} 被投票出局")
            self._hunter_chain([exiled])

        winner = check_winner(self.state)
        if winner is not None:
            self._end(winner)

    def _end(self, winner: tuple[Camp, str]) -> None:
        camp, reason = winner
        self.emit(ev.GameEnded(winner=camp, reason=reason))
        self.transcript.append(f"【结束】{camp.value} 阵营获胜：{reason}")
