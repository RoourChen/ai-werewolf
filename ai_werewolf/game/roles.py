"""Role and faction definitions for the werewolf game.

A *role* is what a single player is dealt; a *faction* is the team that role
wins with. The werewolf engine is deliberately small and rule-driven so the
interesting behaviour lives in the agents, not in the referee.
"""

from __future__ import annotations

from enum import Enum


class Faction(str, Enum):
    """The two teams. A game ends when one faction can no longer lose."""

    VILLAGE = "village"
    WEREWOLVES = "werewolves"

    @property
    def label(self) -> str:
        return "the Village" if self is Faction.VILLAGE else "the Werewolves"


class Role(str, Enum):
    """A concrete role a player can be dealt."""

    VILLAGER = "villager"
    WEREWOLF = "werewolf"
    SEER = "seer"
    DOCTOR = "doctor"
    HUNTER = "hunter"
    WITCH = "witch"

    @property
    def faction(self) -> Faction:
        return Faction.WEREWOLVES if self is Role.WEREWOLF else Faction.VILLAGE

    @property
    def has_night_action(self) -> bool:
        """Whether the engine must consult this role during the night phase."""
        return self in (Role.WEREWOLF, Role.SEER, Role.DOCTOR, Role.WITCH)

    @property
    def summary(self) -> str:
        return _SUMMARIES[self]


_SUMMARIES: dict[Role, str] = {
    Role.VILLAGER: (
        "A plain villager with no night ability. Your only tools are "
        "discussion and your vote."
    ),
    Role.WEREWOLF: (
        "Each night the werewolves secretly agree on one player to eliminate. "
        "By day you must blend in with the village."
    ),
    Role.SEER: (
        "Each night you inspect one player and learn whether they are a "
        "werewolf. You win with the village."
    ),
    Role.DOCTOR: (
        "Each night you protect one player; if the werewolves attack that "
        "player they survive. You win with the village."
    ),
    Role.HUNTER: (
        "You have no night ability, but the moment you die — lynched or "
        "killed at night — you take one living player down with you. You "
        "win with the village."
    ),
    Role.WITCH: (
        "You hold two one-time potions. Each night you learn who the "
        "werewolves attacked; you may use a healing potion to save them, "
        "and/or a poison potion to kill any one player. You win with the "
        "village."
    ),
}


def standard_setup(n_players: int) -> list[Role]:
    """Return a balanced role list for ``n_players``.

    Roughly one werewolf per four players, plus a Seer and a Doctor once the
    village is large enough to support them. This mirrors common table rules
    and keeps win rates close to even in self-play.
    """
    if n_players < 4:
        raise ValueError("werewolf needs at least 4 players")

    n_wolves = max(1, round(n_players / 4))
    roles: list[Role] = [Role.WEREWOLF] * n_wolves
    village_seats = n_players - n_wolves

    if village_seats >= 2:
        roles.append(Role.SEER)
    if village_seats >= 3:
        roles.append(Role.DOCTOR)
    if village_seats >= 4:
        roles.append(Role.HUNTER)
    if village_seats >= 5:
        roles.append(Role.WITCH)

    roles += [Role.VILLAGER] * (n_players - len(roles))
    return roles
