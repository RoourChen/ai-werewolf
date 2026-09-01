"""Tests for roles and the fixed 7-seat roster."""

from __future__ import annotations

import pytest

from ai_werewolf.domain.roles import MVP_SEATS, Faction, Role, build_roster


def test_build_roster_is_exactly_seven():
    roles = build_roster(7)
    assert len(roles) == 7
    assert roles.count(Role.WEREWOLF) == 2
    assert roles.count(Role.SEER) == 1
    assert roles.count(Role.WITCH) == 1
    assert roles.count(Role.VILLAGER) == 3


def test_build_roster_rejects_non_seven():
    for n in (0, 1, 4, 6, 8, 10):
        with pytest.raises(ValueError):
            build_roster(n)


def test_guard_and_hunter_are_not_roles():
    assert not hasattr(Role, "GUARD")
    assert not hasattr(Role, "HUNTER")


def test_role_factions_and_night_actions():
    assert Role.WEREWOLF.faction is Faction.WEREWOLVES
    assert Role.SEER.faction is Faction.VILLAGE
    assert Role.WITCH.faction is Faction.VILLAGE
    assert Role.WITCH.acts_at_night is True
    assert Role.VILLAGER.acts_at_night is False
    assert MVP_SEATS == 7
