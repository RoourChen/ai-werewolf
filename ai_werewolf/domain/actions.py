"""Player actions.

An :class:`Action` is the only thing a player may submit to the referee. The
referee validates every field and rejects (or repairs) anything illegal, so a
misbehaving bot or a buggy client can never corrupt the game.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionKind(str, Enum):
    NIGHT_KILL = "night_kill"      # werewolf: pick a victim
    NIGHT_INSPECT = "night_inspect"  # seer: pick a player to inspect
    NIGHT_PROTECT = "night_protect"  # guard: pick a player to protect
    WITCH_POTIONS = "witch_potions"  # witch: use antidote / poison
    STATEMENT = "statement"          # daytime speech
    BID = "bid"                      # bid for the discussion floor
    VOTE = "vote"                    # lynch vote
    HUNTER_SHOT = "hunter_shot"      # dying hunter's revenge


#: Actions whose legality is defined by a ``target`` player id.
TARGET_ACTIONS = frozenset({
    ActionKind.NIGHT_KILL,
    ActionKind.NIGHT_INSPECT,
    ActionKind.NIGHT_PROTECT,
    ActionKind.VOTE,
    ActionKind.HUNTER_SHOT,
})


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    actor: int
    target: int | None = None
    text: str = ""
    heal: bool = False
    poison: int | None = None
    priority: int = 5
