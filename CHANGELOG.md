# Changelog

All notable changes to AI狼人杀 (ai-werewolf) are documented in this file.
The project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-01-01

### Added

- **Initial release**, an independent derivative of
  [deepwolf](https://github.com/JuneQQQ/deepwolf) at reference commit
  `cc7e8f4c363f7d66d20f66d4d7479d25c842e048`.
- Deterministic game engine (roles: 村民/狼人/预言家/守卫/猎人/女巫) with a
  night/day loop, hunter chains, witch potions and reproducible seeds.
- `RandomAgent`, `LLMAgent` and a new `HumanAgent` (moved into the agents layer,
  driven through a scriptable `HumanUI`).
- `MockProvider` (offline default) and an OpenAI-compatible provider with
  presets for OpenAI, DeepSeek, MiMo, Groq and OpenRouter. Env prefix:
  `AIWEREWOLF_*`.
- Explainable copilot with werewolf-suspicion ranking and Brier-score
  calibration.
- Arena (batch runs + statistics), leaderboard, and JSON transcript save/load/
  replay.
- `extensions/` layer demonstrating stable-interface extensions
  (`vote_analysis`).
- CLI: `simulate`, `play`, `arena`, `leaderboard`, `calibrate`.
- Full test suite: `pytest`, `ruff`, `mypy`.
