from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .agents.random_agent import RandomAgent
from .core import events as ev
from .core.roles import ROLE_ZH
from .engine import Engine


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

_CAUSE_ZH = {
    "wolf": "被狼人杀害",
    "poison": "被女巫毒杀",
    "vote": "被投票放逐",
    "hunter": "被猎人带走",
}


def _printer(god: bool):
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
                console.print(f"[dim red]  {event.player} 死亡（{_CAUSE_ZH[event.cause]}）[/]")
        elif isinstance(event, ev.Spoke):
            console.print(f"[bold]{event.player}[/]: {event.text}")
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
    god: bool = typer.Option(False, "--god", help="上帝视角：显示狼人刀口、预言家验人、女巫用药"),
    reveal: bool = typer.Option(True, "--reveal/--no-reveal", help="结束后公布全部身份"),
    dump: Path | None = typer.Option(None, "--dump", help="把事件流写成 JSONL"),
) -> None:
    """跑一局全随机 AI 的对局，用来验证规则引擎。"""
    engine = Engine(
        agent_factory=lambda seat, role: RandomAgent(random.Random(f"{seed}:{seat}")),
        seed=seed,
        on_event=_printer(god),
    )
    result = engine.run()

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

    if dump is not None:
        dump.parent.mkdir(parents=True, exist_ok=True)
        with dump.open("w", encoding="utf-8") as fh:
            for event in result.events:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        console.print(f"[dim]事件流已写入 {dump}[/]")


@app.command()
def version() -> None:
    """打印版本号。"""
    console.print(f"liars-table {__version__}")


if __name__ == "__main__":
    app()
