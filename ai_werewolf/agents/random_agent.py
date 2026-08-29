"""A baseline agent that plays uniformly at random.

It exists for two reasons: it is the control group every arena benchmark
measures LLM agents against, and it lets the whole engine be exercised in
tests without touching a network.
"""

from __future__ import annotations

from ai_werewolf.agents.base import Agent
from ai_werewolf.game.state import PlayerView

_FILLER = {
    "en": [
        "I don't have anything solid yet. Let's hear from the others.",
        "Hard to read this table. I'll keep watching.",
        "Someone here is lying, but I can't prove who.",
        "I'm keeping my vote open for now.",
        "We should focus on whoever is being too quiet.",
    ],
    "zh": [
        "我暂时还没有确凿的判断，先听听其他人怎么说。",
        "这场局有点难读，我再观察观察。",
        "这里有人在撒谎，但我还说不出是谁。",
        "我的票暂时先留着。",
        "我们该重点关注那些发言太少的人。",
    ],
}


class RandomAgent(Agent):
    """Picks uniformly among legal options. No memory, no strategy."""

    name = "random"

    def night_action(self, view: PlayerView) -> int:
        return view.rng.choice(self._pool(view))

    def vote(self, view: PlayerView) -> int:
        return view.rng.choice(self._pool(view))

    def speak(self, view: PlayerView) -> str:
        return view.rng.choice(_FILLER.get(view.lang, _FILLER["en"]))

    def bid(self, view: PlayerView) -> tuple[int, str]:
        return (view.rng.randint(0, 10), "")

    def witch_turn(
        self, view: PlayerView, victim: int | None, can_heal: bool, can_poison: bool
    ) -> tuple[bool, int | None]:
        heal = can_heal and view.rng.random() < 0.5
        poison: int | None = None
        if can_poison and view.rng.random() < 0.3 and view.others_alive():
            poison = view.rng.choice(view.others_alive())
        return (heal, poison)

    @staticmethod
    def _pool(view: PlayerView) -> list[int]:
        return view.others_alive() or list(view.living_ids)
