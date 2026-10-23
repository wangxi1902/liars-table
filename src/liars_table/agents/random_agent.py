"""A baseline agent that only makes legal moves. Used for rule-engine tests."""

from __future__ import annotations

import random

from .base import Decision, DecisionRequest

_SUSPICIONS = (
    "我觉得 {t} 昨晚的表现很可疑。",
    "我怀疑 {t}，他的发言一直在回避关键信息。",
    "{t} 的票型很奇怪，我先记下。",
    "我暂时站 {t} 是好人，先观察。",
)


class RandomAgent:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def decide(self, request: DecisionRequest) -> Decision:
        if request.kind == "speech":
            alive = [s for s in request.context.get("alive", ()) if s != request.seat]
            if alive:
                return Decision(text=self.rng.choice(_SUSPICIONS).format(t=self.rng.choice(alive)))
            return Decision(text="我先过。")

        if request.kind == "witch":
            save = bool(request.context.get("has_antidote")) and self.rng.random() < 0.3
            poison = None
            if (
                request.context.get("has_poison")
                and not save
                and request.legal
                and self.rng.random() < 0.15
            ):
                poison = self.rng.choice(request.legal)
            return Decision(save=save, target=poison)

        if request.legal:
            return Decision(target=self.rng.choice(request.legal))
        return Decision()
