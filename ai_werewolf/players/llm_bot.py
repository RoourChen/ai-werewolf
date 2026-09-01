"""An LLM-driven player with a persona and structured decision traces.

The bot builds a persona-aware prompt, calls the model, parses the JSON reply,
and produces an immutable :class:`~ai_werewolf.domain.trace.DecisionRecord`
for every decision. The record captures private suspicion, public suspicion
and strategic threat, plus delta, evidence, confidence, rationale and any
deception plan.

Output that is inconsistent (e.g. a public/private gap without an explicit
deception mark) is retried once with a corrective note; a second failure falls
back to a legal action and is recorded with a fallback reason.
"""

from __future__ import annotations

import json

from ai_werewolf.ai.persona import build_prompt
from ai_werewolf.ai.personas import NEUTRAL, Persona
from ai_werewolf.ai.provider import Prompt, Provider
from ai_werewolf.domain.actions import TARGET_ACTIONS, Action, ActionKind
from ai_werewolf.domain.roles import Role
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.domain.trace import (
    DECEPTION_THRESHOLD,
    DEFAULT_SUSPICION,
    DecisionRecord,
    clamp_score,
    compute_delta,
    key_player,
    normalize_scores,
)
from ai_werewolf.players.base import Player

_PUBLIC_KINDS = {ActionKind.STATEMENT, ActionKind.VOTE}
_SUSPICION_KINDS = {
    ActionKind.NIGHT_KILL,
    ActionKind.NIGHT_INSPECT,
    ActionKind.WITCH_POTIONS,
    ActionKind.STATEMENT,
    ActionKind.VOTE,
}

_BASE_EVIDENCE = {"none", "vote_pattern", "death", "statement"}
_ROLE_EVIDENCE = {
    Role.SEER: {"seer_result"},
    Role.WITCH: {"witch_attack"},
    Role.WEREWOLF: {"pack"},
}

_CORRECTION = {
    "zh": (
        "你上一次的输出被判定为不一致：{issue}。请重新只输出一个合法且一致的 JSON。"
        "若公开怀疑与私下怀疑的差值 ≥0.20，必须主动标记欺骗并给出完整欺骗计划"
        "（对象/公开说法/目的/真实依据）；否则不得标记。"
    ),
    "en": (
        "Your previous output was rejected as inconsistent: {issue}. Reply again "
        "with ONE legal, consistent JSON. If |public - private| >= 0.20 for any "
        "player you must mark deception and give a full plan "
        "(target/public claim/purpose/true basis); otherwise do not mark it."
    ),
}


