"""把一局游戏渲染成一个自包含的 HTML 文件。

为什么是单文件？
    不依赖服务器、不依赖 CDN、不依赖构建工具。发给别人，双击就能看。
    这对"作品展示"来说是最省事的形态——简历里放一个 HTML 比放一个网址可靠。

为什么用内嵌 JSON 之外的方案（Python 直接拼 HTML）？
    这一版数据量小（一局几十条事件），直接渲染成静态标签更简单，
    也方便做 SEO 式的"打开即见"。等 v0.5b 做实时观战时再迁到前端渲染。

Python 知识点：
    ``html.escape``
        所有模型生成的内容都必须转义，否则一句 ``<script>`` 就能让报告炸掉。
        这是 Web 输出最基本的安全习惯。
    ``"".join(parts)``
        拼大量字符串时比 ``+=`` 快，也不会产生一堆中间对象。
    ``str.format`` 与 f-string 混用
        这里用 f-string 拼接，注意 CSS 不是 f-string（否则花括号要写两遍）。
"""

from __future__ import annotations

import html

from ..core import events as ev
from ..core.roles import CAMP_OF, ROLE_ZH
from ..core.view import describe_public
from ..engine import GameResult
from .report import ROLE_ZH_BY_VALUE, build_report

_STYLE = """
:root {
  --bg: #0f1115;
  --card: #171a21;
  --line: #262b36;
  --text: #d7dae0;
  --muted: #8b93a1;
  --good: #4ea1ff;
  --wolf: #ff6b6b;
  --accent: #ffc857;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px 80px;
  background: var(--bg); color: var(--text);
  font: 14px/1.7 "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 36px 0 12px; color: var(--muted); font-weight: 600;
     letter-spacing: .08em; text-transform: uppercase; }
.sub { color: var(--muted); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px; }
.card {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px;
}
.card .k { color: var(--muted); font-size: 12px; }
.card .v { font-size: 22px; font-weight: 600; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; background: var(--card);
        border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; font-size: 12px; }
tr:last-child td { border-bottom: none; }
td.num { font-variant-numeric: tabular-nums; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; }
.badge.good { background: rgba(78,161,255,.15); color: var(--good); }
.badge.wolf { background: rgba(255,107,107,.15); color: var(--wolf); }
.blur { filter: blur(6px); }
body.god-on .blur { filter: none; }
.timeline {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; padding: 6px 0;
}
.line { display: flex; gap: 12px; padding: 7px 16px; border-left: 2px solid transparent; }
.line:hover { background: rgba(255,255,255,.03); }
.line .seq { color: #4a5160; font-variant-numeric: tabular-nums; min-width: 34px; }
.line .body { flex: 1; }
.night { border-left-color: var(--wolf); color: var(--wolf); font-weight: 600; }
.dawn { border-left-color: var(--accent); color: var(--accent); font-weight: 600; }
.speech { border-left-color: #3a7bd5; }
.private { display: none; color: var(--muted); font-style: italic; }
body.god-on .private { display: flex; }
.issues li { margin: 4px 0; }
.btn { margin-top: 18px; background: #222835; color: var(--text); border: 1px solid var(--line);
       padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; }
.btn:hover { background: #2b3242; }
.dim { opacity: .25; }
"""

_SCRIPT = """
const btn = document.getElementById('god');
btn.addEventListener('click', () => {
  const on = document.body.classList.toggle('god-on');
  btn.textContent = on ? '关闭上帝视角' : '开启上帝视角';
});

// 分享链接时带上 #godview，打开就是上帝视角
// 注意：这里不能写 #god —— 按钮的 id 就是 god，浏览器会自动滚到按钮那里
if (location.hash === '#godview') {
  document.body.classList.add('god-on');
  btn.textContent = '关闭上帝视角';
}

// 点击玩家行：高亮该玩家参与的发言
document.querySelectorAll('tr[data-seat]').forEach(row => {
  row.style.cursor = 'pointer';
  row.addEventListener('click', () => {
    const seat = row.dataset.seat;
    const active = row.classList.toggle('dim');
    document.querySelectorAll('.line[data-seats]').forEach(line => {
      const seats = line.dataset.seats.split(',');
      const hit = seats.includes(seat);
      line.classList.toggle('dim', active && !hit);
    });
  });
});
"""


def _private_text(event: ev.Event) -> str | None:
    """上帝视角才显示的行。"""
    if isinstance(event, ev.WolfChose):
        return f"{event.wolf} 提议袭击 {event.target}"
    if isinstance(event, ev.WolfKilled):
        return f"狼队决定袭击 {event.target}"
    if isinstance(event, ev.SeerChecked):
        return f"{event.seer} 查验 {event.target} → {event.camp.value}"
    if isinstance(event, ev.WitchActed):
        acts = []
        if event.save:
            acts.append("使用解药")
        if event.poison:
            acts.append(f"毒杀 {event.poison}")
        return f"女巫{'、'.join(acts) if acts else '按兵不动'}"
    if isinstance(event, ev.PlayerDied):
        return f"{event.player} 出局"
    return None


def _event_seats(event: ev.Event) -> str:
    """这条事件涉及哪些座位，用于前端按玩家过滤。"""
    seats: set[str] = set()
    for attr in ("player", "target", "voter", "wolf", "seer", "witch", "hunter"):
        value = getattr(event, attr, None)
        if isinstance(value, str) and value.startswith("P"):
            seats.add(value)
    deaths = getattr(event, "deaths", ())
    for seat in deaths or ():
        seats.add(seat)
    return ",".join(sorted(seats))


