"""Run a single self-play game and print who won.

    python examples/quickstart.py

Uses the offline MockProvider, so no API key is required.
"""

from ai_werewolf import GameConfig, GameEngine, LLMAgent, MockProvider


def main() -> None:
    provider = MockProvider(seed=0)
    config = GameConfig.standard(n_players=7, seed=1)

    def make_agent(player_id: int, _role: object) -> LLMAgent:
        return LLMAgent(player_id, provider)

    result = GameEngine(config, make_agent).run()

    print(f"{result.winner.label} win after {result.days} day(s).\n")
    for player in result.players:
        status = "survived" if player.alive else f"died on day {player.death_day}"
        print(f"  P{player.id} {player.name:<8} {player.role.value:<9} — {status}")


if __name__ == "__main__":
    main()
