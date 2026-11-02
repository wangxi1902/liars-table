"""把模型给出的候选依据收窄成可以安全展示的决策快照。

模型只能提交“关注谁、怀疑度、引用哪个公开事件、依据类别”。事件摘要由后端从
``DecisionRequest.transcript`` 重新取得，模型无法把私有笔记或自由思维文本塞进前端。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from ..cognition import SuspicionLedger, SuspicionReason
from ..llm.schema import ActionPayload, BasisEvidence, EvidenceKind
from .base import DecisionRequest

_PUBLIC_LINE = re.compile(r"^\[(\d+)]\s*(.+)$")
_MAX_SUMMARY_LENGTH = 100


@dataclass(frozen=True, slots=True)
class SafeEvidence:
    """已确认存在于当前AI公开时间线中的一条依据。"""

    event_id: int
    kind: EvidenceKind
    summary: str
    reason: str
    delta: int = 0


@dataclass(frozen=True, slots=True)
class SafeAssessment:
    """前端可以展示的玩家怀疑度和依据。"""

    seat: str
    suspicion: int
    recent_delta: int
    evidence: tuple[SafeEvidence, ...]


@dataclass(frozen=True, slots=True)
class SafeDecisionBasis:
    """不含Prompt、原始模型回复和私密信息的决策依据快照。"""

    decision_id: str
    seat: str
    decision_kind: str
    focus_players: tuple[SafeAssessment, ...]
    planned_target: str | None
    visibility: str = "public"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DecisionBasisSink = Callable[[SafeDecisionBasis], None]
SeatResolver = Callable[[str | None], str | None]


def build_safe_decision_basis(
    request: DecisionRequest,
    payload: ActionPayload,
    *,
    planned_target: str | None,
    resolve_seat: SeatResolver,
    suspicion: SuspicionLedger | None = None,
    extra_visible_events: dict[int, str] | None = None,
) -> SafeDecisionBasis | None:
    """校验座位和事件可见性；没有可展示内容时返回 ``None``。"""
    if request.kind not in {"speech", "vote"}:
        return None

    visible_events = _visible_public_events(request.transcript)
    if extra_visible_events:
        # Agent曾经公开观察过、后来被压缩的旧发言仍可作为可审计依据。
        visible_events = {**extra_visible_events, **visible_events}
    allowed_seats = set(request.legal)
    allowed_seats.update(request.context.get("alive") or ())
    assessments: list[SafeAssessment] = []
    seen_seats: set[str] = set()

    candidates = payload.basis.assessments if payload.basis is not None else ()
    for candidate in candidates:
        seat = resolve_seat(candidate.seat)
        if seat is None or seat == request.seat or seat not in allowed_seats:
            continue
        if seat in seen_seats:
            continue
        evidence = _ledger_evidence(seat, suspicion, visible_events)
        if not evidence:
            evidence = _safe_model_evidence(candidate.evidence, visible_events)
        assessments.append(
            SafeAssessment(
                seat=seat,
                suspicion=suspicion.score(seat) if suspicion else candidate.suspicion,
                recent_delta=sum(item.delta for item in evidence),
                evidence=evidence,
            )
        )
        seen_seats.add(seat)

    if not assessments and suspicion is not None:
        ordered = suspicion.top(tuple(sorted(allowed_seats)), limit=1)
        for seat in ordered:
            evidence = _ledger_evidence(seat, suspicion, visible_events)
            assessments.append(
                SafeAssessment(
                    seat=seat,
                    suspicion=suspicion.score(seat),
                    recent_delta=sum(item.delta for item in evidence),
                    evidence=evidence,
                )
            )

    if not assessments:
        return None
    return SafeDecisionBasis(
        decision_id=uuid.uuid4().hex[:12],
        seat=request.seat,
        decision_kind=request.kind,
        focus_players=tuple(assessments),
        planned_target=planned_target,
    )


def _visible_public_events(transcript: tuple[str, ...]) -> dict[int, str]:
    """只接受引擎放进公开时间线的编号和文本。"""
    visible: dict[int, str] = {}
    for line in transcript:
        match = _PUBLIC_LINE.match(line)
        if match is None:
            continue
        event_id = int(match.group(1))
        summary = match.group(2).strip()[:_MAX_SUMMARY_LENGTH]
        visible[event_id] = summary
    return visible


def _safe_model_evidence(
    candidates: tuple[BasisEvidence, ...],
    visible_events: dict[int, str],
) -> tuple[SafeEvidence, ...]:
    """丢弃编造、重复或当前视角不可见的事件编号。"""
    result: list[SafeEvidence] = []
    seen: set[int] = set()
    for candidate in candidates:
        event_id = candidate.event_id
        if event_id in seen or event_id not in visible_events:
            continue
        result.append(
            SafeEvidence(
                event_id=event_id,
                kind=candidate.kind,
                summary=visible_events[event_id],
                reason="模型选择的公开依据",
            )
        )
        seen.add(event_id)
    return tuple(result)


_REASON_KIND: dict[SuspicionReason, EvidenceKind] = {
    SuspicionReason.UNSUPPORTED_ACCUSATION: EvidenceKind.STATEMENT,
    SuspicionReason.GROUNDED_STATEMENT: EvidenceKind.STATEMENT,
    SuspicionReason.CONFLICTING_ROLE_CLAIM: EvidenceKind.ROLE_CLAIM,
    SuspicionReason.UNEXPLAINED_VOTE: EvidenceKind.VOTE_PATTERN,
    SuspicionReason.VOTE_SHIFT: EvidenceKind.VOTE_PATTERN,
}


def _ledger_evidence(
    seat: str,
    ledger: SuspicionLedger | None,
    visible_events: dict[int, str],
) -> tuple[SafeEvidence, ...]:
    """账本原因优先；只取仍在当前公开上下文窗口内的来源事件。"""
    if ledger is None:
        return ()
    changes = ledger.recent_changes(
        seat,
        limit=3,
        visible_event_ids=set(visible_events),
    )
    return tuple(
        SafeEvidence(
            event_id=change.event_id,
            kind=_REASON_KIND[change.reason],
            summary=visible_events[change.event_id],
            reason=change.summary,
            delta=change.delta,
        )
        for change in changes
        if change.event_id is not None
    )
