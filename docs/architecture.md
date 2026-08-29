# Architecture

AI狼人杀 (ai-werewolf) is built in layers. Dependencies point strictly downward —
an upper layer may import a lower one, never the reverse.

```
  cli            ai_werewolf/cli.py        the only layer that does console I/O
   │
   ├── extensions ai_werewolf/extensions    new features on stable interfaces only
   │
   ├── arena     ai_werewolf/arena         batches games, aggregates statistics
   │
   ├── copilot   ai_werewolf/copilot       the explainable human advisor
   │
   ├── transcript ai_werewolf/transcript   save / load / replay a finished game
   │
   ├── agents    ai_werewolf/agents        player policies (random, llm, human)
   │      │
   │      └── llm  ai_werewolf/llm         provider abstraction + offline mock
   │
   └── game      ai_werewolf/game          the rules engine — pure, no I/O
```

## The game layer

The referee. It has four parts:

- **`roles.py`** — `Role`, `Faction`, and `standard_setup()` which deals a
  balanced table (村民/狼人/预言家/守卫/猎人/女巫).
- **`events.py`** — `Event`, the atomic unit of everything that happens. An
  event carries its own visibility (`public`, or a `visible_to` set).
- **`state.py`** — `GameState` (the referee's full picture), `PlayerView` (a
  filtered picture for one player), and `build_view()` which produces the
  latter from the former.
- **`engine.py`** — `GameEngine`, which runs the night/day loop, consults
  agents, validates every decision and decides the winner.

Two invariants make the engine trustworthy:

1. **The event log is the single source of truth.** Player views, transcripts
   and the copilot are all *derived* from it.
2. **Every agent decision is validated.** An illegal target — out of range, a
   dead player, a hallucinated id — is silently replaced with a random legal
   one. A buggy agent can play badly; it can never corrupt a game.

## The agent layer

An `Agent` controls one seat. It is asked for `night_action`, `speak`, `vote`
(plus `bid`, `witch_turn`, `dying_shot`, `last_reasoning`) and only ever sees a
`PlayerView`. `RandomAgent` is the baseline; `LLMAgent` wraps a provider and is
hardened against malformed model output; `HumanAgent` drives a human seat
through a minimal `HumanUI` (no terminal I/O leaks into the game core).

## The LLM layer

A `provider` turns chat messages into text. `OpenAICompatProvider` speaks the
OpenAI `/chat/completions` dialect that every major endpoint exposes (OpenAI,
DeepSeek, MiMo, Groq, OpenRouter, custom). `MockProvider` answers offline and
deterministically by reading the machine-readable `[[ACTION ...]]` trailer that
prompts carry. API keys come only from `AIWEREWOLF_*` environment variables.

## The copilot layer

`advise()` takes a human's `PlayerView` and returns ranked werewolf suspicions
plus a recommended vote. The estimate is a transparent heuristic (prior →
confirmed facts → voting-behaviour nudges → renormalisation), with an optional
LLM second opinion layered on top. `evaluate_copilot()` measures how
well-calibrated those probabilities are with the Brier score.

## The transcript layer

`transcript` serialises a finished `GameResult` into a versioned JSON document
(`ai-werewolf.transcript/v1`) and can load it back for replay and analysis.

## The arena layer

`Arena` runs many seeded games with one agent configuration and aggregates the
outcomes into an `ArenaReport`. Because every game is seeded, a benchmark is
fully reproducible. `Leaderboard` pits competitors against a fixed reference on
both factions.

## The extensions layer

`extensions/` holds new functionality that must **not** pollute the core rules
layer. Extensions depend only on stable public interfaces — the transcript
format, `advise()`, arena reports — and never import private game internals.
See `extensions/vote_analysis.py` for the first example (post-game vote
accuracy over a transcript dict).

## Determinism

A `GameConfig.seed` flows into a single `random.Random` on the `GameState`.
Role dealing, tie-breaks and `RandomAgent` all draw from it. Given the same
seed and the same (deterministic) agents, a game replays event-for-event —
which is what makes the arena a real benchmark and bugs reproducible.
