"""Optional HTTP adapter (FastAPI).

The server layer is transport-agnostic; this module exposes it over HTTP and
WebSocket when FastAPI is installed. It is deliberately optional so the core
stays offline-runnable and dependency-light.

    pip install "ai-werewolf[server]"
    uvicorn ai_werewolf.app:create_app --factory
"""

from __future__ import annotations

from typing import Any


def create_app(admin: Any = None, matchmaker: Any = None) -> Any:
    """Build a FastAPI application over the provided admin/matchmaker.

    ``admin`` is an :class:`~ai_werewolf.server.admin.AdminBackend` and
    ``matchmaker`` a :class:`~ai_werewolf.server.matchmaking.Matchmaker`.
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "the HTTP adapter needs FastAPI; install with `pip install 'ai-werewolf[server]'`"
        ) from exc

    app = FastAPI(title="AI狼人杀")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/rooms")
    def rooms() -> list[dict]:
        return admin.list_rooms() if admin is not None else []

    @app.post("/match")
    def match(payload: dict) -> dict:
        if matchmaker is None:
            return {"error": "matchmaking disabled"}
        matchmaker.enqueue(payload["player_id"], payload["name"], payload.get("channel"))
        return {"queued": True, "queue": matchmaker.queue_size()}

    return app
