"""Localisation for AI狼人杀 — English and Simplified Chinese.

This module is a leaf: it imports nothing else from ``ai_werewolf``, so any
layer can use it freely. A :class:`Translator` turns message keys into
formatted text in the chosen language. Player ids like ``(P0)`` are kept
verbatim in every language; only words are translated.

To add a language, add its code to :data:`LANGUAGES` and a string under that
code for every entry below. A missing translation falls back to English.
"""

from __future__ import annotations

DEFAULT_LANG = "en"
LANGUAGES = ("en", "zh")

#: Human-readable language names, for prompts that ask an agent to reply in one.
LANGUAGE_NAMES = {"en": "English", "zh": "Simplified Chinese (简体中文)"}


def pick(lang: str, en: str, zh: str) -> str:
    """Choose one of two strings for ``lang`` — Chinese, otherwise English.

    A lightweight companion to :class:`Translator` for the many one-off
    bilingual strings in prompts and CLI output that do not warrant a full
    catalogue entry.
    """
    return zh if lang == "zh" else en

# Templated game-event messages. ``{...}`` fields are filled by Translator.t().
GAME_MESSAGES: dict[str, dict[str, str]] = {
    "game_start": {
        "en": "A game of werewolf begins. Players: {roster}. Roles in play: {roles}.",
        "zh": "狼人杀对局开始。玩家：{roster}。本局角色：{roles}。",
    },
    "role_assigned": {
        "en": "You are the {role}.",
        "zh": "你的身份是{role}。",
    },
    "pack_reveal": {
        "en": "You recognise your fellow werewolves.",
        "zh": "你认出了你的狼人同伴。",
    },
    "night_falls": {
        "en": "Night {day} falls. The village sleeps.",
        "zh": "第 {day} 夜降临，村庄陷入沉睡。",
    },
    "werewolf_target": {
        "en": "The pack marks {who} for death.",
        "zh": "狼队标记了 {who}，准备将其杀害。",
    },
    "seer_result": {
        "en": "Your inspection reveals {who} is {verdict}.",
        "zh": "你的查验结果：{who} {verdict}。",
    },
    "doctor_protect": {
        "en": "You watch over {who} tonight.",
        "zh": "今夜你守护 {who}。",
    },
    "witch_night_info": {
        "en": "The werewolves attacked {who} tonight.",
        "zh": "今夜狼人袭击了 {who}。",
    },
    "witch_heal": {
        "en": "You use your healing potion on {who}.",
        "zh": "你对 {who} 使用了解药。",
    },
    "witch_poison": {
        "en": "You use your poison potion on {who}.",
        "zh": "你对 {who} 使用了毒药。",
    },
    "quiet_night": {
        "en": "The village wakes to find everyone alive.",
        "zh": "村庄醒来，发现无人死亡。",
    },
    "quiet_night_saved": {
        "en": "The village wakes to find everyone alive. "
              "Someone was watched over in the dark.",
        "zh": "村庄醒来，发现无人死亡 —— 有人在黑夜中受到了守护。",
    },
    "death_announced": {
        "en": "At dawn the village finds {who} dead.",
        "zh": "黎明时分，村庄发现 {who} 已死亡。",
    },
    "death_announced_revealed": {
        "en": "At dawn the village finds {who} dead. They were the {role}.",
        "zh": "黎明时分，村庄发现 {who} 已死亡。其身份为{role}。",
    },
    "day_breaks": {
        "en": "Day {day}: the village gathers to debate.",
        "zh": "第 {day} 天：村民聚集起来展开讨论。",
    },
    "speak_bid": {
        "en": "{who} bids {priority}/10 for the floor.",
        "zh": "{who} 出价 {priority}/10 争取发言。",
    },
    "speak_bid_reasoned": {
        "en": "{who} bids {priority}/10 for the floor — {reason}",
        "zh": "{who} 出价 {priority}/10 争取发言 —— {reason}",
    },
    "vote_cast": {
        "en": "{voter} votes for {target}.",
        "zh": "{voter} 投票给 {target}。",
    },
    "no_lynch": {
        "en": "The vote is split. Nobody is lynched today.",
        "zh": "投票未达成一致，今天没有人被放逐。",
    },
    "lynch": {
        "en": "The village votes to lynch {who}.",
        "zh": "村庄投票放逐了 {who}。",
    },
    "lynch_revealed": {
        "en": "The village votes to lynch {who}. They were the {role}.",
        "zh": "村庄投票放逐了 {who}。其身份为{role}。",
    },
    "hunter_shot": {
        "en": "With their dying breath, {who} shoots {target}.",
        "zh": "{who} 用最后一口气开枪带走了 {target}。",
    },
    "hunter_shot_revealed": {
        "en": "With their dying breath, {who} shoots {target}. "
              "They were the {role}.",
        "zh": "{who} 用最后一口气开枪带走了 {target}。其身份为{role}。",
    },
    "game_over": {
        "en": "The game is over after {day} day(s). {faction} win.",
        "zh": "对局在第 {day} 天结束。{faction}获胜。",
    },
    "agent_reasoning": {
        "en": "{who} reasoning ({decision}): {reasoning}",
        "zh": "{who} 推理（{decision}）：{reasoning}",
    },
    "game_over_headcount": {
        "en": "The game reaches the day limit. {faction} win on headcount.",
        "zh": "对局达到天数上限，按存活人数{faction}获胜。",
    },
    # Seer verdicts, used inside seer_result.
    "verdict_wolf": {"en": "a werewolf", "zh": "是狼人"},
    "verdict_clear": {"en": "not a werewolf", "zh": "不是狼人"},
    # Private-knowledge notes shown to a player.
    "note_role": {
        "en": "Your secret role is {role}.",
        "zh": "你的秘密身份是{role}。",
    },
    "note_pack": {
        "en": "Your werewolf pack: {mates}",
        "zh": "你的狼人同伴：{mates}",
    },
    "note_pack_alone": {"en": "you alone", "zh": "只有你自己"},
    "note_seer": {
        "en": "Night {day}: you inspected {who} — {verdict}.",
        "zh": "第 {day} 夜：你查验了 {who} —— {verdict}。",
    },
    "note_verdict_wolf": {
        "en": "they are a werewolf",
        "zh": "对方是狼人",
    },
    "note_verdict_clear": {
        "en": "they are not a werewolf",
        "zh": "对方不是狼人",
    },
}

