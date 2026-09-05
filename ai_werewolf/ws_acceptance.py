"""Manual acceptance for the single-human WebSocket transport.

Runs the scenarios from PRD/03_产品设计 §8 against the real FastAPI WebSocket
endpoint (via starlette's in-process TestClient) using a deterministic mock
provider. It needs no API key and never reads, prints or stores one.

Checks:

1. full game         — create → join → start → … → game_over, and every
                       ``decision_request`` carries the per-kind ``deadline_ms``
2. per-kind timeout  — a game whose human never answers still finishes; each
                       observed timeout fires at its own configured deadline
3. reconnect replay  — dropping mid-game and reconnecting replays the missed
                       downlink by ``stream_seq`` and the game continues
4. final replay      — the post-game replay is readable (events + AI traces)
                       and contains no secret (API key / token / Authorization)

Run directly with ``python -m ai_werewolf.ws_acceptance`` or via the CLI's
``ws-accept`` command.
"""

from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass, field
from typing import Any

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.server.ws import WsConfig, WsServer, create_ws_app
from ai_werewolf.transport.queue import timeout_for_kind

#: Short, pairwise-distinct deadlines so each action kind is distinguishable
#: without waiting for the product defaults.
_SHORT_TIMEOUTS = {
    "night_kill": 0.20,
    "pack_confirm": 0.25,
    "night_inspect": 0.30,
    "witch_potions": 0.35,
    "statement": 0.40,
    "last_words": 0.45,
    "bid": 0.50,
    "vote": 0.55,
}

#: Seeds whose seat-0 role is witch / seer / werewolf / villager respectively,
#: so a no-answer sweep exercises every human-encounterable decision kind.
_DEFAULT_TIMEOUT_SEEDS = (1, 2, 3, 0)

_TARGET_KINDS = {"night_kill", "pack_confirm", "night_inspect", "vote"}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class AcceptanceReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def render(self) -> str:
        lines = ["WebSocket 人工验收报告（离线 Mock）", ""]
        for check in self.checks:
            mark = "PASS" if check.passed else "FAIL"
            lines.append(f"  [{mark}] {check.name}")
            if check.detail:
                lines.append(f"         {check.detail}")
        lines.append("")
        lines.append("结果：" + ("全部通过" if self.all_passed else "存在失败项"))
        return "\n".join(lines)


