"""Tests for localisation."""

from __future__ import annotations

import pytest

from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Role, build_roster
from ai_werewolf.domain.state import GameConfig
from ai_werewolf.i18n import DEFAULT_LANGUAGE, LANGUAGES, L10n
from conftest import random_decider


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_l10n_rejects_unknown_language():
    with pytest.raises(ValueError):
        L10n("fr")


def test_default_language_is_known():
    assert DEFAULT_LANGUAGE in LANGUAGES


def test_role_and_faction_names():
    assert L10n("zh").role_name(Role.WITCH) == "女巫"
    assert L10n("en").role_name(Role.WITCH) == "witch"


def test_chinese_game_emits_chinese_text():
    config = GameConfig(roster=build_roster(7), seed=1, language="zh")
    state = Referee(config, random_decider).run()
    public = " ".join(e.text for e in state.events if e.is_public())
    assert _has_cjk(public)


def test_english_game_emits_english_text():
    config = GameConfig(roster=build_roster(7), seed=1, language="en")
    state = Referee(config, random_decider).run()
    public = " ".join(e.text for e in state.events if e.is_public())
    assert not _has_cjk(public)


def test_missing_message_falls_back_to_key():
    assert L10n("zh").msg("no.such.key") == "no.such.key"
