# Architecture

AI狼人杀 (ai-werewolf) is built in layers. Dependencies point strictly downward:
an upper layer may import a lower one, never the reverse.

```
  cli / app       ai_werewolf/cli.py, app.py    the only layers that do I/O
   │
   ├── benchmark  ai_werewolf/benchmark.py      batch evaluation of bot policies
   ├── stats      ai_werewolf/stats             achievements, ranking, ledger
   ├── replay     ai_werewolf/replay            spectate / record / replay
   ├── server     ai_werewolf/server            rooms, matchmaking, session, admin
   │       │
   │       ├── players   ai_werewolf/players    random bot, LLM bot, human
   │       ├── transport ai_werewolf/transport  channel abstraction
   │       └── ai        ai_werewolf/ai         providers + personas
   ├── copilot    ai_werewolf/copilot           explainable human advisor
   └── domain     ai_werewolf/domain            pure rules + referee state machine
```

## The domain layer (pure, no I/O)

- `roles.py` — `Role`, `Faction`, `build_roster()`.
- `actions.py` — `Action` / `ActionKind`, the only thing a player may submit.
- `events.py` — `GameEvent` with per-event audience (`None` = public).
- `state.py` — `GameConfig`, `Seat`, `GameState`, `PlayerView`, `DecisionRequest`.
- `rules.py` — pure rule functions (winner, night deaths, lynch tally).
- `referee.py` — the **state machine**: `SETUP → NIGHT → DAWN → DISCUSSION →
  VOTING → RESOLUTION → FINISHED`, with a `TRANSITIONS` table and strict
  transition validation. Every player decision is validated and repaired.

Two invariants:

1. The event stream is the single source of truth; views, replays and the
   copilot are all derived from it.
2. An illegal action (wrong phase, wrong actor, dead or hallucinated target)
   is repaired to a random legal choice — a buggy client can play badly but
   can never break a game.

## The server layer

- `room.py` — a `Room` gathers humans and a configured `AIConfig`, transitions
  OPEN → READY → PLAYING → FINISHED.
- `matchmaking.py` — a `Matchmaker` queue that forms rooms from waiting humans.
- `session.py` — `GameSession` wires a room's humans (via channels) and bots
  into a referee run, broadcasts public events, and accepts real-time
  text/voice chat during discussion.
- `admin.py` — `AdminBackend` lists rooms, kicks players, cancels rooms,
  reports server stats and manages the bot pool.

## The transport layer

Humans connect through a `Channel` (send/recv pipe). The in-memory
implementation powers tests and the CLI; a WebSocket implementation can be
dropped in without touching the game core (see `app.py`).

## The player and AI layers

`RandomBot` is the baseline; `LLMBot` wraps a `Provider` and is hardened against
malformed model output; `HumanPlayer` renders a prompt over its channel. The AI
layer carries a structured `Prompt` (system + user + `hint`) so the offline
`MockProvider` can answer deterministically without any ad-hoc string trailers.

## The copilot layer

`advise()` takes a human `PlayerView` and returns ranked werewolf suspicions and
a recommended vote via a transparent heuristic (prior → confirmed facts →
voting behaviour → renormalisation). `evaluate_copilot()` measures Brier
calibration over many seeded bot games.

## The replay and stats layers

`replay` serialises a finished game (seats + events + chat) as
`ai-werewolf.replay/v1` and renders a readable timeline. `stats` accumulates a
per-player ledger and derives win rates, a leaderboard and achievement badges.

## Determinism

A `GameConfig.seed` seeds a single `random.Random` on the `GameState`. Role
dealing, tie-breaks and `RandomBot` all draw from it, so a seeded game with
deterministic policies replays event-for-event.
