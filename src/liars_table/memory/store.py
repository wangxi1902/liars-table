"""记忆存储与检索。

这就是最小可用的 RAG：
    写入：事件发生时，把一条记忆塞进列表
    检索：决策前，按"新近度 + 重要性 + 相关性"打分，取前 k 条塞进 prompt

为什么先不上向量？
    相关性可以用**词面重叠**近似：中文没有空格，但可以用"座位号 + 关键词 + 二字切分"
    做出一个够用的相似度。它零依赖、可解释、跑得快。
    接口留成 ``recall`` 一个方法，将来换成 embedding 只改实现、不改调用方。

Python 知识点：
    re.findall / re.sub
        正则提取与替换。
    frozenset / set 运算
        ``a & b`` 求交集，``len()`` 求大小。
    sorted(..., key=lambda pair: ...)
        按指定键排序，reverse=True 表示降序。
    heapq.nlargest
        取前 k 大，比"全排序再切片"更适合大数据量（这里数据少，演示用）。
"""

from __future__ import annotations

import math
import re

from .models import MemoryItem

# 座位号：P1、P2……大小写都认
_SEAT_PATTERN = re.compile(r"p\d+", re.IGNORECASE)
# 领域关键词：这些词出现就说明两句话在聊同一件事
_KEYWORDS = (
    "狼人",
    "预言家",
    "女巫",
    "猎人",
    "村民",
    "好人",
    "查杀",
    "金水",
    "跳",
    "投票",
    "出局",
    "解药",
    "毒药",
    "袭击",
    "查验",
    "平票",
)
# 只保留中文，用来做二字切分
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> set[str]:
    """把一段中文变成"可比较的特征集合"。

    三路特征：
      1. 座位号（P3、P7）——最强的指代信号
      2. 领域关键词（狼人、查杀…）
      3. 中文字符二元组（"预言家" → 预言、言家）——近似"词"
    """
    lowered = text.lower()
    tokens: set[str] = set(_SEAT_PATTERN.findall(lowered))
    tokens.update(word for word in _KEYWORDS if word in text)

    for run in _CJK.findall(text):
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])

    return tokens


def dice(a: set[str], b: set[str]) -> float:
    """Dice 系数：两个集合的相似度，取值 0~1。

    公式：2 * |交集| / (|a| + |b|)
    比 Jaccard 更"宽容"一点，适合长短不一的句子。
    """
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


class MemoryStore:
    """一个 agent 的私有记忆。"""

    def __init__(self, max_items: int = 200, *, recency_decay: float = 0.85) -> None:
        self._items: list[MemoryItem] = []
        self.max_items = max_items
        self.recency_decay = recency_decay

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: MemoryItem) -> None:
        """写入一条记忆。超过上限时丢掉最旧的（近似"遗忘"）。"""
        self._items.append(item)
        if len(self._items) > self.max_items:
            self._items = self._items[-self.max_items :]

    def score(self, item: MemoryItem, query: set[str], current_round: int) -> float:
        """综合打分。三个权重是拍出来的，后续可以用评测集调。"""
        # 新近度：每过一轮衰减 15%，指数衰减比线性更符合直觉
        delta = max(0, current_round - item.round)
        recency = self.recency_decay**delta

        # 相关性：查询与记忆的词面重叠
        relevance = dice(query, tokenize(item.text))

        return 0.5 * recency + 0.3 * item.importance + 0.2 * relevance

    def recall(self, query_text: str, *, current_round: int, k: int = 6) -> list[MemoryItem]:
        """检索最相关的 k 条记忆，按分数降序。"""
        if not self._items:
            return []
        query = tokenize(query_text)
        scored = [(self.score(item, query, current_round), item) for item in self._items]
        # 二级排序键用 round，保证同分时结果确定（测试才能复现）
        scored.sort(key=lambda pair: (pair[0], pair[1].round), reverse=True)
        return [item for _, item in scored[:k]]

    def recent(self, n: int = 10) -> list[MemoryItem]:
        """最近 n 条，不做相关性排序。调试用。"""
        return self._items[-n:]

    def decayed(self, current_round: int, threshold: float = 0.1) -> int:
        """统计"已经太旧、可以清掉"的记忆条数（暂不实际删除）。"""
        return sum(
            1
            for item in self._items
            if math.pow(self.recency_decay, current_round - item.round) < threshold
        )
