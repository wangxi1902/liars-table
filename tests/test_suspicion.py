"""确定性怀疑度账本测试。"""

from liars_table.cognition import SuspicionLedger, SuspicionReason
from liars_table.core.claims import Claim
from liars_table.core.events import SeerChecked, Spoke, Voted
from liars_table.core.roles import Camp
from liars_table.roster import PlayerInfo


def _ledger(observer: str = "P1") -> SuspicionLedger:
    roster = {
        seat: PlayerInfo(seat, name, "🙂", hue)
        for seat, name, hue in (
            ("P1", "阿飞", 10),
            ("P2", "老K", 20),
            ("P3", "小北", 30),
        )
    }
    return SuspicionLedger.from_roster(observer, roster)


def test_unsupported_accusation_increases_suspicion() -> None:
    ledger = _ledger()
    ledger.observe(
        Spoke(player="P2", text="P3是狼", claims=(Claim("accuse", target="P3"),)),
        round_no=1,
        event_id=12,
    )

    assert ledger.score("P2") == 42
    change = ledger.recent_changes("P2")[0]
    assert change.event_id == 12
    assert change.reason == SuspicionReason.UNSUPPORTED_ACCUSATION


def test_cited_accusation_slightly_reduces_suspicion() -> None:
    ledger = _ledger()
    ledger.observe(
        Spoke(
            player="P2",
            text="根据上一轮票型，我怀疑P3",
            claims=(Claim("accuse", target="P3"),),
            cites=(8,),
        ),
        round_no=1,
        event_id=12,
    )

    assert ledger.score("P2") == 33
    assert ledger.recent_changes("P2")[0].delta == -2


def test_conflicting_role_claims_affect_both_claimants() -> None:
    ledger = _ledger()
    ledger.observe(
        Spoke(player="P2", text="我是预言家", claims=(Claim("claim_role", role="seer"),)),
        1,
        10,
    )
    ledger.observe(
        Spoke(player="P3", text="我才是预言家", claims=(Claim("claim_role", role="seer"),)),
        1,
        11,
    )

    assert ledger.score("P2") == 40
    assert ledger.score("P3") == 45


def test_unexplained_vote_and_vote_shift_accumulate() -> None:
    ledger = _ledger()
    ledger.observe(Voted(voter="P2", target="P3"), 1, 20)
    ledger.observe(Voted(voter="P2", target="P1"), 2, 30)

    assert ledger.score("P2") == 48
    assert [change.reason for change in ledger.recent_changes("P2")] == [
        SuspicionReason.UNEXPLAINED_VOTE,
        SuspicionReason.VOTE_SHIFT,
        SuspicionReason.UNEXPLAINED_VOTE,
    ]


def test_private_night_event_does_not_change_public_suspicion() -> None:
    ledger = _ledger()
    ledger.observe(SeerChecked(seer="P1", target="P2", camp=Camp.WOLF), 1, 5)

    assert ledger.score("P2") == 35
    assert ledger.changes == []


def test_observer_never_scores_themselves() -> None:
    ledger = _ledger(observer="P1")
    ledger.observe(
        Spoke(player="P1", text="P2是狼", claims=(Claim("accuse", target="P2"),)),
        1,
        9,
    )

    assert ledger.score("P1") == 0
    assert ledger.recent_changes("P1") == ()
