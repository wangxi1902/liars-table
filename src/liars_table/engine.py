"""规则引擎：唯一负责“流程”的地方。

设计原则：**引擎管流程，Agent 管决策。**
    很多 LLM 项目的失败原因是让模型自己决定“现在该天黑了还是该投票了”。
    模型一旦跑偏，整局就乱。所以这里把流程写死成状态机：

        夜（狼刀 → 预言家验人 → 女巫用药）
          ↓
        天亮（公布死讯）
          ↓
        白天（依次发言 → 全体投票 → 放逐）
          ↓
        胜负判定，未结束则回到“夜”

    模型只能回答“刀谁 / 验谁 / 说什么 / 投谁”，永远碰不到流程本身。

阅读顺序：run() → _night() → _day()，其余都是辅助方法。

Python 知识点：
    Callable[[str, Role], Agent]
        函数类型注解。表示“接收 (座位, 身份) 两个参数、返回 Agent 的可调用对象”。
        这里用工厂函数而不是直接传 agent 列表，是因为 agent 必须先知道自己的身份
        才能被创建。
    list[tuple[str, str]]
        列表里装元组，例如 ``[("P3", "wolf"), ("P5", "poison")]``。
    @dataclass
        GameResult 只是个数据袋子，用 dataclass 比手写 __init__ 清楚。
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
    """一局打完后的产物：最终状态、完整事件流、人类可读的战报。"""

    state: GameState
    events: list[ev.Event]
    transcript: list[str]


class Engine:
    """一局游戏的调度器。

    典型用法::

        engine = Engine(agent_factory=..., seed=7)
        result = engine.run()

    注意：Engine 是**有状态**的，一个实例只能跑一局。
    """

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

        # 洗牌分配身份。用独立 Random 实例而不是全局 random，
        # 是为了保证“同一个 seed 必然得到同一局”，测试才能复现。
        role_list = list(roles)
        self.rng.shuffle(role_list)

        self._roles = role_list
        self._factory = agent_factory
        self._max_rounds = max_rounds
        self._on_event = on_event  # 观察者回调，CLI 用它实时打印

        self.state = GameState()
        self.events: list[ev.Event] = []
        self.transcript: list[str] = []  # 给人类看的战报，和 events 并存
        self.notes: dict[str, list[str]] = {}  # 每个座位的私有笔记
        self.agents: dict[str, Agent] = {}

    # ---------------------------------------------------------------- 基础设施

    def emit(self, event: ev.Event) -> ev.Event:
        """发出一条事件：存档 → 折叠进状态 → 通知观察者。

        所有状态变化都必须经过这里，这是“状态 = fold(事件)”的唯一入口。
        """
        self.events.append(event)
        apply(self.state, event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def _note(self, seat: str, text: str) -> None:
        """给某个座位记一条私有笔记（例如预言家的验人结果）。"""
        self.notes.setdefault(seat, []).append(text)

    def _ask(
        self,
        seat: str,
        kind: str,
        legal: Sequence[str],
        context: dict | None = None,
    ) -> Decision:
        """向一个 Agent 提问，并做一次合法性兜底。

        注意这里喂给 agent 的是**裁剪过的信息**：公开战报 + 自己的笔记。
        它拿不到 self.state，所以读不到别人的身份。
        """
        request = DecisionRequest(
            kind=kind,
            seat=seat,
            role=self.state.roles[seat],
            round=self.state.round,
            legal=tuple(legal),
            context=dict(context or {}),
            transcript=tuple(self.transcript[-24:]),  # 只带最近 24 条，控制 prompt 长度
            notes=tuple(self.notes.get(seat, ())[-12:]),
        )
        decision = self.agents[seat].decide(request)

        # 防作弊第二道闸：目标不在合法列表里，直接丢弃，由 _pick 兜底随机
        if decision.target is not None and decision.target not in legal:
            return replace(decision, target=None)
        return decision

    def _pick(self, seat: str, kind: str, legal: Sequence[str], context: dict | None = None) -> str:
        """要一个合法的目标。Agent 给不出来（或给错）就随机兜底。

        “永远有合法动作可做”是引擎不崩的底线：
        LLM 输出乱码、超时、返回不存在的座位号，都在这里被吸收掉。
        """
        if not legal:
            raise RuntimeError(f"no legal target for {kind!r} ({seat})")
        decision = self._ask(seat, kind, legal, context)
        return decision.target if decision.target is not None else self.rng.choice(list(legal))

    def _majority(self, votes: dict[str, str], fallback: Sequence[str]) -> str:
        """多数决。平票时在并列最高里随机选一个。"""
        counts = Counter(votes.values())
        if not counts:
            return self.rng.choice(list(fallback))
        best = max(counts.values())
        leaders = [seat for seat, n in counts.items() if n == best]
        return self.rng.choice(leaders)

    # ---------------------------------------------------------------- 主流程

    def run(self) -> GameResult:
        """跑完一整局，返回结果。"""
        # 开局：先把身份固定下来，再据此创建每个 agent
        specs = tuple(ev.PlayerSpec(f"P{i}", role) for i, role in enumerate(self._roles, start=1))
        self.emit(ev.GameStarted(seed=self.seed, players=specs))
        for spec in specs:
            self.agents[spec.seat] = self._factory(spec.seat, spec.role)

        # 主循环：夜 → 白天，直到分出胜负或超过最大轮数
        while self.state.winner is None and self.state.round < self._max_rounds:
            night_deaths = self._night()
            if self.state.winner is not None:
                break  # 夜里可能已经结束（例如狼人数量追平好人）
            self._day(night_deaths)

        # 保险丝：理论上不应该走到这里，防止死循环
        if self.state.winner is None:
            self.emit(
                ev.GameEnded(winner=Camp.WOLF, reason=f"超过 {self._max_rounds} 轮，判狼人胜")
            )
        return GameResult(state=self.state, events=self.events, transcript=self.transcript)

    def _night(self) -> list[tuple[str, str]]:
        """一个夜晚。返回 [(出局者, 死因), ...]，供天亮时公布。"""
        self.emit(ev.NightFell(round=self.state.round + 1))
        round_no = self.state.round  # NightFell 已经把 round 推进了

        # ---- 1. 狼人各自的提议，然后多数决 ----
        wolves = self.state.seats_with_role(Role.WEREWOLF)
        # 狼人不能刀自己人，所以候选池排除了所有狼
        prey = [s for s in self.state.alive_sorted() if s not in wolves]
        proposals: dict[str, str] = {}
        for wolf in wolves:
            teammates = [s for s in wolves if s != wolf]
            target = self._pick(wolf, "kill", prey, {"teammates": teammates})
            proposals[wolf] = target
            self.emit(ev.WolfChose(wolf=wolf, target=target))
        victim = self._majority(proposals, prey)
        self.emit(ev.WolfKilled(target=victim))

        # ---- 2. 预言家验人 ----
        self._seer_turn(round_no)

        # ---- 3. 女巫用药 ----
        saved, poison = self._witch_turn(victim, round_no)

        # ---- 4. 结算死亡 ----
        deaths: list[tuple[str, str]] = []
        if not saved:
            deaths.append((victim, "wolf"))
        if poison is not None:
            deaths.append((poison, "poison"))

        killed: list[tuple[str, str]] = []
        for seat, cause in deaths:
            if self.state.is_alive(seat):  # 可能被救、也可能被同一个人重复计算
                self._kill(seat, cause)
                killed.append((seat, cause))

        # ---- 5. 猎人连锁（夜里死掉也可能开枪）----
        killed.extend(self._hunter_chain([seat for seat, _ in killed]))

        winner = check_winner(self.state)
        if winner is not None:
            self._end(winner)
        return killed

    def _seer_turn(self, round_no: int) -> None:
        """预言家验人。注意：预言家是在“死讯结算前”行动的。"""
        seers = self.state.seats_with_role(Role.SEER)
        if not seers:
            return  # 预言家已死
        seer = seers[0]
        legal = [s for s in self.state.alive_sorted() if s != seer]
        if not legal:
            return
        target = self._pick(seer, "check", legal)
        camp = CAMP_OF[self.state.roles[target]]
        self.emit(ev.SeerChecked(seer=seer, target=target, camp=camp))
        self._note(seer, f"第{round_no}夜查验：{target} 属于 {camp.value} 阵营")

    def _witch_turn(self, victim: str, round_no: int) -> tuple[bool, str | None]:
        """女巫用药。返回 (是否救人, 毒了谁)。

        规则：同一夜不能既用解药又用毒药；每种药整局只能用一次。
        """
        witches = self.state.seats_with_role(Role.WITCH)
        if not witches:
            return False, None
        witch = witches[0]
        legal = [s for s in self.state.alive_sorted() if s != witch]
        context = {
            "victim": victim,  # 女巫知道今晚谁被刀
            "has_antidote": self.state.witch_antidote,
            "has_poison": self.state.witch_poison,
        }
        decision = self._ask(witch, "witch", legal, context)

        saved = bool(decision.save and self.state.witch_antidote)
        poison = decision.target if self.state.witch_poison else None
        if poison is not None and poison not in legal:
            poison = None
        if saved:
            poison = None  # 强制规则：解药与毒药互斥
        self.emit(ev.WitchActed(witch=witch, save=saved, poison=poison))

        note = f"第{round_no}夜：被袭击的是 {victim}"
        if saved:
            note += "，你使用了解药"
        if poison is not None:
            note += f"，你对 {poison} 使用了毒药"
        self._note(witch, note)
        return saved, poison

    def _kill(self, seat: str, cause: str) -> None:
        """让一个人出局。只发事件，不直接改 state——状态由 apply 负责。"""
        self.emit(ev.PlayerDied(player=seat, cause=cause))

    def _hunter_chain(self, dead_seats: list[str]) -> list[tuple[str, str]]:
        """猎人死亡时开枪，可能再带走一个人。返回被额外带走的人。"""
        extra: list[tuple[str, str]] = []
        for seat in dead_seats:
            if self.state.roles.get(seat) is not Role.HUNTER:
                continue
            legal = self.state.alive_sorted()
            if not legal:
                self.emit(ev.HunterShot(hunter=seat, target=None))
                continue
            # 注意：此刻猎人已经死了，但这正是规则允许的“临终开枪”
            target = self._pick(seat, "shoot", legal)
            self.emit(ev.HunterShot(hunter=seat, target=target))
            if self.state.is_alive(target):
                self._kill(target, "hunter")
                extra.append((target, "hunter"))
        return extra

    def _day(self, night_deaths: list[tuple[str, str]]) -> None:
        """一个白天：公布死讯 → 依次发言 → 投票放逐。"""
        seats = [seat for seat, _ in night_deaths]
        self.state.phase = Phase.DAWN
        self.emit(ev.DawnBroke(round=self.state.round, deaths=tuple(seats)))
        if seats:
            self.transcript.append(f"【第{self.state.round}天】昨晚出局：{'、'.join(seats)}")
        else:
            self.transcript.append(f"【第{self.state.round}天】平安夜")

        # ---- 发言：按座位号顺序，每人一次 ----
        self.state.phase = Phase.DISCUSSION
        for seat in self.state.alive_sorted():
            decision = self._ask(seat, "speech", (), {"alive": self.state.alive_sorted()})
            text = decision.text.strip() or "（沉默）"
            self.emit(
                ev.Spoke(player=seat, text=text, claims=decision.claims, cites=decision.cites)
            )
            self.transcript.append(f"{seat}：{text}")

        # ---- 投票：不能投自己；平票则无人出局（简化规则）----
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
        """结束游戏并写明原因。"""
        camp, reason = winner
        self.emit(ev.GameEnded(winner=camp, reason=reason))
        self.transcript.append(f"【结束】{camp.value} 阵营获胜：{reason}")
