"""Prompt construction for LLM-driven agents.

These helpers turn a :class:`~ai_werewolf.game.state.PlayerView` into chat
messages, in the view's language (``view.lang``). The format is deliberately
stable: every decision request ends with a machine-readable ``[[ACTION ...]]``
trailer, which lets the offline :class:`~ai_werewolf.llm.mock.MockProvider`
answer without a real model. That trailer and the JSON reply keys stay in
English in every language — only the human-readable prose is localised.
"""

from __future__ import annotations

from ai_werewolf.game.events import EventType
from ai_werewolf.game.state import PlayerView
from ai_werewolf.i18n import Translator, pick

# Decision kinds understood by both the LLM agent and the mock provider.
KIND_KILL = "kill"
KIND_INSPECT = "inspect"
KIND_PROTECT = "protect"
KIND_VOTE = "vote"
KIND_SPEAK = "speak"
KIND_SHOOT = "shoot"
KIND_WITCH = "witch"
KIND_BID = "bid"


# Per-decision instructions, English / Chinese.
_ASK: dict[str, tuple[str, str]] = {
    KIND_KILL: (
        "It is night. As a werewolf, choose one living player for the pack to "
        "eliminate. Pick someone whose loss hurts the village.",
        "现在是夜晚。作为狼人，选择一名存活玩家供狼队猎杀。"
        "挑选一个失去后会重创村民阵营的人。",
    ),
    KIND_INSPECT: (
        "It is night. As the Seer, choose one living player to inspect. You "
        "will learn if they are a werewolf.",
        "现在是夜晚。作为预言家，选择一名存活玩家查验。你将得知其是否为狼人。",
    ),
    KIND_PROTECT: (
        "It is night. As the Doctor, choose one living player to protect from "
        "the werewolves tonight.",
        "现在是夜晚。作为守卫，选择一名存活玩家进行守护，使其免遭今夜的狼人袭击。",
    ),
    KIND_VOTE: (
        "It is the daytime vote. Choose one living player to lynch. Vote to "
        "advance your faction's win condition.",
        "现在是白天投票环节。选择一名存活玩家放逐。投票要服务于你所在阵营的胜利目标。",
    ),
    KIND_SPEAK: (
        "It is the daytime discussion. Make a short statement (2-4 sentences) "
        "to the village. Push your faction's agenda — share real reads if that "
        "helps you, or mislead if you must.",
        "现在是白天讨论环节。向全场发表一段简短发言（2-4 句）。"
        "推动你所在阵营的目标——对你有利就分享真实判断，必要时也可以误导。",
    ),
    KIND_SHOOT: (
        "You are the Hunter and you have just died. As your final act, choose "
        "one living player to shoot — aim at whoever you most believe is a "
        "werewolf.",
        "你是猎人，你刚刚死亡。作为最后的行动，选择一名存活玩家开枪带走——"
        "瞄准你最认定是狼人的那个人。",
    ),
}


def system_message(view: PlayerView) -> str:
    """The standing instructions for a player: rules, role and objective."""
    tr = Translator(view.lang)
    role_name = tr.role_name(view.me_role)
    summary = tr.role_summary(view.me_role)
    return pick(
        view.lang,
        "You are playing a game of Werewolf (Mafia), a game of social "
        "deduction. The Village wins when every werewolf is dead. The "
        "Werewolves win when they equal or outnumber the remaining villagers.\n\n"
        f"You are {view.me_name} (P{view.me_id}). Your secret role is "
        f"{role_name.upper()}.\n{summary}\n\n"
        "Play to win. Reason carefully about who is lying. Werewolves should "
        "blend in and misdirect; villagers should compare claims and voting "
        "patterns. Keep statements concise and in character. Never reveal "
        "information you could not plausibly know.",
        "你正在玩一局狼人杀（社交推理游戏）。当所有狼人都死亡时，村民阵营获胜；"
        "当狼人数量达到或超过剩余村民时，狼人阵营获胜。\n\n"
        f"你是 {view.me_name}（P{view.me_id}）。你的秘密身份是{role_name}。\n"
        f"{summary}\n\n"
        "全力争取胜利。仔细推理谁在说谎。狼人应当伪装并误导；村民应当比对各人的"
        "发言与投票。发言简洁、保持角色。绝不要透露你本不该知道的信息。"
        "请全程使用简体中文进行发言与推理。",
    )


def decision_request(view: PlayerView, kind: str, candidates: list[int]) -> str:
    """The user message asking the agent for one concrete decision."""
    lang = view.lang
    header = pick(lang, f"=== Day {view.day} ===", f"=== 第 {view.day} 天 ===")
    parts = [
        header,
        _players_block(view),
        _secret_block(view),
        _log_block(view),
        pick(lang, _ASK[kind][0], _ASK[kind][1]),
        _candidates_line(view, candidates),
        _format_instructions(lang, kind),
        f"[[ACTION kind={kind} candidates={','.join(map(str, candidates))} "
        f"lang={lang}]]",
    ]
    return "\n\n".join(p for p in parts if p)


