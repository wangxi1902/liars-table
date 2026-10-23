import json
import random

from liars_table.agents.random_agent import RandomAgent
from liars_table.core.events import GameEnded, PlayerDied
from liars_table.core.state import replay
from liars_table.engine import Engine, GameResult


def run_game(seed: int) -> GameResult:
    engine = Engine(
        agent_factory=lambda seat, role: RandomAgent(random.Random(f"{seed}:{seat}")),
        seed=seed,
    )
    return engine.run()


def test_every_game_terminates() -> None:
    for seed in range(40):
        result = run_game(seed)
        assert result.state.winner is not None, f"seed {seed} did not finish"
        assert isinstance(result.events[-1], GameEnded)


def test_replay_rebuilds_the_same_state() -> None:
    result = run_game(11)
    rebuilt = replay(result.events)
    assert rebuilt.alive == result.state.alive
    assert rebuilt.roles == result.state.roles
    assert rebuilt.winner == result.state.winner
    assert rebuilt.deaths == result.state.deaths


def test_same_seed_same_game() -> None:
    a = run_game(5)
    b = run_game(5)
    assert [e.to_dict() for e in a.events] == [e.to_dict() for e in b.events]


def test_events_are_json_serialisable() -> None:
    result = run_game(3)
    payload = json.dumps([e.to_dict() for e in result.events], ensure_ascii=False)
    assert "game_started" in payload and "game_ended" in payload


def test_players_only_act_while_alive() -> None:
    """A dead player must never speak or vote. The hunter is the one exception:
    he fires *after* dying, which is the rule, not a bug."""
    seen: list[tuple[str, str, bool]] = []
    holder: dict[str, Engine] = {}

    def factory(seat: str, role):
        inner = RandomAgent(random.Random(seat))

        class Spy:
            def decide(self, request):
                alive = holder["engine"].state.is_alive(request.seat)
                seen.append((request.seat, request.kind, alive))
                return inner.decide(request)

        return Spy()

    engine = Engine(agent_factory=factory, seed=3)
    holder["engine"] = engine
    engine.run()

    assert seen, "no decisions were recorded"
    for seat, kind, alive in seen:
        if kind == "shoot":
            continue
        assert alive, f"{seat} acted while dead ({kind})"


def test_deaths_are_never_duplicated() -> None:
    result = run_game(17)
    died = [e.player for e in result.events if isinstance(e, PlayerDied)]
    assert len(died) == len(set(died))
