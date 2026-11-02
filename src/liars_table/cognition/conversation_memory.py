"""单个Agent视角的有限对话记忆。

完整事件流由Engine永久保存；本模块只模拟玩家有限的工作记忆：最近发言保留原文，
溢出的旧发言按说话人压缩，自身公开承诺额外长期保存。所有摘要保留来源事件编号。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import events as ev
from ..core.claims import Claim
from ..roster import PlayerInfo
from .suspicion import SuspicionLedger


@dataclass(frozen=True, slots=True)
class ConversationMemoryConfig:
    """有限记忆容量；后续可以从CLI/API动态覆盖。"""

    recent_speeches: int = 4
    own_recent_speeches: int = 2
    max_sources_per_speaker: int = 12
    max_self_commitments: int = 16
    excerpt_chars: int = 100

    def __post_init__(self) -> None:
        for name, value in (
            ("recent_speeches", self.recent_speeches),
            ("own_recent_speeches", self.own_recent_speeches),
            ("max_sources_per_speaker", self.max_sources_per_speaker),
            ("max_self_commitments", self.max_self_commitments),
            ("excerpt_chars", self.excerpt_chars),
        ):
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0")


@dataclass(frozen=True, slots=True)
class SpeechRecord:
    """仍在工作记忆中的一条完整公开发言。"""

    event_id: int
    round: int
    speaker: str
    text: str
    claims: tuple[Claim, ...]
    cites: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SelfCommitment:
    """自己公开表达过的身份、指控或立场承诺。"""

    event_id: int
    round: int
    kind: str
    value: str


@dataclass
class SpeakerDigest:
    """某名玩家溢出工作记忆后的结构化压缩结果。"""

    speaker: str
    speech_count: int = 0
    last_round: int = 0
    source_summaries: dict[int, str] = field(default_factory=dict)
    accusations: dict[str, int] = field(default_factory=dict)
    role_claims: list[str] = field(default_factory=list)


@dataclass
class ConversationMemory:
    """一名观察者独享的最近原文、旧摘要和自我承诺。"""

    observer: str
    names: dict[str, str] = field(default_factory=dict)
    config: ConversationMemoryConfig = field(default_factory=ConversationMemoryConfig)
    recent: list[SpeechRecord] = field(default_factory=list)
    own_recent: list[SpeechRecord] = field(default_factory=list)
    digests: dict[str, SpeakerDigest] = field(default_factory=dict)
    self_commitments: list[SelfCommitment] = field(default_factory=list)

    @classmethod
    def from_roster(
        cls,
        observer: str,
        roster: dict[str, PlayerInfo],
        *,
        config: ConversationMemoryConfig | None = None,
    ) -> ConversationMemory:
        return cls(
            observer=observer,
            names={seat: info.name for seat, info in roster.items()},
            config=config or ConversationMemoryConfig(),
        )

    def observe(self, event: ev.Event, round_no: int, event_id: int | None) -> None:
        """只记录带全局编号的公开发言，其他事件由Facts和MemoryStore负责。"""
        if not isinstance(event, ev.Spoke) or event_id is None:
            return
        record = SpeechRecord(
            event_id=event_id,
            round=round_no,
            speaker=event.player,
            text=event.text,
            claims=event.claims,
            cites=event.cites,
        )
        self.recent.append(record)
        if len(self.recent) > self.config.recent_speeches:
            self._compress(self.recent.pop(0))

        if event.player == self.observer:
            self.own_recent.append(record)
            del self.own_recent[: -self.config.own_recent_speeches]
            self._remember_self_commitments(record)

    def evidence_summaries(self) -> dict[int, str]:
        """返回仍能回忆的公开发言摘要，供引用白名单和思考卡片使用。"""
        evidence: dict[int, str] = {}
        for digest in self.digests.values():
            evidence.update(digest.source_summaries)
        for record in self.recent:
            evidence[record.event_id] = self._event_summary(record)
        return evidence

    def render_prompt(self, suspicion: SuspicionLedger | None = None) -> str:
        """把个人记忆渲染成Prompt片段；旧记录只显示压缩信息。"""
        lines: list[str] = []
        if self.recent:
            lines.append("【最近完整发言】")
            lines.extend(
                f"  #{record.event_id} {self._label(record.speaker)}：{record.text}"
                for record in self.recent
            )

        if self.digests:
            lines.append("【更早发言的个人压缩记忆】")
            for speaker in sorted(self.digests):
                digest = self.digests[speaker]
                sources = ",".join(f"#{event_id}" for event_id in digest.source_summaries)
                details = [f"共{digest.speech_count}次，来源{sources}"]
                if digest.accusations:
                    accused = "、".join(
                        f"{self._label(target)}×{count}"
                        for target, count in sorted(digest.accusations.items())
                    )
                    details.append(f"公开指控：{accused}")
                if digest.role_claims:
                    details.append("身份声称：" + "、".join(digest.role_claims))
                if suspicion is not None:
                    details.append(f"我当前的狼人嫌疑：{suspicion.score(speaker)}/100")
                last_excerpt = next(reversed(digest.source_summaries.values()))
                details.append(f"最近摘要：{last_excerpt}")
                lines.append(f"  {self._label(speaker)}｜" + "；".join(details))

        if self.own_recent or self.self_commitments:
            lines.append("【我自己的公开发言与承诺】")
            lines.extend(
                f"  最近原文 #{record.event_id}：{record.text}" for record in self.own_recent
            )
            lines.extend(
                f"  承诺 #{item.event_id}：{item.kind} {item.value}"
                for item in self.self_commitments
            )
        return "\n".join(lines)

    def _compress(self, record: SpeechRecord) -> None:
        digest = self.digests.setdefault(record.speaker, SpeakerDigest(record.speaker))
        digest.speech_count += 1
        digest.last_round = record.round
        digest.source_summaries[record.event_id] = self._event_summary(record)
        while len(digest.source_summaries) > self.config.max_sources_per_speaker:
            oldest = next(iter(digest.source_summaries))
            del digest.source_summaries[oldest]

        for claim in record.claims:
            if claim.kind == "accuse" and claim.target:
                digest.accusations[claim.target] = digest.accusations.get(claim.target, 0) + 1
            elif claim.kind == "claim_role" and claim.role:
                if claim.role not in digest.role_claims:
                    digest.role_claims.append(claim.role)

    def _remember_self_commitments(self, record: SpeechRecord) -> None:
        for claim in record.claims:
            value = claim.target if claim.kind == "accuse" else claim.role
            if value:
                self.self_commitments.append(
                    SelfCommitment(record.event_id, record.round, claim.kind, value)
                )
        del self.self_commitments[: -self.config.max_self_commitments]

    def _event_summary(self, record: SpeechRecord) -> str:
        text = record.text.strip()
        if len(text) > self.config.excerpt_chars:
            text = text[: self.config.excerpt_chars].rstrip() + "…"
        return f"{record.speaker}：{text}"

    def _label(self, seat: str) -> str:
        name = self.names.get(seat)
        return f"{seat}（{name}）" if name else seat
