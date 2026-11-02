"""结构化决策依据的可见性与防幻觉测试。"""

from liars_table.agents.base import DecisionRequest
from liars_table.agents.decision_basis import build_safe_decision_basis
from liars_table.cognition import SuspicionLedger
from liars_table.core.claims import Claim
from liars_table.core.events import Spoke
from liars_table.core.roles import Role
from liars_table.llm.schema import ActionPayload


def _request() -> DecisionRequest:
    return DecisionRequest(
        kind="speech",
        seat="P1",
        role=Role.VILLAGER,
        round=2,
        context={"alive": ("P1", "P2", "P3")},
        transcript=(
            "[12] P2：我没有额外信息",
            "[18] P3 投给了 P2",
        ),
        notes=("[7] 只有自己知道的查验结果",),
    )


def test_safe_basis_uses_public_event_text_and_drops_fake_ids() -> None:
    payload = ActionPayload.from_dict(
        {
            "basis": {
                "assessments": [
                    {
                        "seat": "P2",
                        "suspicion": 72,
                        "evidence": [
                            {"event_id": 12, "kind": "statement"},
                            {"event_id": 7, "kind": "behavior"},
                            {"event_id": 999, "kind": "behavior"},
                        ],
                    }
                ]
            }
        }
    )

    safe = build_safe_decision_basis(
        _request(), payload, planned_target="P2", resolve_seat=lambda value: value
    )

    assert safe is not None
    assert safe.focus_players[0].seat == "P2"
    assert [item.event_id for item in safe.focus_players[0].evidence] == [12]
    assert safe.focus_players[0].evidence[0].summary == "P2：我没有额外信息"
    assert "查验" not in str(safe.to_dict())


def test_safe_basis_drops_self_and_non_alive_players() -> None:
    payload = ActionPayload.from_dict(
        {
            "basis": {
                "assessments": [
                    {"seat": "P1", "suspicion": 50},
                    {"seat": "P9", "suspicion": 90},
                ]
            }
        }
    )

    safe = build_safe_decision_basis(
        _request(), payload, planned_target=None, resolve_seat=lambda value: value
    )

    assert safe is None


def test_ledger_score_overrides_model_score_and_adds_auditable_reason() -> None:
    ledger = SuspicionLedger(observer="P1")
    ledger.observe(
        Spoke(player="P2", text="P3是狼", claims=(Claim("accuse", target="P3"),)),
        round_no=2,
        event_id=12,
    )
    payload = ActionPayload.from_dict(
        {
            "basis": {
                "assessments": [
                    {"seat": "P2", "suspicion": 99, "evidence": []}
                ]
            }
        }
    )

    safe = build_safe_decision_basis(
        _request(),
        payload,
        planned_target=None,
        resolve_seat=lambda value: value,
        suspicion=ledger,
    )

    assert safe is not None
    assessment = safe.focus_players[0]
    assert assessment.suspicion == 42
    assert assessment.recent_delta == 7
    assert assessment.evidence[0].reason == "公开指控他人但没有引用事件依据"


def test_compressed_old_public_speech_remains_citable() -> None:
    request = _request()
    payload = ActionPayload.from_dict(
        {
            "basis": {
                "assessments": [
                    {
                        "seat": "P2",
                        "suspicion": 60,
                        "evidence": [{"event_id": 3, "kind": "statement"}],
                    }
                ]
            }
        }
    )

    safe = build_safe_decision_basis(
        request,
        payload,
        planned_target=None,
        resolve_seat=lambda value: value,
        extra_visible_events={3: "P2：更早但仍被压缩记住的公开发言"},
    )

    assert safe is not None
    assert safe.focus_players[0].evidence[0].event_id == 3
