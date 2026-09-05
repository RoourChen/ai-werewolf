"""The ``ai-werewolf`` command-line interface.

Commands:

* ``simulate``  — watch one all-bot game;
* ``play``      — 1 human + 6 AI bots in a room (copilot assists the human);
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
from ai_werewolf.analysis import analyze_decision_quality
from ai_werewolf.balance import run_balance
from ai_werewolf.benchmark import run_arena
from ai_werewolf.copilot.calibration import evaluate_copilot
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import build_roster
from ai_werewolf.domain.state import GameConfig
from ai_werewolf.domain.trace import DecisionRecord
from ai_werewolf.players.base import Player
from ai_werewolf.players.llm_bot import LLMBot
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.replay.recorder import (
    load as load_replay,
)
from ai_werewolf.replay.recorder import (
    record_game_with_traces,
    record_session,
    replay_text,
    save,
    traces_text,
)
from ai_werewolf.server.room import AIConfig, Room, RoomConfig
from ai_werewolf.server.session import make_traced_decider
from ai_werewolf.transport.channel import Envelope

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


class TerminalChannel:
    """A human channel backed by the terminal (print prompts, read input)."""

    def __init__(self, console: Any) -> None:
        self.console = console
        self._pending: dict | None = None

    def send(self, envelope: Envelope) -> None:
        if envelope.kind == "decision":
            self._pending = envelope.payload
            self.console.rule("轮到你行动")
            if envelope.payload.get("advice"):
                self.console.print(envelope.payload["advice"])
            self.console.print(envelope.payload["prompt"])
        elif envelope.kind == "event":
            self.console.print(envelope.payload["event"]["text"])
        elif envelope.kind == "chat":
            self.console.print(f"[聊天] P{envelope.payload['player']}: {envelope.payload['body']}")
        elif envelope.kind == "result":
            self.console.print(f"对局结束：{envelope.payload['result']['winner']}")

    def recv(self, timeout: float | None = None) -> Envelope:
        if self._pending is None:
            raise TimeoutError("no pending decision")
        request = self._pending["request"]
        return Envelope("action", payload={"action": self._ask(request)})

    def _ask(self, request: dict) -> dict:
        kind = request["kind"]
        targets = request.get("legal_targets", [])
        if kind == "statement":
            text = self.console.input("发言> ").strip()
            return {"kind": kind, "text": text or "..."}
        if kind == "bid":
            raw = self.console.input("竞价 [0-10]> ").strip()
            priority = int(raw) if raw.isdigit() else 5
            reason = self.console.input("理由（可选）> ").strip()
            return {"kind": kind, "priority": priority, "reason": reason}
        if kind == "witch_potions":
            heal = False
            if request.get("can_heal"):
                heal = self.console.input("使用解药？[y/N] ").strip().lower().startswith("y")
            poison: int | None = None
            if request.get("can_poison"):
                raw = self.console.input("毒药——输入编号或留空：").strip().lstrip("Pp")
                if raw.isdigit() and int(raw) in targets:
                    poison = int(raw)
            return {"kind": kind, "heal": heal, "poison": poison}
        named = ", ".join(f"P{t}" for t in targets)
        self.console.print(f"  合法目标：{named}")
        while True:
            raw = self.console.input("> ").strip().lstrip("Pp")
            if raw.isdigit() and int(raw) in targets:
                return {"kind": kind, "target": int(raw)}
            self.console.print("  无效，请输入列出的编号。")


# ------------------------------------------------------------------ commands
def cmd_simulate(args: argparse.Namespace) -> int:
    console = _console()
    config = GameConfig(
        roster=build_roster(args.players),
        seed=args.seed,
        language=args.lang,
        discussion_mode="bidding" if args.bidding else "seating",
    )

    players: dict[int, Player] = {}
    if args.provider == "random":
        players = {pid: RandomBot(pid) for pid in range(args.players)}
    else:
        provider = build_provider(args.provider, seed=args.model_seed)
        players = {pid: LLMBot(pid, provider) for pid in range(args.players)}
    traces: dict[int, list[DecisionRecord]] = {}
    decider = make_traced_decider(players, traces)

    console.rule(f"ai-werewolf simulate — {args.players} 人，seed {args.seed}")
    state = Referee(config, decider, observer=lambda e: _print_event(console, e)).run()
    _print_result(console, state)
    _print_run_record(console, provider, traces)
    if args.transcript:
        save(record_game_with_traces(state, traces), args.transcript)
        console.print(f"对局已保存到 {args.transcript}（含 {sum(len(t) for t in traces.values())} 条决策轨迹）")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    console = _console()
    provider = build_provider(args.provider, seed=args.model_seed) if args.provider == "mock" else None
    ai = AIConfig(count=6, policy="llm", provider=provider, model=args.model)
    room = Room(RoomConfig(
        capacity=7,
        language=args.lang,
        discussion_mode="bidding" if args.bidding else "seating",
        ai=ai,
        seed=args.seed,
    ))
    seat = room.add_human("你", TerminalChannel(console))
    console.rule(f"ai-werewolf play — 你是 P{seat}")
    session = room.start()
    result = session.result
    assert result is not None
    _print_result(console, result)
    _print_run_record(console, getattr(session, "provider", None), session.traces)
    console.rule("决策轨迹回放")
    replay = record_session(session)
    console.print(traces_text(replay))
    if args.transcript:
        save(replay, args.transcript)
        console.print(f"transcript 已保存到 {args.transcript}（脱敏，不含 API Key）")
    won = result.winner is result.seat(seat).faction
    console.print("你赢了！" if won else "你输了。")
    return 0


def cmd_arena(args: argparse.Namespace) -> int:
    console = _console()
    provider = build_provider(args.provider, seed=args.model_seed) if args.bots == "llm" else None
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


def cmd_balance(args: argparse.Namespace) -> int:
    console = _console()
    console.rule("ai-werewolf balance — 离线阵营胜率基线")
    report = run_balance(
        n_games_per_seat=args.games, base_seed=args.seed, strategy=args.strategy
    )
    console.print(report.render())
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    console = _console()
    console.rule(f"ai-werewolf calibrate — {args.games} 局")
    report = evaluate_copilot(args.players, args.games, base_seed=args.seed)
    console.print(report.render())
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    console = _console()
    console.print(replay_text(load_replay(args.path)))
    return 0


# -------------------------------------------------------------- rendering
def _print_run_record(console: Any, provider: object, traces: dict) -> None:
    stats = getattr(provider, "stats", None) if provider is not None else None
    if stats is not None:
        console.rule("模型运行记录")
        for key, value in stats.to_dict().items():
            console.print(f"  {key}: {value}")
    console.print(analyze_decision_quality(traces).render())


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
    console.rule(f"对局结果 — 胜方 {winner}（终局身份揭晓）")
    for seat in game.seats:
        status = "存活" if seat.alive else f"第 {seat.death_day} 天死亡"
        console.print(f"  P{seat.id} {seat.name:<8} {seat.role.value:<10} — {status}")


_STYLE = {
    EventKind.GAME_STARTED: "bold cyan",
    EventKind.NIGHT_BEGINS: "blue",
    EventKind.DISCUSSION_BEGINS: "yellow",
    EventKind.DEATH: "red",
    EventKind.LYNCH: "red",
    EventKind.PEACEFUL_NIGHT: "green",
    EventKind.GAME_OVER: "bold green",
}


# ---------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-werewolf",
        description="AI狼人杀：1 真人 + 6 名不同人格 AI 的 7 人狼人杀。",
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

    play = sub.add_parser("play", help="1 真人入座 + 6 名 AI")
    play.add_argument("--seed", type=int, default=1)
    play.add_argument("--provider", default="mock", help="'mock' 或 'env'")
    play.add_argument("--model-seed", type=int, default=0)
    play.add_argument("--model", default=None, help="模型名（可选）")
    play.add_argument("--lang", choices=("zh", "en"), default="zh")
    play.add_argument("--bidding", action="store_true")
    play.add_argument("--transcript", metavar="PATH", default=None, help="保存脱敏 transcript JSON")
    play.set_defaults(func=cmd_play)

    arena = sub.add_parser("arena", help="批量评测机器人策略")
    arena.add_argument("--players", type=int, default=7)
    arena.add_argument("--games", type=int, default=20)
    arena.add_argument("--seed", type=int, default=0)
    arena.add_argument("--bots", choices=("random", "llm"), default="random")
    arena.add_argument("--provider", default="mock", help="llm 机器人使用的 provider")
    arena.add_argument("--model-seed", type=int, default=0)
    arena.set_defaults(func=cmd_arena)

    balance = sub.add_parser("balance", help="离线阵营胜率基线（按阵营/角色/座位/先后手/seed 分层）")
    balance.add_argument("--games", type=int, default=50, help="每个真人座位跑多少局")
    balance.add_argument("--seed", type=int, default=0)
    balance.add_argument("--strategy", choices=("llm", "random"), default="llm", help="AI 策略对照")
    balance.set_defaults(func=cmd_balance)

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