# Localised role display names.
ROLE_NAMES: dict[str, dict[str, str]] = {
    "villager": {"en": "villager", "zh": "村民"},
    "werewolf": {"en": "werewolf", "zh": "狼人"},
    "seer": {"en": "seer", "zh": "预言家"},
    "doctor": {"en": "doctor", "zh": "守卫"},
    "hunter": {"en": "hunter", "zh": "猎人"},
    "witch": {"en": "witch", "zh": "女巫"},
}

# Localised faction labels.
FACTION_LABELS: dict[str, dict[str, str]] = {
    "village": {"en": "the Village", "zh": "村民阵营"},
    "werewolves": {"en": "the Werewolves", "zh": "狼人阵营"},
}

# Localised role summaries, used in agent system prompts.
ROLE_SUMMARIES: dict[str, dict[str, str]] = {
    "villager": {
        "en": "A plain villager with no night ability. Your only tools are "
              "discussion and your vote.",
        "zh": "你是一名普通村民，没有夜间能力。讨论与投票是你仅有的武器。",
    },
    "werewolf": {
        "en": "Each night the werewolves secretly agree on one player to "
              "eliminate. By day you must blend in with the village.",
        "zh": "每晚狼人秘密商定一名玩家进行猎杀。白天你必须伪装成村民。",
    },
    "seer": {
        "en": "Each night you inspect one player and learn whether they are a "
              "werewolf. You win with the village.",
        "zh": "每晚你查验一名玩家，得知其是否为狼人。你与村民阵营共同获胜。",
    },
    "doctor": {
        "en": "Each night you protect one player; if the werewolves attack "
              "that player they survive. You win with the village.",
        "zh": "每晚你守护一名玩家；若狼人袭击该玩家，他将存活。你与村民阵营共同获胜。",
    },
    "hunter": {
        "en": "You have no night ability, but the moment you die you take one "
              "living player down with you. You win with the village.",
        "zh": "你没有夜间能力，但你死亡的瞬间可以带走一名存活玩家。你与村民阵营共同获胜。",
    },
    "witch": {
        "en": "You hold two one-time potions. Each night you learn who the "
              "werewolves attacked; you may heal them and/or poison any "
              "player. You win with the village.",
        "zh": "你持有两瓶一次性药水。每晚你会得知狼人袭击了谁；你可以用解药救他，"
              "也可以用毒药杀死任意一名玩家。你与村民阵营共同获胜。",
    },
}


class Translator:
    """Renders message keys into one language, falling back to English."""

    def __init__(self, lang: str = DEFAULT_LANG) -> None:
        if lang not in LANGUAGES:
            raise ValueError(
                f"unknown language {lang!r}; known: {', '.join(LANGUAGES)}"
            )
        self.lang = lang

    def t(self, key: str, **kwargs: object) -> str:
        """Return the localised, formatted message for ``key``."""
        entry = GAME_MESSAGES.get(key, {})
        template = entry.get(self.lang) or entry.get(DEFAULT_LANG) or key
        return template.format(**kwargs) if kwargs else template

    def role_name(self, role: object) -> str:
        """Localised display name of a role (accepts a Role enum or its value)."""
        value = getattr(role, "value", role)
        entry = ROLE_NAMES.get(str(value), {})
        return entry.get(self.lang) or entry.get(DEFAULT_LANG) or str(value)

    def role_summary(self, role: object) -> str:
        """Localised one-line summary of a role's abilities."""
        value = getattr(role, "value", role)
        entry = ROLE_SUMMARIES.get(str(value), {})
        return entry.get(self.lang) or entry.get(DEFAULT_LANG) or ""

    def faction_label(self, faction: object) -> str:
        """Localised label of a faction (accepts a Faction enum or its value)."""
        value = getattr(faction, "value", faction)
        entry = FACTION_LABELS.get(str(value), {})
        return entry.get(self.lang) or entry.get(DEFAULT_LANG) or str(value)

    @property
    def language_name(self) -> str:
        """Human-readable name of this language, for prompting agents."""
        return LANGUAGE_NAMES.get(self.lang, self.lang)