def _timeline(result: GameResult) -> list[str]:
    parts = ['<div class="timeline">']
    for index, event in enumerate(result.events):
        public = describe_public(event)
        private = _private_text(event)
        seats = _event_seats(event)
        attrs = f' data-seats="{seats}"' if seats else ""

        if isinstance(event, ev.NightFell):
            parts.append(
                f'<div class="line night"{attrs}><span class="seq">{index}</span>'
                f'<span class="body">第 {event.round} 夜</span></div>'
            )
            continue
        if isinstance(event, ev.DawnBroke):
            label = f"天亮，出局：{'、'.join(event.deaths)}" if event.deaths else "天亮，平安夜"
            parts.append(
                f'<div class="line dawn"{attrs}><span class="seq">{index}</span>'
                f'<span class="body">{html.escape(label)}</span></div>'
            )
            continue

        if public is not None:
            css = "speech" if isinstance(event, ev.Spoke) else ""
            parts.append(
                f'<div class="line {css}"{attrs}><span class="seq">{index}</span>'
                f'<span class="body">{html.escape(public)}</span></div>'
            )
        if private is not None:
            parts.append(
                f'<div class="line private"{attrs}><span class="seq">{index}</span>'
                f'<span class="body">{html.escape(private)}</span></div>'
            )
    parts.append("</div>")
    return parts


def _players(result: GameResult, report) -> list[str]:
    rows = []
    for player in report.players:
        camp = CAMP_OF[player.role]
        status = "存活" if player.survived else "出局"
        rows.append(
            f'<tr data-seat="{player.seat}">'
            f"<td><b>{player.seat}</b></td>"
            f'<td class="blur">{html.escape(ROLE_ZH[player.role])}</td>'
            f'<td class="blur"><span class="badge {camp.value}">{camp.value}</span></td>'
            f"<td>{status}</td>"
            f'<td class="num">{player.speeches}</td>'
            f'<td class="num">{player.citation_rate:.0%}</td>'
            f'<td class="num">{sum(player.accused_by.values())}</td>'
            "</tr>"
        )
    return [
        "<table>",
        "<thead><tr><th>座位</th><th>身份</th><th>阵营</th><th>结局</th>"
        "<th>发言</th><th>引用率</th><th>被指控</th></tr></thead>",
        "<tbody>",
        *rows,
        "</tbody></table>",
    ]


def _matrix(report) -> list[str]:
    header = "".join(f"<th>{p.seat}</th>" for p in report.players)
    body = []
    for accuser in report.players:
        cells = []
        for target in report.players:
            if accuser.seat == target.seat:
                cells.append('<td style="color:#3a4150">—</td>')
                continue
            count = accuser.accused.get(target.seat, 0)
            if count:
                alpha = min(0.15 + 0.2 * count, 0.75)
                cells.append(
                    f'<td class="num" style="background:rgba(255,107,107,{alpha:.2f})">{count}</td>'
                )
            else:
                cells.append('<td style="color:#3a4150">·</td>')
        body.append(f"<tr><th>{accuser.seat}</th>{''.join(cells)}</tr>")
    return [
        "<table>",
        f"<thead><tr><th>指控者</th>{header}</tr></thead>",
        "<tbody>",
        *body,
        "</tbody></table>",
    ]


def render_html(result: GameResult) -> str:
    """渲染成一份完整的 HTML 文档。"""
    report = build_report(result)

    claims = [p for p in report.players if p.role_claims]
    claim_lines = []
    for player in claims:
        claimed = "、".join(
            ROLE_ZH_BY_VALUE.get(value, value) for value in dict.fromkeys(player.role_claims)
        )
        verdict = "不符" if player.exposed else "相符"
        claim_lines.append(
            f"<li>{player.seat} 声称自己是 {html.escape(claimed)}，"
            f"真实身份 {html.escape(ROLE_ZH[player.role])}（{verdict}）</li>"
        )

    issues = "".join(f"<li>{html.escape(i)}</li>" for i in report.issues)
    if not issues:
        issues = "<li>未发现明显问题</li>"

    alive_count = sum(1 for p in report.players if p.survived)

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        f"<title>Liar's Table · seed {report.seed}</title>",
        f"<style>{_STYLE}</style>",
        "</head><body><div class='wrap'>",
        "<h1>Liar's Table 对局回放</h1>",
        f'<div class="sub">seed {report.seed} · {report.rounds} 轮 · '
        f"{html.escape(report.reason)}</div>",
        '<div class="cards">',
        f'<div class="card"><div class="k">胜者</div><div class="v">{report.winner}</div></div>',
        f'<div class="card"><div class="k">发言</div>'
        f'<div class="v">{report.total_speeches}</div></div>',
        f'<div class="card"><div class="k">引用率</div>'
        f'<div class="v">{report.citation_rate:.0%}</div></div>',
        f'<div class="card"><div class="k">存活</div>'
        f'<div class="v">{alive_count}/{len(report.players)}</div></div>',
        "</div>",
        '<button class="btn" id="god">开启上帝视角</button>',
        "<h2>玩家</h2>",
        *_players(result, report),
        "<h2>时间线</h2>",
        *_timeline(result),
        "<h2>指控矩阵</h2>",
        *_matrix(report),
    ]

    if claim_lines:
        parts.extend(["<h2>身份声称</h2>", "<ul class='issues'>", *claim_lines, "</ul>"])

    parts.extend(["<h2>问题清单</h2>", f"<ul class='issues'>{issues}</ul>"])
    parts.extend([f"<script>{_SCRIPT}</script>", "</div></body></html>"])

    return "\n".join(parts)
