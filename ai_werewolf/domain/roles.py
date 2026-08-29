"""Roles and factions.

Roles are the six classic werewolf identities. A faction is the team a role
wins with. :func:`build_roster` produces a balanced multiset of roles for a
room of a given size.
"""

from __future__ import annotations

from enum import Enum


class Faction(str, Enum):
    VILLAGE = "village"
    WEREWOLVES = "werewolves"


class Role(str, Enum):
    VILLAGER = "villager"
    WEREWOLF = "werewolf"
    SEER = "seer"
    GUARD = "guard"
    HUNTER = "hunter"
    WITCH = "witch"

    @property
    def faction(self) -> Faction:
        return Faction.WEREWOLVES if self is Role.WEREWOLF else Faction.VILLAGE

    @property
    def acts_at_night(self) -> bool:
        """Whether the referee must consult this role during the night."""
        return self in (Role.WEREWOLF, Role.SEER, Role.GUARD, Role.WITCH)


def build_roster(seat_count: int) -> list[Role]:
    """Return a balanced role multiset for ``seat_count`` players.

    Roughly one werewolf per three players (a common social-deduction ratio),
    then special village roles once the village is large enough, then plain
    villagers to fill the rest.
    """
    if seat_count < 4:
        raise ValueError("a room needs at least 4 seats")

    wolf_count = max(1, seat_count // 3)
    roles: list[Role] = [Role.WEREWOLF] * wolf_count
    village_seats = seat_count - wolf_count

    if village_seats >= 2:
        roles.append(Role.SEER)
    if village_seats >= 3:
        roles.append(Role.GUARD)
    if village_seats >= 4:
        roles.append(Role.WITCH)
    if village_seats >= 5:
        roles.append(Role.HUNTER)

    roles += [Role.VILLAGER] * (seat_count - len(roles))
    return roles
