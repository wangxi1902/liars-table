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
from ..cognition import Facts
from ..core.roles import CAMP_OF, ROLE_ZH, Camp, Role
from ..llm.client import ChatMessage
from ..memory import MemoryItem
from ..roster import PlayerInfo, name_of, substitute


def _label(seat: str, roster: dict[str, PlayerInfo]) -> str:
    """``P3（阿飞）``。同时给座位号和名字，模型两种都能用。"""
    info = roster.get(seat)
    return f"{seat}（{info.name}）" if info else seat

ROLE_BRIEF: dict[Role, str] = {
    Role.WEREWOLF: "你是狼人。每晚和队友共同决定杀谁。白天必须伪装成好人，误导投票、保护队友。",
    Role.SEER: (
        "你是预言家，是好人阵营唯一的信息源。"
        "第一晚验到狼（查杀）必须立刻跳身份，把查验结果报出来，带领好人投出去；"
        "验到好人（金水）也要在第二轮之前公开，否则你的信息等于浪费。"
        "不跳身份的预言家，对好人阵营毫无价值。"
    ),
    Role.WITCH: (
        "你是女巫。有一瓶解药和一瓶毒药，各只能用一次，同一夜不能同时使用。"
        "你掌握'昨晚谁被刀'这条独家信息，白天要用它来判断谁在说谎。"
    ),
    Role.HUNTER: "你是猎人。被狼人杀害或被投票出局时，可以开枪带走一名玩家。",
    Role.VILLAGER: (
        "你是普通村民。没有夜间信息，只能靠听发言找狼：重点听谁的逻辑前后矛盾、"
        "谁在无理由跟票、谁急着替别人下定义。"
    ),
}

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
    "vote": "现在是投票阶段，请选择你要放逐的玩家。",
    "shoot": "你已经出局，触发猎人技能，请选择要带走的玩家。",
}

KIND_SCHEMA: dict[str, str] = {
    "kill": '{"target": "座位号"}',
    "check": '{"target": "座位号"}',
    "vote": '{"target": "座位号"}',
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


def build_messages(
    request: DecisionRequest,
    memories: Sequence[MemoryItem] = (),
    roster: dict[str, PlayerInfo] | None = None,
    facts: Facts | None = None,
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
        f"{ROLE_BRIEF[role]}\n"
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
            lines.append(f"你的狼队友：{'、'.join(teammates)}")

    if request.kind == "witch":
        victim = request.context.get("victim")
        lines.append(f"今晚被袭击的是：{victim}")
        lines.append(
            f"你还有解药：{'有' if request.context.get('has_antidote') else '没有'}；"
            f"你还有毒药：{'有' if request.context.get('has_poison') else '没有'}"
        )

    # 结构化态势：存活、票型、身份声称、指控关系。
    # 比"最近 16 条原文"信息密度高得多，也不会因为截断丢掉关键事实。
    if facts is not None:
        lines.append("")
        lines.append(facts.summary())
        if request.transcript:
            lines.append("\n最近几条发言（原文，开头 [数字] 是事件编号）：")
            lines.extend(f"  {substitute(line, roster)}" for line in request.transcript[-6:])
    elif request.transcript:
        lines.append("\n最近的公开发言（开头 [数字] 是事件编号，发言时可以引用）：")
        lines.extend(f"  {substitute(line, roster)}" for line in request.transcript[-16:])
    else:
        lines.append("\n目前还没有人发言。")

    if request.notes:
        lines.append("\n只有你知道的信息（**必须用起来**，否则等于没有）：")
        lines.extend(f"  {substitute(line, roster)}" for line in request.notes)

    # 身份专属的行动提示：光有信息不够，得逼模型把它变成动作
    if role is Role.SEER and request.kind == "speech":
        lines.append(
            "\n提示：你还没公开身份的话，现在就应该跳出来报查验结果；"
            "报的时候要说清楚'我是预言家'，并把查杀对象写进 claims。"
        )
    if role is Role.WITCH and request.kind == "speech" and request.notes:
        lines.append("\n提示：如果昨晚有人被刀而你救了，这条信息可以用来反推谁在说假话。")

    if memories:
        lines.append("\n你记得的事（按相关度排序，可能不完整）：")
        lines.extend(f"  - {substitute(item.text, roster)}" for item in memories)

    lines.append(f"\n任务：{KIND_TASK[request.kind]}")
    lines.append(f"输出格式：{KIND_SCHEMA[request.kind]}")
    if request.legal:
        targets = "、".join(_label(seat, roster) for seat in request.legal)
        lines.append(f"合法目标（只能从中选，写座位号或名字都行）：{targets}")

    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n".join(lines)),
    ]
