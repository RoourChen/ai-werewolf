"""Tests for roles and roster building."""

from __future__ import annotations

import pytest

from ai_werewolf.domain.roles import Faction, Role, build_roster


def test_build_roster_is_balanced_for_seven():
    roles = build_roster(7)
    assert len(roles) == 7
    assert roles.count(Role.WEREWOLF) == 2
    assert roles.count(Role.SEER) == 1
    assert roles.count(Role.GUARD) == 1
    assert roles.count(Role.WITCH) == 1
    assert roles.count(Role.HUNTER) == 1


def test_build_roster_omits_special_roles_in_small_games():
    roles = build_roster(4)
    assert len(roles) == 4
    assert roles.count(Role.WEREWOLF) == 1
    assert roles.count(Role.HUNTER) == 0


def test_build_roster_rejects_tiny_rooms():
    with pytest.raises(ValueError):
        build_roster(3)


def test_role_factions_and_night_actions():
    assert Role.WEREWOLF.faction is Faction.WEREWOLVES
    assert Role.SEER.faction is Faction.VILLAGE
    assert Role.GUARD.faction is Faction.VILLAGE
    assert Role.GUARD.acts_at_night is True
    assert Role.HUNTER.acts_at_night is False
