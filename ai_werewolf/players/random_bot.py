"""A baseline bot that plays uniformly at random.

It is the control group for every benchmark and lets the whole engine run
offline in tests without a network.
"""

from __future__ import annotations

from ai_werewolf.domain.actions import TARGET_ACTIONS, Action, ActionKind
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.players.base import Player

_FILLER: dict[str, list[str]] = {
    "zh": [
        "我暂时没有确凿的判断，先听大家怎么说。",
        "这局有点难读，我再观察一下。",
        "有人在说谎，但我还指不出是谁。",
        "我的票先留着。",
        "我们该关注那些发言太少的人。",
    ],
    "en": [
        "I have nothing solid yet; let's hear from the others.",
        "This table is hard to read; I will keep watching.",
        "Someone here is lying, but I cannot prove who.",
        "I am keeping my vote open for now.",
        "We should focus on whoever is too quiet.",
    ],
}


class RandomBot(Player):
    """Picks uniformly among legal options. No memory, no strategy."""

    name = "random"

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        if request.kind in TARGET_ACTIONS and request.legal_targets:
            return Action(
                request.kind,
                request.actor,
                target=view.rng.choice(list(request.legal_targets)),
            )
        if request.kind is ActionKind.WITCH_POTIONS:
            heal = request.can_heal and view.rng.random() < 0.5
            poison: int | None = None
            if request.can_poison and request.legal_targets and view.rng.random() < 0.3:
                poison = view.rng.choice(list(request.legal_targets))
            return Action(ActionKind.WITCH_POTIONS, request.actor, heal=heal, poison=poison)
        if request.kind is ActionKind.STATEMENT:
            pool = _FILLER.get(view.language, _FILLER["zh"])
            return Action(ActionKind.STATEMENT, request.actor, text=view.rng.choice(pool))
        if request.kind is ActionKind.BID:
            return Action(ActionKind.BID, request.actor, priority=view.rng.randint(0, 10))
        return Action(request.kind, request.actor)
