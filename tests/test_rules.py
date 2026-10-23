from liars_table.core.roles import TEMPLATE_9, Camp, Role
from liars_table.core.rules import check_winner, tally, top_voted
from liars_table.core.state import GameState


def make_state(roles: list[Role]) -> GameState:
    state = GameState()
    state.roles = {f"P{i}": role for i, role in enumerate(roles, start=1)}
    state.alive = set(state.roles)
    return state


def test_template_9_shape() -> None:
    assert len(TEMPLATE_9) == 9
    assert TEMPLATE_9.count(Role.WEREWOLF) == 3
    assert TEMPLATE_9.count(Role.VILLAGER) == 3
    assert set(TEMPLATE_9) == {Role.WEREWOLF, Role.SEER, Role.WITCH, Role.HUNTER, Role.VILLAGER}


def test_good_wins_when_all_wolves_dead() -> None:
    state = make_state([Role.SEER, Role.WITCH, Role.VILLAGER])
    winner = check_winner(state)
    assert winner is not None
    assert winner[0] is Camp.GOOD


def test_wolf_wins_on_parity() -> None:
    state = make_state([Role.WEREWOLF, Role.WEREWOLF, Role.VILLAGER])
    winner = check_winner(state)
    assert winner is not None
    assert winner[0] is Camp.WOLF


def test_game_still_running() -> None:
    state = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER, Role.VILLAGER])
    assert check_winner(state) is None


def test_tally_and_tie() -> None:
    votes = {"P1": "P3", "P2": "P3", "P3": "P1", "P4": "P1"}
    assert tally(votes) == [("P1", 2), ("P3", 2)]
    assert top_voted(votes) is None
    assert top_voted({"P1": "P3", "P2": "P3", "P3": "P1"}) == "P3"