class LLMBot(Player):
    """A player whose decisions come from a language model + persona."""

    name = "llm"

    def __init__(
        self,
        player_id: int,
        provider: Provider,
        persona: Persona | None = None,
    ) -> None:
        super().__init__(player_id)
        self.provider = provider
        self.persona = persona or NEUTRAL
        self.trace: list[DecisionRecord] = []
        self.latest_record: DecisionRecord | None = None
        self._last_private: dict[int, float] = {}

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        prompt = build_prompt(view, request, self.persona)
        data = _parse_json(self._call(prompt))
        if data is None:
            record, action = self._build_fallback(request, view, "unparseable output")
        else:
            issue = self._validate(request, view, data)
            if issue is None:
                record, action = self._build(request, view, data, None)
            else:
                retried = _parse_json(self._call(self._corrective(view, request, issue)))
                if retried is not None and self._validate(request, view, retried) is None:
                    record, action = self._build(request, view, retried, None)
                else:
                    record, action = self._build_fallback(
                        request, view, f"retry failed: {issue}"
                    )
        self._append(record)
        return action

    # ------------------------------------------------------------- internals
    def _call(self, prompt: Prompt) -> str:
        try:
            return self.provider.complete(prompt)
        except Exception:  # noqa: BLE001 - a provider error must not crash a game
            return ""

    def _corrective(self, view: PlayerView, request: DecisionRequest, issue: str) -> Prompt:
        prompt = build_prompt(view, request, self.persona)
        correction = _CORRECTION[view.language].format(issue=issue)
        return Prompt(prompt.system, prompt.user + "\n\n" + correction, prompt.hint)

    def _append(self, record: DecisionRecord) -> None:
        self.trace.append(record)
        self.latest_record = record

    def _validate(self, request: DecisionRequest, view: PlayerView, data: dict) -> str | None:
        if request.kind is ActionKind.BID:
            return None

        evidence = str(data.get("evidence", "none"))
        if not _evidence_allowed(evidence, view.my_role):
            return f"unauthorized evidence {evidence!r}"

        if view.my_role is Role.WEREWOLF:
            private = normalize_scores(data.get("private_suspicion"), view.living_others())
            pack = set(view.packmates)
            for pid, score in private.items():
                expected = 1.0 if pid in pack else 0.0
                if abs(score - expected) > 0.1:
                    return "wolf pretended unknown judgment"

        if request.kind in _PUBLIC_KINDS:
            private = normalize_scores(data.get("private_suspicion"), view.living_others())
            public = normalize_scores(data.get("public_suspicion"), view.living_others())
            deception = data.get("deception")
            plan = deception if isinstance(deception, dict) else {}
            marked = bool(plan.get("active"))
            plan_complete = _plan_complete(plan)
            big_gap = any(
                abs(public[p] - private[p]) >= DECEPTION_THRESHOLD
                for p in view.living_others()
            )
            if big_gap and not marked:
                return "public/private gap without deception mark"
            if marked and not big_gap and not plan_complete:
                return "deception marked without gap or plan"
            if marked and big_gap and not plan_complete:
                return "deception marked without complete plan"
        return None

    def _build(
        self,
        request: DecisionRequest,
        view: PlayerView,
        data: dict,
        fallback_reason: str | None,
    ) -> tuple[DecisionRecord, Action]:
        others = view.living_others()
        private = normalize_scores(data.get("private_suspicion"), others)
        threat = normalize_scores(data.get("strategic_threat"), others)
        if view.my_role is Role.WEREWOLF:
            pack = set(view.packmates)
            private = {pid: (1.0 if pid in pack else 0.0) for pid in others}
        public = (
            normalize_scores(data.get("public_suspicion"), others)
            if request.kind in _PUBLIC_KINDS
            else {}
        )
        delta = compute_delta(self._last_private, private, others)
        self._last_private = dict(private)

        deception = data.get("deception")
        plan = deception if isinstance(deception, dict) else {}
        marked = request.kind in _PUBLIC_KINDS and bool(plan.get("active"))
        action = _to_action(request, data, view)
        record = DecisionRecord(
            day=view.day,
            phase=view.phase.value,
            actor=request.actor,
            persona=self.persona.id,
            role=view.my_role.value,
            kind=request.kind.value,
            private_suspicion=private,
            public_suspicion=public,
            strategic_threat=threat,
            delta=delta,
            key_player=key_player(delta),
            evidence=str(data.get("evidence", "none")),
            candidates=tuple(request.legal_targets),
            decision=_describe_action(action),
            confidence=clamp_score(data.get("confidence")),
            rationale=str(data.get("reasoning", "")),
            deception=marked,
            deception_plan=_deception_plan(plan) if marked else {},
            fallback_reason=fallback_reason,
        )
        return record, action

    def _build_fallback(
        self, request: DecisionRequest, view: PlayerView, reason: str
    ) -> tuple[DecisionRecord, Action]:
        others = view.living_others()
        private = {
            pid: self._last_private.get(pid, DEFAULT_SUSPICION) for pid in others
        }
        if view.my_role is Role.WEREWOLF:
            pack = set(view.packmates)
            private = {pid: (1.0 if pid in pack else 0.0) for pid in others}
        public = dict(private) if request.kind in _PUBLIC_KINDS else {}
        action = _fallback(request, view)
        record = DecisionRecord(
            day=view.day,
            phase=view.phase.value,
            actor=request.actor,
            persona=self.persona.id,
            role=view.my_role.value,
            kind=request.kind.value,
            private_suspicion=private,
            public_suspicion=public,
            strategic_threat=dict.fromkeys(others, DEFAULT_SUSPICION),
            delta=dict.fromkeys(others, 0.0),
            key_player=None,
            evidence="none",
            candidates=tuple(request.legal_targets),
            decision=_describe_action(action),
            confidence=0.0,
            rationale=reason,
            deception=False,
            deception_plan={},
            fallback_reason=reason,
        )
        return record, action


