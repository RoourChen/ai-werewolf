# Changelog

All notable changes to AI狼人杀 (ai-werewolf) are documented here.
The project follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-01-01

### Changed

- **Independent rewrite.** The previous 0.1.x code was a port of deepwolf; it
  has been removed and replaced by an original architecture designed around
  human-vs-AI multiplayer play. deepwolf is now an inspiration reference only
  (see THIRD_PARTY_NOTICES.md).

### Added

- `domain/` — an explicit referee state machine (setup → night → dawn →
  discussion → voting → resolution → finished) with validated transitions.
- `server/` — rooms, matchmaking queue, game sessions, and an admin backend.
- `players/` — `RandomBot`, `LLMBot`, and `HumanPlayer` (connected via a
  transport channel).
- `transport/` — channel abstraction + in-memory implementation, ready for a
  WebSocket replacement.
- `copilot/` — explainable werewolf-suspicion advisor + Brier calibration.
- `replay/` — recording, saving and replaying games (`ai-werewolf.replay/v1`).
- `stats/` — win/loss ledger, leaderboard and achievement badges.
- `benchmark.py` — batch evaluation of bot policies.
- `app.py` — optional FastAPI adapter.
- `cli.py` — `simulate`, `play`, `arena`, `calibrate`, `replay`.

## [0.1.0] - 2026-01-01 (superseded)

Initial release, replaced by the 0.2.0 independent rewrite.