def witch_request(
    view: PlayerView, victim: int | None, can_heal: bool, can_poison: bool
) -> str:
    """The user message asking the Witch which potions to use tonight."""
    lang = view.lang
    options = []
    if can_heal:
        who = f"{view.name(victim)} (P{victim})" if victim is not None else (
            pick(lang, "the victim", "今夜的受害者")
        )
        options.append(pick(
            lang,
            f"  - HEALING potion: save {who} from the werewolves.",
            f"  - 解药：救下 {who}，使其免遭狼人猎杀。",
        ))
    if can_poison:
        options.append(pick(
            lang,
            "  - POISON potion: kill any one living player.",
            "  - 毒药：毒杀任意一名存活玩家。",
        ))
    living = [p.id for p in view.players if p.alive]
    parts = [
        pick(lang, f"=== Day {view.day} — night ===", f"=== 第 {view.day} 天 — 夜晚 ==="),
        _players_block(view),
        _secret_block(view),
        _log_block(view),
        pick(
            lang,
            "You are the Witch. Potions still available to you:\n"
            + "\n".join(options),
            "你是女巫。你当前还可使用的药水：\n" + "\n".join(options),
        ),
        pick(
            lang,
            "Decide whether to use each — you may use both, one, or neither. "
            "Spend potions wisely; you only get one of each for the whole game.",
            "决定是否使用每一瓶药水——可以都用、用一瓶、或都不用。"
            "谨慎用药，整局游戏每种药水只有一瓶。",
        ),
        pick(
            lang,
            'Respond with ONLY a JSON object: {"heal": true|false, "poison": '
            '<player id|null>}. Use "poison" only to name someone you want dead.',
            '只回复一个 JSON 对象：{"heal": true|false, "poison": <玩家编号|null>}。'
            '只有当你想毒杀某人时才在 "poison" 填写其编号。',
        ),
        f"[[ACTION kind={KIND_WITCH} candidates={','.join(map(str, living))} "
        f"lang={lang}]]",
    ]
    return "\n\n".join(p for p in parts if p)


def bid_request(view: PlayerView) -> str:
    """The user message asking an agent to bid for the discussion floor."""
    lang = view.lang
    parts = [
        pick(lang, f"=== Day {view.day} ===", f"=== 第 {view.day} 天 ==="),
        _players_block(view),
        _secret_block(view),
        _log_block(view),
        pick(
            lang,
            "The village is about to debate. Bid for the discussion floor: how "
            "urgently do you need to speak this round? Bid high only if you have "
            "something genuinely important to say — the bid and your reason are "
            "public.",
            "村庄即将展开讨论。为发言权竞价：本轮你有多迫切需要发言？"
            "只有当你确有重要的话要说时才出高价——你的出价和理由都会公开。",
        ),
        pick(
            lang,
            'Respond with ONLY a JSON object: {"priority": <integer 0-10>, '
            '"reason": "<short public reason>"}. No other text.',
            '只回复一个 JSON 对象：{"priority": <0-10 的整数>, '
            '"reason": "<简短的公开理由>"}。不要输出其他内容。',
        ),
        f"[[ACTION kind={KIND_BID} candidates= lang={lang}]]",
    ]
    return "\n\n".join(p for p in parts if p)


def _players_block(view: PlayerView) -> str:
    lang = view.lang
    alive = pick(lang, "alive", "存活")
    dead = pick(lang, "DEAD", "已死亡")
    you = pick(lang, "  <- you", "  ← 你")
    rows = []
    for p in view.players:
        tag = alive if p.alive else dead
        mark = you if p.id == view.me_id else ""
        rows.append(f"  P{p.id} {p.name}: {tag}{mark}")
    return pick(lang, "Players:", "玩家：") + "\n" + "\n".join(rows)


def _secret_block(view: PlayerView) -> str:
    if not view.private_notes:
        return ""
    label = pick(view.lang, "What only you know:", "只有你知道的信息：")
    return label + "\n" + "\n".join(f"  - {n}" for n in view.private_notes)


def _log_block(view: PlayerView) -> str:
    lang = view.lang
    secret = pick(lang, "  [secret] ", "  [私密] ")
    lines = []
    for e in view.events:
        if e.type in (EventType.ROLE_ASSIGNED, EventType.PACK_REVEAL):
            continue  # already surfaced in the secret block
        lines.append(("  " if e.public else secret) + e.text)
    if not lines:
        return pick(
            lang,
            "Game log: (nothing has happened yet)",
            "对局日志：（暂无事件）",
        )
    return pick(lang, "Game log:", "对局日志：") + "\n" + "\n".join(lines)


def _candidates_line(view: PlayerView, candidates: list[int]) -> str:
    named = ", ".join(f"{view.name(c)} (P{c})" for c in candidates)
    return pick(
        view.lang,
        f"Your legal choices are: {named}.",
        f"你的合法选择有：{named}。",
    )


def _format_instructions(lang: str, kind: str) -> str:
    if kind == KIND_SPEAK:
        return pick(
            lang,
            'Respond with ONLY a JSON object: {"statement": "<your words>"}. '
            "No other text.",
            '只回复一个 JSON 对象：{"statement": "<你的发言>"}。'
            "statement 用简体中文书写，不要输出其他内容。",
        )
    return pick(
        lang,
        'Respond with ONLY a JSON object: {"choice": <player id as integer>, '
        '"reasoning": "<one sentence>"}. The choice MUST be one of the legal '
        "player ids above. No other text.",
        '只回复一个 JSON 对象：{"choice": <玩家编号整数>, "reasoning": "<一句话理由>"}。'
        "choice 必须是上面列出的合法玩家编号之一，不要输出其他内容。",
    )