def run_acceptance(timeout_seeds: tuple[int, ...] = _DEFAULT_TIMEOUT_SEEDS) -> AcceptanceReport:
    """Run every WebSocket acceptance check and return a report."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        from fastapi.testclient import TestClient

    report = AcceptanceReport()
    report.checks.append(_check_full_game(TestClient(create_ws_app(_make_server(1)))))
    report.checks.append(_check_per_kind_timeout(TestClient, timeout_seeds))
    report.checks.append(_check_reconnect_replay(TestClient(create_ws_app(_make_server(1)))))
    report.checks.append(_check_final_replay(TestClient(create_ws_app(_make_server(1)))))
    return report


def main(argv: list[str] | None = None) -> int:
    report = run_acceptance()
    print(report.render())
    return 0 if report.all_passed else 1


def _make_server(seed: int = 1) -> WsServer:
    return WsServer(config=WsConfig(
        seed=seed,
        provider_factory=lambda s: MockProvider(seed=s),
        timeouts=dict(_SHORT_TIMEOUTS),
    ))


def _auto_action(data: dict) -> dict:
    kind = data["kind"]
    out: dict = {"kind": kind}
    if kind in _TARGET_KINDS:
        targets = data.get("suggestions") or data.get("legal_targets") or []
        out["target"] = targets[0] if targets else None
    elif kind == "witch_potions":
        legal = data.get("legal_targets") or []
        out["heal"] = False
        out["poison"] = legal[0] if data.get("can_poison") and legal else None
    elif kind in ("statement", "last_words"):
        out["text"] = "acceptance"
    elif kind == "bid":
        out["priority"] = 5
    return out


def _create_and_join(ws: Any) -> tuple[str, str, str]:
    ws.send_json({"type": "create_room", "data": {}})
    created = ws.receive_json()
    room_id = created["data"]["room_id"]
    join_secret = created["data"]["join_secret"]
    ws.send_json({"type": "join", "data": {"room_id": room_id, "join_secret": join_secret}})
    joined = ws.receive_json()
    if joined["type"] != "joined":
        raise AssertionError(f"join failed: {joined}")
    return room_id, join_secret, joined["data"]["session_token"]


def _drive_to_game_over(
    ws: Any, *, respond: bool, on_decision=None
) -> tuple[object, int, list[str]]:
    """Drain messages until ``game_over``; optionally answer decisions."""
    winner: object = None
    decisions = 0
    kinds: list[str] = []
    while True:
        message = ws.receive_json()
        if message["type"] == "decision_request":
            kinds.append(message["data"]["kind"])
            if on_decision is not None:
                on_decision(message["data"])
            if respond:
                decisions += 1
                action = _auto_action(message["data"])
                action["request_id"] = message["data"]["request_id"]
                action["client_action_id"] = f"c{decisions}"
                ws.send_json({"type": "action", "data": action})
        elif message["type"] == "game_over":
            winner = message["data"]["winner"]
            break
    return winner, decisions, kinds


def _check_full_game(client: Any) -> Check:
    try:
        deadline_errors: list[str] = []

        def verify_deadline(data: dict) -> None:
            kind = data["kind"]
            expected_ms = int(timeout_for_kind(kind, _SHORT_TIMEOUTS) * 1000)
            if int(data.get("deadline_ms", 0)) != expected_ms:
                deadline_errors.append(
                    f"{kind}: deadline_ms={data.get('deadline_ms')} 期望 {expected_ms}"
                )

        with client.websocket_connect("/ws") as ws:
            room_id, _secret, _token = _create_and_join(ws)
            ws.send_json({"type": "start", "data": {"room_id": room_id}})
            winner, decisions, _ = _drive_to_game_over(
                ws, respond=True, on_decision=verify_deadline
            )
            if winner not in ("village", "werewolves"):
                return Check("full_game", False, f"unexpected winner {winner!r}")
        if deadline_errors:
            return Check("full_game", False, "；".join(deadline_errors[:5]))
        return Check("full_game", True, f"对局完整结束，胜方 {winner}，真人决策 {decisions} 次")
    except Exception as exc:  # noqa: BLE001
        return Check("full_game", False, f"{type(exc).__name__}: {exc}")


def _check_per_kind_timeout(TestClient: Any, seeds: tuple[int, ...]) -> Check:
    """The human never answers across several roles; each kind must time out
    at its own deadline and the game must still finish."""
    try:
        timed_out: dict[str, list[float]] = {}
        winners: list[object] = []
        for seed in seeds:
            server = _make_server(seed)
            with TestClient(create_ws_app(server)).websocket_connect("/ws") as ws:
                room_id, _secret, _token = _create_and_join(ws)
                ws.send_json({"type": "start", "data": {"room_id": room_id}})
                pending: dict[str, tuple[float, str, float]] = {}
                while True:
                    message = ws.receive_json()
                    if message["type"] == "decision_request":
                        data = message["data"]
                        pending[data["request_id"]] = (
                            time.monotonic(),
                            data["kind"],
                            int(data["deadline_ms"]) / 1000.0,
                        )
                    elif message["type"] == "timeout":
                        start, kind, _deadline = pending.pop(
                            message["data"]["request_id"], (0.0, "?", 0.0)
                        )
                        timed_out.setdefault(kind, []).append(time.monotonic() - start)
                    elif message["type"] == "game_over":
                        winners.append(message["data"]["winner"])
                        break

        if not timed_out:
            return Check("per-kind timeout", False, "没有观察到任何 timeout")
        if any(winner not in ("village", "werewolves") for winner in winners):
            return Check("per-kind timeout", False, f"对局未正常结束 {winners}")

        mismatches = []
        for kind, elapsed_list in sorted(timed_out.items()):
            deadline = _SHORT_TIMEOUTS.get(kind, 0.0)
            for elapsed in elapsed_list:
                if elapsed < deadline - 0.05 or elapsed > deadline + 0.8:
                    mismatches.append(
                        f"{kind}: 实测 {elapsed:.2f}s 偏离配置 {deadline:.2f}s"
                    )
        if mismatches:
            return Check("per-kind timeout", False, "；".join(mismatches[:5]))

        return Check(
            "per-kind timeout",
            True,
            f"兜底不中断，覆盖 {('、'.join(sorted(timed_out))) or '无'}",
        )
    except Exception as exc:  # noqa: BLE001
        return Check("per-kind timeout", False, f"{type(exc).__name__}: {exc}")


def _check_reconnect_replay(client: Any) -> Check:
    try:
        with client.websocket_connect("/ws") as ws:
            room_id, _secret, token = _create_and_join(ws)
            ws.send_json({"type": "start", "data": {"room_id": room_id}})
            while True:
                message = ws.receive_json()
                if message["type"] == "game_started":
                    break
        # connection 1 closed here — the server marks the room disconnected

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "reconnect", "data": {
                "room_id": room_id,
                "seat_id": 0,
                "session_token": token,
                "last_stream_seq": 0,
            }})
            reconnected: dict | None = None
            while True:
                message = ws.receive_json()
                if message["type"] == "reconnected":
                    reconnected = message["data"]
                    break
            if reconnected is None or reconnected["replayed_count"] < 1:
                return Check("reconnect replay", False, f"补发异常 {reconnected}")
            _drive_to_game_over(ws, respond=True)
        return Check(
            "reconnect replay",
            True,
            f"补发 {reconnected['replayed_count']} 条，latest_stream_seq={reconnected['latest_stream_seq']}",
        )
    except Exception as exc:  # noqa: BLE001
        return Check("reconnect replay", False, f"{type(exc).__name__}: {exc}")


def _check_final_replay(client: Any) -> Check:
    try:
        with client.websocket_connect("/ws") as ws:
            room_id, secret, token = _create_and_join(ws)
            ws.send_json({"type": "start", "data": {"room_id": room_id}})
            _drive_to_game_over(ws, respond=True)
            ws.send_json({"type": "replay", "data": {"room_id": room_id}})
            reply = ws.receive_json()
            if reply["type"] != "replay":
                return Check("final replay", False, f"replay 未返回：{reply['type']}")
            replay = reply["data"]["replay"]
            if not replay.get("events") or not replay.get("traces"):
                return Check("final replay", False, "replay 缺少 events/traces")

            blob = json.dumps(replay, ensure_ascii=False)
            for secret_value in (secret, token):
                if secret_value and secret_value in blob:
                    return Check("final replay", False, "replay 泄漏了 token/secret")
            for marker in ("Authorization", "Bearer", "api_key", "AIWEREWOLF_API_KEY", "sk-"):
                if marker.lower() in blob.lower():
                    return Check("final replay", False, f"replay 出现敏感标记 {marker!r}")
        return Check(
            "final replay",
            True,
            f"回放可读：{len(replay['events'])} 事件 + {len(replay['traces'])} 席轨迹，无密钥泄漏",
        )
    except Exception as exc:  # noqa: BLE001
        return Check("final replay", False, f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
