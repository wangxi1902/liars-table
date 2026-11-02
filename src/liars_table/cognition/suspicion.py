"""每个Agent独享的确定性怀疑度账本。

第一版只根据公开、可验证的行为更新分数。它不是“真狼人概率”，而是一组可解释、
可测试的启发式信号；LLM可以读取和解释，但不能直接覆盖历史分数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..core import events as ev
from ..roster import PlayerInfo


class SuspicionReason(StrEnum):
    """有限原因码便于前端展示和后续量化，而不是保存自由思维文本。"""

    UNSUPPORTED_ACCUSATION = "unsupported_accusation"
    GROUNDED_STATEMENT = "grounded_statement"
    CONFLICTING_ROLE_CLAIM = "conflicting_role_claim"
    UNEXPLAINED_VOTE = "unexplained_vote"
    VOTE_SHIFT = "vote_shift"


_REASON_TEXT: dict[SuspicionReason, str] = {
    SuspicionReason.UNSUPPORTED_ACCUSATION: "公开指控他人但没有引用事件依据",
    SuspicionReason.GROUNDED_STATEMENT: "发言引用了可核验的公开事件",
    SuspicionReason.CONFLICTING_ROLE_CLAIM: "与其他玩家出现身份声称冲突",
    SuspicionReason.UNEXPLAINED_VOTE: "投票前没有公开表达对目标的怀疑",
    SuspicionReason.VOTE_SHIFT: "与上一轮相比改变了投票目标",
}


@dataclass(frozen=True, slots=True)
class SuspicionChange:
    """一次分数变化；保留来源事件，支持前端引用和赛后审计。"""

    seat: str
    round: int
    event_id: int | None
    delta: int
    score_after: int
    reason: SuspicionReason
    summary: str


@dataclass
class SuspicionLedger:
    """某个观察者自己的怀疑账本，不在不同Agent之间共享。"""

    observer: str
    names: dict[str, str] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    changes: list[SuspicionChange] = field(default_factory=list)
    accusations: dict[str, set[str]] = field(default_factory=dict)
    role_claimants: dict[str, set[str]] = field(default_factory=dict)
    last_votes: dict[str, str] = field(default_factory=dict)
    base_score: int = 35

    @classmethod
    def from_roster(
        cls,
        observer: str,
        roster: dict[str, PlayerInfo],
        *,
        base_score: int = 35,
    ) -> SuspicionLedger:
        """所有其他玩家从相同中立分开始，观察者本人固定为0。"""
        scores = {seat: (0 if seat == observer else base_score) for seat in roster}
        return cls(
            observer=observer,
            names={seat: info.name for seat, info in roster.items()},
            scores=scores,
            base_score=base_score,
        )

    def score(self, seat: str) -> int:
        """未知座位也返回中立分，便于没有名册的轻量测试。"""
        if seat == self.observer:
            return 0
        return self.scores.get(seat, self.base_score)

    def observe(self, event: ev.Event, round_no: int, event_id: int | None = None) -> None:
        """根据一条可见事件增量更新；私有夜间事件不会命中任何分支。"""
        if isinstance(event, ev.Spoke):
            self._observe_speech(event, round_no, event_id)
        elif isinstance(event, ev.Voted):
            self._observe_vote(event, round_no, event_id)

    def recent_changes(
        self,
        seat: str,
        *,
        limit: int = 3,
        visible_event_ids: set[int] | None = None,
    ) -> tuple[SuspicionChange, ...]:
        """返回最近变化；公开卡片可以额外传入当前可见事件白名单。"""
        selected = [change for change in self.changes if change.seat == seat]
        if visible_event_ids is not None:
            selected = [
                change
                for change in selected
                if change.event_id is not None and change.event_id in visible_event_ids
            ]
        return tuple(selected[-limit:])

    def top(self, seats: tuple[str, ...], limit: int = 3) -> tuple[str, ...]:
        """按分数降序返回候选；同分时用座位号保证结果可复现。"""
        candidates = {seat for seat in seats if seat != self.observer}
        ordered = sorted(candidates, key=lambda seat: (-self.score(seat), seat))
        return tuple(ordered[:limit])

    def summary(self, seats: tuple[str, ...], limit: int = 4) -> str:
        """生成给模型看的简短摘要，不输出隐藏推理。"""
        lines = ["【怀疑度账本】分数只是公开行为信号，不等于真实身份概率"]
        for seat in self.top(seats, limit):
            label = self.names.get(seat, seat)
            changes = self.recent_changes(seat, limit=2)
            reasons = "；".join(
                f"{change.delta:+d} {_REASON_TEXT[change.reason]}" for change in changes
            )
            suffix = f"（{reasons}）" if reasons else "（暂无显著公开信号）"
            lines.append(f"  {label}：{self.score(seat)}/100 {suffix}")
        return "\n".join(lines)

    def _observe_speech(
        self,
        event: ev.Spoke,
        round_no: int,
        event_id: int | None,
    ) -> None:
        accusations = {
            claim.target
            for claim in event.claims
            if claim.kind == "accuse" and claim.target is not None
        }
        if accusations:
            self.accusations.setdefault(event.player, set()).update(accusations)
            delta = -2 if event.cites else 7
            reason = (
                SuspicionReason.GROUNDED_STATEMENT
                if event.cites
                else SuspicionReason.UNSUPPORTED_ACCUSATION
            )
            self._change(event.player, round_no, event_id, delta, reason)

        for claim in event.claims:
            if claim.kind != "claim_role" or claim.role is None:
                continue
            claimants = self.role_claimants.setdefault(str(claim.role), set())
            others = claimants - {event.player}
            if others:
                self._change(
                    event.player,
                    round_no,
                    event_id,
                    10,
                    SuspicionReason.CONFLICTING_ROLE_CLAIM,
                )
                for other in sorted(others):
                    self._change(
                        other,
                        round_no,
                        event_id,
                        5,
                        SuspicionReason.CONFLICTING_ROLE_CLAIM,
                    )
            claimants.add(event.player)

    def _observe_vote(
        self,
        event: ev.Voted,
        round_no: int,
        event_id: int | None,
    ) -> None:
        previous = self.last_votes.get(event.voter)
        if previous is not None and previous != event.target:
            self._change(
                event.voter,
                round_no,
                event_id,
                5,
                SuspicionReason.VOTE_SHIFT,
            )
        accused = self.accusations.get(event.voter, set())
        if event.target not in accused:
            self._change(
                event.voter,
                round_no,
                event_id,
                4,
                SuspicionReason.UNEXPLAINED_VOTE,
            )
        self.last_votes[event.voter] = event.target

    def _change(
        self,
        seat: str,
        round_no: int,
        event_id: int | None,
        delta: int,
        reason: SuspicionReason,
    ) -> None:
        if seat == self.observer:
            return
        before = self.score(seat)
        after = max(0, min(100, before + delta))
        self.scores[seat] = after
        self.changes.append(
            SuspicionChange(
                seat=seat,
                round=round_no,
                event_id=event_id,
                delta=after - before,
                score_after=after,
                reason=reason,
                summary=_REASON_TEXT[reason],
            )
        )