# ---------------------------------------------------------------- helpers
def _evidence_allowed(evidence: str, role: Role) -> bool:
    prefix = evidence.split(":", 1)[0]
    return prefix in (_BASE_EVIDENCE | _ROLE_EVIDENCE.get(role, set()))


def _plan_complete(plan: dict) -> bool:
    return (
        plan.get("target") is not None
        and bool(str(plan.get("public_statement", "")).strip())
        and bool(str(plan.get("purpose", "")).strip())
        and bool(str(plan.get("true_basis", "")).strip())
    )


def _deception_plan(plan: dict) -> dict:
    return {
        "target": plan.get("target"),
        "public_statement": str(plan.get("public_statement", "")),
        "purpose": str(plan.get("purpose", "")),
        "true_basis": str(plan.get("true_basis", "")),
    }


def _describe_action(action: Action) -> str:
    if action.kind is ActionKind.STATEMENT:
        return f"statement: {action.text[:40]}"
    if action.kind is ActionKind.BID:
        return f"bid {action.priority}"
    if action.kind is ActionKind.WITCH_POTIONS:
        parts = []
        if action.heal:
            parts.append("heal")
        if action.poison is not None:
            parts.append(f"poison P{action.poison}")
        return "witch:" + ("+".join(parts) or "no-potion")
    if action.target is not None:
        return f"{action.kind.value} P{action.target}"
    return action.kind.value


def _to_action(
    request: DecisionRequest, data: dict | None, view: PlayerView
) -> Action:
    if not data:
        return _fallback(request, view)
    if request.kind in TARGET_ACTIONS:
        choice = data.get("choice")
        if isinstance(choice, int) and choice in request.legal_targets:
            return Action(request.kind, request.actor, target=choice)
        return _fallback(request, view)
    if request.kind is ActionKind.WITCH_POTIONS:
        heal = bool(data.get("heal")) and request.can_heal
        poison = data.get("poison")
        poison_target = (
            poison
            if isinstance(poison, int) and request.can_poison and poison in request.legal_targets
            else None
        )
        return Action(ActionKind.WITCH_POTIONS, request.actor, heal=heal, poison=poison_target)
    if request.kind is ActionKind.STATEMENT:
        statement = data.get("statement")
        return Action(
            ActionKind.STATEMENT, request.actor, text=str(statement) if statement else "..."
        )
    if request.kind is ActionKind.BID:
        priority = data.get("priority")
        reason = data.get("reason")
        return Action(
            ActionKind.BID,
            request.actor,
            text=str(reason) if reason else "",
            priority=priority if isinstance(priority, int) else 5,
        )
    return Action(request.kind, request.actor)


def _fallback(request: DecisionRequest, view: PlayerView) -> Action:
    if request.kind in TARGET_ACTIONS and request.legal_targets:
        return Action(
            request.kind,
            request.actor,
            target=view.rng.choice(list(request.legal_targets)),
        )
    if request.kind is ActionKind.STATEMENT:
        return Action(ActionKind.STATEMENT, request.actor, text="...")
    if request.kind is ActionKind.BID:
        return Action(ActionKind.BID, request.actor, priority=5)
    return Action(request.kind, request.actor)


def _parse_json(raw: str) -> dict | None:
    """Extract the first balanced JSON object from a model reply."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    result = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return result if isinstance(result, dict) else None
    return None
