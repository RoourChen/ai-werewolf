"""Roles and factions.

The MVP supports exactly seven seats with a fixed roster: two werewolves, one
seer, one witch and three villagers. Guard and hunter are not part of this
version.
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
    WITCH = "witch"

    @property
    def faction(self) -> Faction:
        return Faction.WEREWOLVES if self is Role.WEREWOLF else Faction.VILLAGE

    @property
    def acts_at_night(self) -> bool:
        """Whether the referee must consult this role during the night."""
        return self in (Role.WEREWOLF, Role.SEER, Role.WITCH)


MVP_SEATS = 7


def build_roster(seat_count: int) -> list[Role]:
    """Return the fixed 7-seat roster; reject any other size."""
    if seat_count != MVP_SEATS:
        raise ValueError(f"the MVP only supports {MVP_SEATS}-player games")
    return [
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.SEER,
        Role.WITCH,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.VILLAGER,
    ]
