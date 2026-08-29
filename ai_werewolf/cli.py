"""The ``ai-werewolf`` command-line interface.

Commands:

* ``simulate``  — watch one all-bot game;
* ``play``      — sit at one seat yourself (bots fill the rest, copilot helps);
* ``arena``     — batch-run a bot policy and print statistics;
* ``calibrate`` — measure the copilot's Brier calibration;
* ``replay``    — replay a saved JSON game.

The CLI is the only layer that does console I/O.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ai_werewolf import __version__
from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import ModelConfig, OpenAICompatProvider, Provider
from ai_werewolf.benchmark import run_arena
from ai_werewolf.copilot.advisor import advise
from ai_werewolf.copilot.calibration import evaluate_copilot
from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import build_roster
from ai_werewolf.domain.state import DecisionRequest, GameConfig, PlayerView
from ai_werewolf.players.llm_bot import LLMBot
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.replay.recorder import load as load_replay
from ai_werewolf.replay.recorder import replay_text, save

try:  # rich is optional sugar
    from rich.console import Console

    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False


class _Plain:
    def print(self, *args: object, **_: object) -> None:
        print(*args)

    def rule(self, title: str = "", **_: object) -> None:
        print(f"--- {title} ---")

    def input(self, prompt: str = "") -> str:
        return input(prompt)


def _console() -> Any:
    return Console() if _RICH else _Plain()


def build_provider(name: str, seed: int = 0) -> Provider:
    if name == "mock":
        return MockProvider(seed=seed)
    if name == "env":
        return OpenAICompatProvider(ModelConfig.from_env())
    raise ValueError(f"unknown provider {name!r} (use 'mock' or 'env')")


class TerminalHuman:
    """A human at the keyboard, with the copilot at their side."""

    name = "human"

    def __init__(self, player_id: int, console: Any) -> None:
        self.player_id = player_id
        self.console = console

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        self.console.rule(
            f"你是 {view.name(view.me)}（P{view.me}）——身份 {view.my_role.value}"
            f"——阶段 {view.phase.value}"
        )
        for secret in view.secrets:
            self.console.print(f"  • {secret}")
        if request.kind in (ActionKind.VOTE, ActionKind.HUNTER_SHOT):
            self._show_copilot(view)
        return self._ask(view, request)

    def _show_copilot(self, view: PlayerView) -> None:
        advice = advise(view)
        self.console.print("🐺 Copilot 狼人嫌疑：")
        for s in advice.suspicions:
            bar = "█" * round(s.probability * 10)
            self.console.print(
                f"  P{s.player_id} {s.name:<8} {s.percent:3d}% {bar}  "
                f"{'; '.join(s.reasons)}"
            )
        self.console.print(f"  建议：{advice.rationale}")

    def _ask(self, view: PlayerView, request: DecisionRequest) -> Action:
        if request.kind is ActionKind.STATEMENT:
            text = self.console.input("发言> ").strip()
            return Action(ActionKind.STATEMENT, request.actor, text=text or "...")
        if request.kind is ActionKind.BID:
            raw = self.console.input("竞价 [0-10]> ").strip()
            priority = int(raw) if raw.isdigit() else 5
            reason = self.console.input("理由（可选）> ").strip()
            return Action(ActionKind.BID, request.actor, text=reason, priority=priority)
        if request.kind is ActionKind.WITCH_POTIONS:
            heal = False
            if request.can_heal:
                heal = self.console.input("使用解药？[y/N] ").strip().lower().startswith("y")
            poison: int | None = None
            if request.can_poison:
                raw = self.console.input("毒药——输入编号或留空：").strip().lstrip("Pp")
                if raw.isdigit() and int(raw) in request.legal_targets:
                    poison = int(raw)
            return Action(ActionKind.WITCH_POTIONS, request.actor, heal=heal, poison=poison)
        named = ", ".join(f"P{c}={view.name(c)}" for c in request.legal_targets)
        self.console.print(f"  合法目标：{named}")
        while True:
            raw = self.console.input("> ").strip().lstrip("Pp")
            if raw.isdigit() and int(raw) in request.legal_targets:
                return Action(request.kind, request.actor, target=int(raw))
            self.console.print("  无效，请输入列出的编号。")


# ------------------------------------------------------------------ commands
def cmd_simulate(args: argparse.Namespace) -> int:
    console = _console()
    provider = build_provider(args.provider, seed=args.model_seed)
    config = GameConfig(
        roster=build_roster(args.players),
        seed=args.seed,
        language=args.lang,
        discussion_mode="bidding" if args.bidding else "seating",
    )

    def decider(view: PlayerView, request: DecisionRequest) -> Action:
        if args.provider == "random":
            return RandomBot(request.actor).decide(view, request)
        return LLMBot(request.actor, provider).decide(view, request)

    console.rule(f"ai-werewolf simulate — {args.players} 人，seed {args.seed}")
    state = Referee(config, decider, observer=lambda e: _print_event(console, e)).run()
    _print_result(console, state)
    if args.transcript:
        path = save(_game_replay(state), args.transcript)
        console.print(f"对局已保存到 {path}")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    console = _console()
    provider = build_provider(args.provider, seed=args.model_seed)
    config = GameConfig(
        roster=build_roster(args.players),
        seed=args.seed,
        language=args.lang,
        discussion_mode="bidding" if args.bidding else "seating",
    )
    seat = args.seat if args.seat is not None else (args.seed % args.players)
    human = TerminalHuman(seat, console)

    def decider(view: PlayerView, request: DecisionRequest) -> Action:
        if request.actor == seat:
            return human.decide(view, request)
        if args.provider == "random":
            return RandomBot(request.actor).decide(view, request)
        return LLMBot(request.actor, provider).decide(view, request)

    console.rule(f"ai-werewolf play — 你是 P{seat}")
    try:
        state = Referee(config, decider, observer=lambda e: _print_public(console, e)).run()
    except (KeyboardInterrupt, EOFError):
        console.print("对局已中止。")
        return 130
    _print_result(console, state)
    won = state.winner is state.seat(seat).faction
    console.print("你赢了！" if won else "你输了。")
    return 0


def cmd_arena(args: argparse.Namespace) -> int:
    console = _console()
    provider = build_provider(args.provider, seed=args.model_seed) if args.provider == "llm" else None
    console.rule(f"ai-werewolf arena — {args.games} 局")
    report = run_arena(
        args.players,
        args.games,
        policy=args.bots,
        base_seed=args.seed,
        provider=provider,
    )
    console.print(report.render())
    console.print(report.ledger.render_leaderboard())
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    console = _console()
    console.rule(f"ai-werewolf calibrate — {args.games} 局")
    report = evaluate_copilot(args.players, args.games, base_seed=args.seed)
    console.print(report.render())
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    console = _console()
    replay = load_replay(args.path)
    console.print(replay_text(replay))
    return 0


# -------------------------------------------------------------- rendering
def _print_event(console: Any, event: GameEvent) -> None:
    tag = "" if event.is_public() else "[私密] "
    style = _STYLE.get(event.kind, "")
    if _RICH and style:
        console.print(f"[{style}]{tag}{event.text}[/{style}]")
    else:
        console.print(f"{tag}{event.text}")


def _print_public(console: Any, event: GameEvent) -> None:
    if event.is_public():
        _print_event(console, event)


def _print_result(console: Any, state: object) -> None:
    from ai_werewolf.domain.state import GameState

    game: GameState = state  # type: ignore[assignment]
    winner = game.winner.value if game.winner else "?"
    console.rule(f"对局结果 — 胜方 {winner}")
    for seat in game.seats:
        status = "存活" if seat.alive else f"第 {seat.death_day} 天死亡"
        console.print(f"  P{seat.id} {seat.name:<8} {seat.role.value:<10} — {status}")


def _game_replay(state: object) -> dict:
    from ai_werewolf.replay.recorder import record_game

    return record_game(state)  # type: ignore[arg-type]


_STYLE = {
    EventKind.GAME_STARTED: "bold cyan",
    EventKind.NIGHT_BEGINS: "blue",
    EventKind.DISCUSSION_BEGINS: "yellow",
    EventKind.DEATH: "red",
    EventKind.LYNCH: "red",
    EventKind.HUNTER_SHOT: "bold red",
    EventKind.PEACEFUL_NIGHT: "green",
    EventKind.GAME_OVER: "bold green",
}


# ---------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-werewolf",
        description="AI狼人杀：真人与 AI 多智能体对战的狼人杀引擎。",
    )
    parser.add_argument("--version", action="version", version=f"ai-werewolf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="观看一局 AI 自博弈")
    sim.add_argument("--players", type=int, default=7)
    sim.add_argument("--seed", type=int, default=1)
    sim.add_argument("--provider", default="mock", help="'mock'、'random' 或 'env'")
    sim.add_argument("--model-seed", type=int, default=0)
    sim.add_argument("--lang", choices=("zh", "en"), default="zh")
    sim.add_argument("--bidding", action="store_true", help="竞价发言模式")
    sim.add_argument("--transcript", metavar="PATH", help="保存对局 JSON")
    sim.set_defaults(func=cmd_simulate)

    play = sub.add_parser("play", help="真人入座，其余席位由 AI 控制")
    play.add_argument("--players", type=int, default=7)
    play.add_argument("--seed", type=int, default=1)
    play.add_argument("--seat", type=int, default=None)
    play.add_argument("--provider", default="mock", help="'mock'、'random' 或 'env'")
    play.add_argument("--model-seed", type=int, default=0)
    play.add_argument("--lang", choices=("zh", "en"), default="zh")
    play.add_argument("--bidding", action="store_true")
    play.set_defaults(func=cmd_play)

    arena = sub.add_parser("arena", help="批量评测机器人策略")
    arena.add_argument("--players", type=int, default=7)
    arena.add_argument("--games", type=int, default=20)
    arena.add_argument("--seed", type=int, default=0)
    arena.add_argument("--bots", choices=("random", "llm"), default="random")
    arena.add_argument("--provider", default="mock", help="llm 机器人使用的 provider")
    arena.add_argument("--model-seed", type=int, default=0)
    arena.set_defaults(func=cmd_arena)

    cal = sub.add_parser("calibrate", help="评估 Copilot 概率的 Brier 校准")
    cal.add_argument("--players", type=int, default=7)
    cal.add_argument("--games", type=int, default=40)
    cal.add_argument("--seed", type=int, default=0)
    cal.set_defaults(func=cmd_calibrate)

    replay = sub.add_parser("replay", help="回放保存的对局 JSON")
    replay.add_argument("path")
    replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ai-werewolf: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
