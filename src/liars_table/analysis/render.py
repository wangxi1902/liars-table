"""把复盘数据渲染成 Markdown。

为什么要单独一层？
    分析（report.py）和呈现（本文件）分开，将来换成 Web 页面时，
    分析结果可以直接复用，只是换一个渲染器。

Python 知识点：
    ``"".join(parts)``
        比在循环里 ``s += x`` 快得多（字符串不可变，每次 += 都会新建一个）。
    ``textwrap.dedent``
        写多行模板时去掉公共缩进，这里用不到，但值得知道。
"""

from __future__ import annotations

from ..core.roles import CAMP_OF, ROLE_ZH
from .report import ROLE_ZH_BY_VALUE, GameReport


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """生成一张 Markdown 表格。列宽由渲染器自动对齐，这里不用管。"""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_markdown(report: GameReport) -> str:
    parts: list[str] = []

    parts.append(f"# 复盘报告 · seed {report.seed}")
    parts.append("")

    # ---------------- 概况 ----------------
    parts.append("## 概况")
    parts.append("")
    parts.extend(
        _table(
            ["项目", "值"],
            [
                ["胜者", report.winner],
                ["原因", report.reason],
                ["轮数", str(report.rounds)],
                ["发言总数", str(report.total_speeches)],
                ["带引用发言", f"{report.cited_speeches}（{report.citation_rate:.0%}）"],
            ],
        )
    )
    parts.append("")

    # ---------------- 身份与结局 ----------------
    parts.append("## 身份与结局")
    parts.append("")
    rows = []
    for player in report.players:
        rows.append(
            [
                player.seat,
                player.name or player.seat,
                ROLE_ZH[player.role],
                CAMP_OF[player.role].value,
                "存活" if player.survived else "出局",
                str(player.speeches),
                f"{player.cited}（{player.citation_rate:.0%}）",
                str(sum(player.accused_by.values())),
            ]
        )
    parts.extend(
        _table(["座位", "名字", "身份", "阵营", "结局", "发言", "带引用", "被指控"], rows)
    )
    parts.append("")

    # ---------------- 指控矩阵 ----------------
    parts.append("## 指控矩阵")
    parts.append("")
    parts.append("行 = 指控者，列 = 被指控者，数字是次数。")
    parts.append("")
    header = ["指控者"] + [p.seat for p in report.players]
    matrix: list[list[str]] = []
    for accuser in report.players:
        row = [accuser.seat]
        for target in report.players:
            if accuser.seat == target.seat:
                row.append("—")
                continue
            count = accuser.accused.get(target.seat, 0)
            row.append(str(count) if count else "·")
        matrix.append(row)
    parts.extend(_table(header, matrix))
    parts.append("")

    # ---------------- 身份声称 ----------------
    claimants = [p for p in report.players if p.role_claims]
    parts.append("## 身份声称")
    parts.append("")
    if claimants:
        claim_rows = []
        for player in claimants:
            claimed = "、".join(
                ROLE_ZH_BY_VALUE.get(value, value) for value in dict.fromkeys(player.role_claims)
            )
            claim_rows.append(
                [
                    player.seat,
                    claimed,
                    ROLE_ZH[player.role],
                    "不符" if player.exposed else "相符",
                ]
            )
        parts.extend(_table(["座位", "对外声称", "真实身份", "是否相符"], claim_rows))
        parts.append("")
        parts.append("> “不符”不等于作弊：狼人悍跳预言家、村民诈身份都是常见战术。")
    else:
        parts.append("本局没有玩家公开声称身份。")
    parts.append("")

    # ---------------- 问题清单 ----------------
    parts.append("## 问题清单")
    parts.append("")
    if report.issues:
        parts.extend(f"- {issue}" for issue in report.issues)
    else:
        parts.append("- 未发现明显问题")
    parts.append("")

    return "\n".join(parts)
