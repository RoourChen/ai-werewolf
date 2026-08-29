"""Benchmark one agent line-up against another in the arena.

    python examples/benchmark.py

Pits mock-LLM villagers against random werewolves over 40 seeded games and
prints the aggregated report. Runs fully offline.
"""

from ai_werewolf import Arena, LLMAgent, MockProvider, RandomAgent
from ai_werewolf.game.roles import Role


def main() -> None:
    provider = MockProvider(seed=0)

    def factory(player_id: int, role: Role):
        # Werewolves play randomly; the village runs the (mock) LLM agent.
        if role is Role.WEREWOLF:
            return RandomAgent(player_id)
        return LLMAgent(player_id, provider)

    report = Arena(n_players=7, agent_factory=factory, n_games=40).run()
    print(report.render())


if __name__ == "__main__":
    main()
