"""Tests for localisation (i18n)."""

from __future__ import annotations

import pytest

from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.events import EventType
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import GameConfig
from ai_werewolf.i18n import DEFAULT_LANG, LANGUAGES, Translator


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_translator_rejects_an_unknown_language():
    with pytest.raises(ValueError):
        Translator("fr")


def test_translator_formats_messages_per_language():
    assert Translator("en").t("night_falls", day=2) == "Night 2 falls. The village sleeps."
    assert _has_cjk(Translator("zh").t("night_falls", day=2))


def test_translator_localises_role_and_faction_names():
    assert Translator("en").role_name(Role.WITCH) == "witch"
    assert Translator("zh").role_name(Role.WITCH) == "女巫"
    assert Translator("zh").faction_label(Faction.VILLAGE) == "村民阵营"


def test_unknown_key_falls_back_to_the_key_itself():
    assert Translator("en").t("no_such_key") == "no_such_key"


def test_default_language_is_a_known_language():
    assert DEFAULT_LANG in LANGUAGES


def test_game_config_rejects_an_unknown_language():
    from ai_werewolf.game.roles import standard_setup

    with pytest.raises(ValueError):
        GameConfig(roles=standard_setup(7), lang="klingon")


def test_chinese_game_emits_chinese_event_text():
    config = GameConfig.standard(7, seed=1, lang="zh")
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    public_text = " ".join(e.text for e in result.events if e.public)
    assert _has_cjk(public_text)
    # the game-over banner is localised too
    game_over = next(e for e in result.events if e.type is EventType.GAME_OVER)
    assert _has_cjk(game_over.text)


def test_english_is_still_the_default_and_unchanged():
    config = GameConfig.standard(7, seed=1)  # no lang -> en
    assert config.lang == "en"
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    night = next(e for e in result.events if e.type is EventType.NIGHT_FALLS)
    assert night.text == "Night 1 falls. The village sleeps."
