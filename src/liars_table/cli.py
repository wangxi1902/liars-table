from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .agents.llm_agent import LLMAgent
from .agents.random_agent import RandomAgent
from .analysis import build_report, render_html, render_markdown
from .config import get_settings
from .core import events as ev
from .core.roles import CAUSE_ZH, ROLE_ZH
from .engine import Engine
from .llm.client import build_client
from .roster import build_roster


def _force_utf8() -> None:
    """Keep *redirected* output UTF-8 on Windows. The console itself is unaffected."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


_force_utf8()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Liar's Table — 多智能体社交推理竞技场",
)
console = Console()


def _printer(god: bool):
    """返回一个观察者函数：引擎每发一条事件，就打印一行。"""

    def show(event: ev.Event) -> None:
        if isinstance(event, ev.GameStarted):
            console.print(f"[dim]游戏开始 · seed={event.seed} · {len(event.players)} 人局[/]")
        elif isinstance(event, ev.NightFell):
            console.print(f"\n[bold blue]──── 第 {event.round} 夜 ────[/]")
        elif isinstance(event, ev.WolfChose):
            if god:
                console.print(f"[dim red]  {event.wolf} 提议袭击 {event.target}[/]")
        elif isinstance(event, ev.WolfKilled):
            if god:
                console.print(f"[red]  狼人决定袭击 {event.target}[/]")
        elif isinstance(event, ev.SeerChecked):
            if god:
                console.print(
                    f"[dim cyan]  {event.seer} 查验 {event.target} → {event.camp.value}[/]"
                )
        elif isinstance(event, ev.WitchActed):
            if god:
                acts = []
                if event.save:
                    acts.append("使用解药")
                if event.poison:
                    acts.append(f"毒杀 {event.poison}")
                console.print(f"[dim green]  女巫{'、'.join(acts) or '按兵不动'}[/]")
        elif isinstance(event, ev.DawnBroke):
            console.print(f"\n[bold yellow]──── 第 {event.round} 天 ────[/]")
            if event.deaths:
                console.print(f"[red]  天亮，出局：{'、'.join(event.deaths)}[/]")
            else:
                console.print("[green]  平安夜[/]")
        elif isinstance(event, ev.PlayerDied):
            if god:
                console.print(f"[dim red]  {event.player} 死亡（{CAUSE_ZH[event.cause]}）[/]")
        elif isinstance(event, ev.Spoke):
            ids = ",".join(str(c) for c in event.cites)
            suffix = f" [dim]（引用 {ids}）[/]" if ids else ""
            console.print(f"[bold]{event.player}[/]: {event.text}{suffix}")
        elif isinstance(event, ev.Voted):
            console.print(f"[dim]  {event.voter} → {event.target}[/]")
        elif isinstance(event, ev.Exiled):
            counts = "、".join(f"{seat}×{n}" for seat, n in event.tally)
            if event.player is None:
                console.print(f"[yellow]  票型：{counts} → 平票，无人出局[/]")
            else:
                console.print(f"[magenta]  票型：{counts} → {event.player} 出局[/]")
        elif isinstance(event, ev.HunterShot):
            target = event.target or "（无人）"
            console.print(f"[red]  猎人 {event.hunter} 开枪带走 {target}[/]")
        elif isinstance(event, ev.GameEnded):
            console.print()
            console.print(
                Panel(
                    f"胜者：[bold]{event.winner.value}[/]\n原因：{event.reason}",
                    title="游戏结束",
                    border_style="green" if event.winner.value == "good" else "red",
                )
            )

    return show


@app.command()
def demo(
    seed: int = typer.Option(7, "--seed", "-s", help="随机种子"),
    agent: str = typer.Option("llm", "--agent", help="agent 类型：llm 或 random"),
    live: bool = typer.Option(False, "--live", help="真实调用 DeepSeek（需要 .env 里的 key）"),
    latency: float = typer.Option(0.2, "--latency", help="mock 模式模拟的网络延迟（秒）"),
    god: bool = typer.Option(False, "--god", help="上帝视角：显示狼人刀口、预言家验人、女巫用药"),
    reveal: bool = typer.Option(True, "--reveal/--no-reveal", help="结束后公布全部身份"),
    dump: Path | None = typer.Option(None, "--dump", help="把事件流写成 JSONL"),
    report: Path | None = typer.Option(None, "--report", help="生成 Markdown 复盘报告"),
    html_out: Path | None = typer.Option(None, "--html", help="生成单文件 HTML 回放页"),
) -> None:
    """跑一局。默认用 mock 模型，不需要 API key。"""
    settings = get_settings()

    try:
        client = build_client(
            mock=not live,
            latency=latency,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            thinking=settings.deepseek_thinking,
            max_tokens=settings.deepseek_max_tokens,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    roster = build_roster(seed, 9)

    if agent == "random":
        factory = lambda seat, role: RandomAgent(random.Random(f"{seed}:{seat}"))  # noqa: E731
    else:
        factory = lambda seat, role: LLMAgent(seat, role, client, roster=roster)  # noqa: E731

    engine = Engine(agent_factory=factory, seed=seed, on_event=_printer(god), roster=roster)

    started = time.perf_counter()
    result = asyncio.run(engine.run())
    elapsed = time.perf_counter() - started

    if reveal:
        table = Table(title="身份公开")
        table.add_column("座位")
        table.add_column("身份")
        table.add_column("结局")
        for seat in sorted(result.state.roles, key=lambda s: int(s[1:])):
            role = result.state.roles[seat]
            status = "[green]存活[/]" if result.state.is_alive(seat) else "[red]出局[/]"
            table.add_row(seat, ROLE_ZH[role], status)
        console.print(table)

    calls = getattr(client, "calls", 0)
    prompt_tokens = getattr(client, "prompt_tokens", 0)
    completion_tokens = getattr(client, "completion_tokens", 0)
    speeches = [e for e in result.events if e.kind == "spoke"]
    cited = [e for e in speeches if e.cites]
    citation_rate = len(cited) / len(speeches) if speeches else 0.0
    silent = sum(1 for e in speeches if e.text == "（沉默）")
    failures = sum(getattr(agent, "failures", 0) for agent in engine.agents.values())

    console.print(
        f"[dim]用时 {elapsed:.1f}s · LLM 调用 {calls} 次 · "
        f"tokens≈{prompt_tokens}/{completion_tokens} · "
        f"发言 {len(speeches)} 条（{len(cited)} 条带引用，{citation_rate:.0%}）[/]"
    )
    if silent or failures:
        console.print(
            f"[yellow]警告：{silent} 条沉默发言、{failures} 次解析失败——"
            f"通常是 max_tokens 不够或模型没按 JSON 输出[/]"
        )

    if dump is not None:
        dump.parent.mkdir(parents=True, exist_ok=True)
        with dump.open("w", encoding="utf-8") as fh:
            for event in result.events:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        console.print(f"[dim]事件流已写入 {dump}[/]")

    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_markdown(build_report(result)), encoding="utf-8")
        console.print(f"[dim]复盘报告已写入 {report}[/]")

    if html_out is not None:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(render_html(result), encoding="utf-8")
        console.print(f"[dim]HTML 回放页已写入 {html_out}[/]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址"),
    port: int = typer.Option(8000, "--port", help="监听端口"),
) -> None:
    """启动本地观战服务，浏览器打开 http://127.0.0.1:8000 观看实时对局。"""
    import uvicorn

    from .api.server import app as api_app

    console.print(f"[green]观战页：http://{host}:{port}[/]")
    uvicorn.run(api_app, host=host, port=port, log_level="warning")


@app.command()
def bench(
    n: int = typer.Option(9, "--n", help="并发任务数"),
    latency: float = typer.Option(0.3, "--latency", help="每个任务模拟的耗时（秒）"),
) -> None:
    """对比串行与并发，亲眼看到 asyncio.gather 的收益。"""

    async def serial() -> None:
        for _ in range(n):
            await asyncio.sleep(latency)

    async def concurrent() -> None:
        await asyncio.gather(*(asyncio.sleep(latency) for _ in range(n)))

    t0 = time.perf_counter()
    asyncio.run(serial())
    serial_cost = time.perf_counter() - t0

    t1 = time.perf_counter()
    asyncio.run(concurrent())
    concurrent_cost = time.perf_counter() - t1

    console.print(f"{n} 个任务，每个耗时 {latency}s")
    console.print(f"  串行：{serial_cost:.2f}s")
    console.print(f"  并发：{concurrent_cost:.2f}s")
    console.print(f"  加速：{serial_cost / concurrent_cost:.1f}×")


@app.command()
def version() -> None:
    """打印版本号。"""
    console.print(f"liars-table {__version__}")


if __name__ == "__main__":
    app()
