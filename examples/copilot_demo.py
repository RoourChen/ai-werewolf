"""Show the human copilot analysing a real game position.

    python examples/copilot_demo.py

Plays a game with baseline agents, then asks the copilot — from player P0's
seat — who the werewolves probably are. Runs fully offline.
"""

from ai_werewolf import GameConfig, GameEngine, RandomAgent, advise
from ai_werewolf.game.state import build_view


def main() -> None:
    config = GameConfig.standard(n_players=7, seed=11)
    engine = GameEngine(config, lambda pid, _role: RandomAgent(pid))
    engine.run()

    # Build the view player P0 would have, and ask the copilot for advice.
    view = build_view(engine.state, player_id=0)
    advice = advise(view)

    print(f"Copilot report for P0 on day {advice.day}:\n")
    for s in advice.suspicions:
        bar = "#" * round(s.score * 20)
        print(f"  P{s.player_id} {s.name:<8} {s.percent:3d}% |{bar:<20}|")
        print(f"      {'; '.join(s.reasons)}")
    print(f"\n  Recommendation: {advice.rationale}")


if __name__ == "__main__":
    main()
