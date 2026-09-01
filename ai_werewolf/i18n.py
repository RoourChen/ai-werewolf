"""Localisation for AI狼人杀 — Simplified Chinese (default) and English.

A :class:`L10n` renders message keys into the chosen language. The message
catalogue below was written for this project; it does not reuse upstream text.
"""

from __future__ import annotations

LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"

_MESSAGES: dict[str, dict[str, str]] = {
    "game.started": {
        "zh": "对局开始。座位：{roster}；身份池：{roles}。",
        "en": "The game begins. Seats: {roster}. Roles in play: {roles}.",
    },
    "role.dealt": {
        "zh": "你的身份是：{role}。",
        "en": "Your role is: {role}.",
    },
    "pack.mates": {
        "zh": "你的狼队友：{mates}",
        "en": "Your packmates: {mates}",
    },
    "night.begins": {
        "zh": "第 {day} 夜降临。",
        "en": "Night {day} falls.",
    },
    "wolf.kill": {
        "zh": "狼队决定猎杀 {who}。",
        "en": "The pack marks {who} for death.",
    },
    "seer.result.wolf": {
        "zh": "查验结果：{who} 是狼人。",
        "en": "Inspection: {who} is a werewolf.",
    },
    "seer.result.clear": {
        "zh": "查验结果：{who} 不是狼人。",
        "en": "Inspection: {who} is not a werewolf.",
    },
    "witch.attack": {
        "zh": "狼队袭击了 {who}。",
        "en": "The pack attacked {who}.",
    },
    "witch.heal": {
        "zh": "你对 {who} 使用了解药。",
        "en": "You used your antidote on {who}.",
    },
    "witch.poison": {
        "zh": "你对 {who} 使用了毒药。",
        "en": "You poisoned {who}.",
    },
    "dawn": {
        "zh": "第 {day} 天清晨。",
        "en": "Day {day} dawns.",
    },
    "death": {
        "zh": "{who} 死了。",
        "en": "{who} died.",
    },
    "death.revealed": {
        "zh": "{who} 死了，其身份是{role}。",
        "en": "{who} died and was the {role}.",
    },
    "peaceful.night": {
        "zh": "昨夜平安无事。",
        "en": "It was a peaceful night.",
    },
    "discussion.begins": {
        "zh": "进入第 {day} 天讨论。",
        "en": "Day {day} discussion begins.",
    },
    "bid": {
        "zh": "{who} 以 {priority}/10 竞价发言。",
        "en": "{who} bids {priority}/10 to speak.",
    },
    "vote": {
        "zh": "{who} 投给了 {target}。",
        "en": "{who} voted for {target}.",
    },
    "lynch": {
        "zh": "{who} 被放逐。",
        "en": "{who} was lynched.",
    },
    "lynch.revealed": {
        "zh": "{who} 被放逐，其身份是{role}。",
        "en": "{who} was lynched and was the {role}.",
    },
    "no.lynch": {
        "zh": "平票，无人被放逐。",
        "en": "The vote tied; nobody is lynched.",
    },
    "game.over": {
        "zh": "对局结束，{faction} 获胜。",
        "en": "Game over: {faction} win.",
    },
}

_ROLE_NAMES: dict[str, dict[str, str]] = {
    "villager": {"zh": "村民", "en": "villager"},
    "werewolf": {"zh": "狼人", "en": "werewolf"},
    "seer": {"zh": "预言家", "en": "seer"},
    "witch": {"zh": "女巫", "en": "witch"},
}

_FACTION_NAMES: dict[str, dict[str, str]] = {
    "village": {"zh": "村民阵营", "en": "the Village"},
    "werewolves": {"zh": "狼人阵营", "en": "the Werewolves"},
}

_ROLE_BRIEF: dict[str, dict[str, str]] = {
    "villager": {
        "zh": "普通村民，没有夜间能力，只能靠发言和投票。",
        "en": "A plain villager with no night ability; only speech and voting.",
    },
    "werewolf": {
        "zh": "每晚与狼队友共同猎杀一名玩家，白天伪装成村民。",
        "en": "Each night the pack kills one player; by day, blend in.",
    },
    "seer": {
        "zh": "每晚查验一名玩家的阵营。",
        "en": "Each night inspect one player's faction.",
    },
    "witch": {
        "zh": "持有一次性解药与毒药。",
        "en": "Holds one-time antidote and poison.",
    },
}


class L10n:
    """Renders messages, role names and faction names in one language."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}; known: {', '.join(LANGUAGES)}")
        self.language = language

    def msg(self, key: str, **kwargs: object) -> str:
        entry = _MESSAGES.get(key, {})
        template = entry.get(self.language) or entry.get(DEFAULT_LANGUAGE) or key
        return template.format(**kwargs) if kwargs else template

    def role_name(self, role: object) -> str:
        value = getattr(role, "value", role)
        entry = _ROLE_NAMES.get(str(value), {})
        return entry.get(self.language) or entry.get(DEFAULT_LANGUAGE) or str(value)

    def role_brief(self, role: object) -> str:
        value = getattr(role, "value", role)
        entry = _ROLE_BRIEF.get(str(value), {})
        return entry.get(self.language) or entry.get(DEFAULT_LANGUAGE) or ""

    def faction_name(self, faction: object) -> str:
        value = getattr(faction, "value", faction)
        entry = _FACTION_NAMES.get(str(value), {})
        return entry.get(self.language) or entry.get(DEFAULT_LANGUAGE) or str(value)
