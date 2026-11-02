"""Prompt 拼装。

一个好的 Agent prompt 应该只有四块，按重要性排：
    1. 身份与目标（我是谁、我要赢）
    2. 规则约束（能做什么、不能做什么）
    3. 当前局势（公开发言 + 我的私密信息）
    4. 本次任务（现在要输出什么，格式是什么）

顺序很重要：稳定不变的内容放前面，能命中服务端的上下文缓存，省钱。

Python 知识点：
    dict[Role, str] 做"查表"
        比一长串 if/elif 干净得多，加角色时只改表。
    f-string 多行
        用三引号包住，再用 f 插值，比字符串拼接可读。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..agents.base import DecisionRequest
from ..cognition import ConversationMemory, Facts, SuspicionLedger
from ..core.roles import CAMP_OF, ROLE_ZH, Camp, Role
from ..llm.client import ChatMessage
from ..memory import MemoryItem
from ..roster import PlayerInfo, name_of, substitute
from .role_guidance import render_role_guidance


def _label(seat: str, roster: dict[str, PlayerInfo]) -> str:
    """``P3（阿飞）``。同时给座位号和名字，模型两种都能用。"""
    info = roster.get(seat)
    return f"{seat}（{info.name}）" if info else seat

#: 每个座位固定一种说话风格。
#: 为什么需要？真实对局里 9 个人说话方式完全不同，但同一套 prompt 会让模型
#: 收敛到同一个"安全模板句"。给座位绑定人设，是最便宜的破同质化手段。
PERSONAS: dict[str, str] = {
    "P1": "你说话直接，喜欢先手施压、逼人表态，句子短。",
    "P2": "你谨慎，凡事要证据，习惯先复述别人哪里矛盾再下结论。",
    "P3": "你擅长带节奏，喜欢把话题引向自己怀疑的人。",
    "P4": "你偏理性分析，爱算票型、算人数，说话像在记账。",
    "P5": "你情绪外放，容易激动，会为认定的好人强出头。",
    "P6": "你话少而冷，只在有把握时开口，一开口就下判断。",
    "P7": "你爱用反问，喜欢让对方先解释。",
    "P8": "你圆滑，习惯两头不得罪，但关键票会明确站边。",
    "P9": "你爱开玩笑缓和气氛，但会把关键的怀疑藏在玩笑里。",
}

KIND_TASK: dict[str, str] = {
    "kill": "现在是夜晚，请和队友一起选择今晚要击杀的玩家。",
    "check": "现在是夜晚，请选择今晚要查验身份的玩家。",
    "witch": "现在是夜晚，你看到了今晚被袭击的人。请决定是否使用解药，以及是否使用毒药。",
    "speech": "现在轮到你发言。用 1-2 句话表态：可以指控、辩解或站边，不要复述规则。"
    "如果你确定某人是狼，把它写进 claims；如果你想跳身份，也写进 claims。",
    "wolf_talk": "现在是狼队夜聊。先回应队友的意见，再说出你的判断："
    "刀谁收益最大、谁可能已经暴露身份、明天谁最该被推出去。"
    "然后给出你这一票要刀谁。",
    "vote": "现在是投票阶段，请选择你要放逐的玩家。",
    "shoot": "你已经出局，触发猎人技能，请选择要带走的玩家。",
}

KIND_SCHEMA: dict[str, str] = {
    "kill": '{"target": "座位号"}',
    "check": '{"target": "座位号"}',
    "vote": '{"target": "座位号"}',
    "wolf_talk": '{"text": "你在狼队里说的话", "target": "你建议刀谁"}',
    "shoot": '{"target": "座位号"}',
    "witch": '{"save": true 或 false, "target": "要毒杀的座位号，不用毒药就填 null"}',
    "speech": (
        '{"text": "你的发言", '
        '"claims": [{"kind": "accuse", "target": "P3"} 或 '
        '{"kind": "claim_role", "role": "seer"}], '
        '"cites": [事件编号整数，例如 12]}'
    ),
}

SYSTEM_RULES = """这是 9 人标准局狼人杀：3 狼人、1 预言家、1 女巫、1 猎人、3 村民。
胜负：狼人全部出局则好人胜；狼人数量不少于好人则狼人胜。
硬性要求：
1. 只能输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。
2. 只能从给定合法目标中选择，不要编造不存在的座位号。
3. 不要输出思考过程，只输出结果。
4. 不要复述别人刚说过的话，也不要使用"平安夜先别急着站边"这类套话；
   每次发言必须给出一个属于你自己的新判断（怀疑谁、为什么、接下来想听谁解释）。"""

BASIS_SCHEMA = (
    '同时增加 "basis": {"assessments": ['
    '{"seat": "公开怀疑的座位号", "suspicion": 0到100整数, '
    '"evidence": [{"event_id": 公开事件编号, "kind": "statement"}]}]}。'
    "最多关注3人，每人最多3条依据；kind只能是 statement、vote_pattern、"
    "role_claim、behavior。只能引用上方公开时间线编号，不能写私有身份、夜间信息或思考原文。"
)


def build_messages(
    request: DecisionRequest,
    memories: Sequence[MemoryItem] = (),
    roster: dict[str, PlayerInfo] | None = None,
    facts: Facts | None = None,
    suspicion: SuspicionLedger | None = None,
    conversation_memory: ConversationMemory | None = None,
) -> list[ChatMessage]:
    """把一次决策请求变成两条消息（system + user）。"""
    role = request.role
    camp = CAMP_OF[role]
    goal = "隐藏身份，误导好人，帮助狼队获胜。" if camp is Camp.WOLF else "找出并放逐所有狼人。"
    persona = PERSONAS.get(request.seat, "")
    roster = roster or {}
    me = name_of(roster, request.seat)

    system = (
        f"你正在参加一局狼人杀。你是 {request.seat}（{me}），身份是{ROLE_ZH[role]}。\n"
        f"{render_role_guidance(role)}\n"
        f"你的目标：{goal}\n"
        f"你的说话风格：{persona}\n\n"
        f"{SYSTEM_RULES}"
    )

    lines: list[str] = [f"当前是第 {request.round} 轮。"]
    alive = request.context.get("alive", ())
    if alive:
        lines.append(f"存活玩家：{'、'.join(_label(seat, roster) for seat in alive)}")

    if role is Role.WEREWOLF:
        teammates = request.context.get("teammates") or ()
        if teammates:
            lines.append(f"你的狼队友：{'、'.join(_label(seat, roster) for seat in teammates)}")

    # 狼队夜聊的记录：后置位要能读到前面队友说了什么，才能反驳/统一
    wolf_chat = request.context.get("wolf_chat") or []
    if wolf_chat:
        lines.append("\n【狼队内部讨论】")
        lines.extend(
            f"  第{index + 1}位 {_label(wolf, roster)}：{text}"
            for index, (wolf, text) in enumerate(wolf_chat)
        )

    if request.kind == "witch":
        victim = request.context.get("victim")
        lines.append(f"今晚被袭击的是：{victim}")
        lines.append(
            f"你还有解药：{'有' if request.context.get('has_antidote') else '没有'}；"
            f"你还有毒药：{'有' if request.context.get('has_poison') else '没有'}"
        )

    # 结构化态势负责精确事实；个体对话记忆负责最近原文和旧发言压缩。
    if facts is not None:
        lines.append("")
        lines.append(facts.summary())
        if conversation_memory is None and request.transcript:
            lines.append("\n最近几条发言（原文，开头 [数字] 是事件编号）：")
            lines.extend(f"  {substitute(line, roster)}" for line in request.transcript[-6:])
    elif conversation_memory is None:
        if request.transcript:
            lines.append("\n最近的公开发言（开头 [数字] 是事件编号，发言时可以引用）：")
            lines.extend(f"  {substitute(line, roster)}" for line in request.transcript[-16:])
        else:
            lines.append("\n目前还没有人发言。")

    if conversation_memory is not None:
        conversation_context = conversation_memory.render_prompt(suspicion)
        if conversation_context:
            lines.append("")
            lines.append(conversation_context)

    if request.notes:
        lines.append("\n只有你知道的信息（是否以及如何使用，由你结合收益和风险决定）：")
        lines.extend(f"  {substitute(line, roster)}" for line in request.notes)

    # ConversationMemory已经负责公开发言，避免同一句话又被MemoryStore重复召回。
    recalled_memories = [
        item for item in memories if conversation_memory is None or item.kind != "speech"
    ]
    if recalled_memories:
        lines.append("\n你记得的事（按相关度排序，可能不完整）：")
        lines.extend(f"  - {substitute(item.text, roster)}" for item in recalled_memories)

    visible_seats = tuple(request.context.get("alive") or request.legal)
    if suspicion is not None and visible_seats and request.kind in {"speech", "vote"}:
        lines.append("")
        lines.append(suspicion.summary(visible_seats))

    lines.append(f"\n任务：{KIND_TASK[request.kind]}")
    lines.append(f"输出格式：{KIND_SCHEMA[request.kind]}")
    if request.kind in {"speech", "vote"}:
        lines.append(BASIS_SCHEMA)
    if request.legal:
        targets = "、".join(_label(seat, roster) for seat in request.legal)
        lines.append(f"合法目标（只能从中选，写座位号或名字都行）：{targets}")

    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n".join(lines)),
    ]
