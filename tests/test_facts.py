from liars_table.cognition import Facts
from liars_table.core.claims import Claim
from liars_table.core.events import (
    DawnBroke,
    Exiled,
    HunterShot,
    NightFell,
    Spoke,
    Voted,
)
from liars_table.roster import PlayerInfo


def make_roster() -> dict[str, PlayerInfo]:
    return {
        "P1": PlayerInfo("P1", "阿飞", "🐺", 10),
        "P2": PlayerInfo("P2", "老K", "🦊", 20),
        "P3": PlayerInfo("P3", "小北", "🐼", 30),
    }


def make_facts() -> Facts:
    return Facts.from_roster(make_roster())


def test_initial_state_from_roster() -> None:
    facts = make_facts()
    assert facts.alive == ["P1", "P2", "P3"]
    assert facts.names["P1"] == "阿飞"


def test_death_from_dawn_removes_player() -> None:
    facts = make_facts()
    facts.observe(NightFell(round=1))
    facts.observe(DawnBroke(round=1, deaths=("P2",)))

    assert "P2" not in facts.alive
    assert facts.deaths == [("P2", "第1夜")]


def test_death_from_exile_and_hunter() -> None:
    facts = make_facts()
    facts.observe(NightFell(round=1))
    facts.observe(Exiled(player="P3", tally=()))
    facts.observe(HunterShot(hunter="P1", target="P2"))

    assert facts.alive == ["P1"]
    assert {seat for seat, _ in facts.deaths} == {"P2", "P3"}


def test_votes_are_grouped_by_round() -> None:
    facts = make_facts()
    facts.observe(NightFell(round=1))
    facts.observe(Voted(voter="P1", target="P2"))
    facts.observe(Voted(voter="P2", target="P2"))
    facts.observe(NightFell(round=2))
    facts.observe(Voted(voter="P1", target="P3"))

    assert facts.votes[1] == {"P1": "P2", "P2": "P2"}
    assert facts.votes[2] == {"P1": "P3"}


def test_spoke_updates_claims_and_accusations() -> None:
    facts = make_facts()
    facts.observe(NightFell(round=1))
    facts.observe(
        Spoke(player="P1", text="我怀疑 P2", claims=(Claim("accuse", target="P2"),))
    )
    facts.observe(
        Spoke(
            player="P3",
            text="P2 是狼",
            claims=(Claim("accuse", target="P2"), Claim("claim_role", role="seer")),
        )
    )

    assert facts.accusations["P2"] == {"P1": 1, "P3": 1}
    assert any(claim.kind == "claim_role" for _, _, claim in facts.claims)


def test_summary_uses_names_and_sections() -> None:
    facts = make_facts()
    facts.observe(NightFell(round=1))
    facts.observe(Spoke(player="P1", text="我怀疑 P2", claims=(Claim("accuse", target="P2"),)))
    facts.observe(Voted(voter="P1", target="P2"))
    facts.observe(DawnBroke(round=1, deaths=("P3",)))

    text = facts.summary()

    assert "第 1 轮" in text
    assert "阿飞" in text and "老K" in text
    assert "【票型】" in text and "第1轮" in text
    assert "【指控关系】" in text
    assert "小北" in text  # 出局的人也要显示


def test_summary_omits_empty_sections() -> None:
    facts = make_facts()
    text = facts.summary()
    assert "【票型】" not in text
    assert "【指控关系】" not in text
