"""An LLM-driven player with a persona and structured decision traces.

The bot builds a persona-aware prompt, calls the model, parses the JSON reply,
and produces an immutable :class:`~ai_werewolf.domain.trace.DecisionRecord`
for every decision. Output is validated strictly: suspicion maps must be
exactly the living-other keys with 0..1 numbers, evidence must reference a
visible event id, wolf knowledge must be 0/1, and deception must target a real
player with a ≥0.20 public/private gap (or a verifiable fabricated event) plus
a complete, matching plan.

Invalid output is retried once with a corrective note; a second failure falls
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
    parse_scores,
)
from ai_werewolf.players.base import Player

_PUBLIC_KINDS = {ActionKind.STATEMENT, ActionKind.VOTE}
_SUSPICION_KINDS = {
    ActionKind.NIGHT_KILL,
    ActionKind.PACK_CONFIRM,
    ActionKind.NIGHT_INSPECT,
    ActionKind.WITCH_POTIONS,
    ActionKind.STATEMENT,
    ActionKind.VOTE,
}

_CORRECTION = {
    "zh": (
        "你上一次的输出被判定为不一致：{issue}。请重新只输出一个合法且一致的 JSON。"
        "怀疑分必须覆盖每个存活其他玩家且为 0-1 数值；evidence 必须是对局日志中你"
        "可见的事件编号或 null；若公开与私下怀疑差值 ≥0.20，必须主动标记欺骗并给出"
        "与该对象一致的完整计划。"
    ),
    "en": (
        "Your previous output was rejected as inconsistent: {issue}. Reply again "
        "with ONE legal, consistent JSON. Suspicion must cover every living other "
        "with 0-1 numbers; evidence must be a visible event id or null; if "
        "|public - private| >= 0.20 for a target you must mark deception with a "
        "complete, matching plan."
    ),
}

_JSON_ONLY = {
    "zh": "请只输出一个合法的 JSON 对象，不要任何解释或多余文字。",
    "en": "Output ONLY one valid JSON object, with no other text.",
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
        self._last_threat: dict[int, float] = {}
        self.json_diagnostics: list[dict] = []

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        prompt = build_prompt(view, request, self.persona)
        raw = self._call(prompt)
        data = _parse_json(raw)
        first_failure: str | None = None
        if data is None:
            first_failure = "unparseable output"
            self._record_json_failure(raw)
            retried_raw = self._call(self._json_only(view, request))
            retried = _parse_json(retried_raw)
            if retried is not None and self._validate(request, view, retried) is None:
                self._mark_last_recovered("retry")
                record, action = self._build(request, view, retried, None, retried=True, first_failure=first_failure)
            else:
                if retried is None:
                    self._record_json_failure(retried_raw)
                record, action = self._build_fallback(
                    request, view, "unparseable output", retried=True, first_failure=first_failure
                )
        else:
            issue = self._validate(request, view, data)
            if issue is None:
                record, action = self._build(request, view, data, None, retried=False, first_failure=None)
            else:
                first_failure = issue
                retried = _parse_json(self._call(self._corrective(view, request, issue)))
                if retried is not None and self._validate(request, view, retried) is None:
                    record, action = self._build(request, view, retried, None, retried=True, first_failure=first_failure)
                else:
                    record, action = self._build_fallback(
                        request, view, f"retry failed: {issue}", retried=True, first_failure=first_failure
                    )
        self._append(record)
        return action

    def _record_json_failure(self, raw: str) -> None:
        _, diag = _parse_json_with_diag(raw)
        full = dict(getattr(self.provider, "last_diagnostic", {}))
        full.update(diag)
        full["reached_max_tokens"] = (
            full.get("finish_reason") == "length"
            or full.get("completion_tokens", 0) >= full.get("max_tokens", 0)
        )
        self.json_diagnostics.append(full)

    def _mark_last_recovered(self, method: str) -> None:
        if self.json_diagnostics:
            self.json_diagnostics[-1]["recovered_by"] = method

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

    def _json_only(self, view: PlayerView, request: DecisionRequest) -> Prompt:
        prompt = build_prompt(view, request, self.persona)
        note = _JSON_ONLY[view.language]
        return Prompt(prompt.system, prompt.user + "\n\n" + note, prompt.hint)

    def _append(self, record: DecisionRecord) -> None:
        self.trace.append(record)
        self.latest_record = record

    def _validate(self, request: DecisionRequest, view: PlayerView, data: dict) -> str | None:
        if request.kind in (ActionKind.BID, ActionKind.LAST_WORDS):
            return None

        others = view.living_others()

        evidence = data.get("evidence")
        issue = _validate_evidence(evidence, view)
        if issue is not None:
            return issue

        if request.kind in _SUSPICION_KINDS:
            if parse_scores(data.get("private_suspicion"), others) is None:
                return "invalid private_suspicion (missing/extra/out-of-range keys)"
            if parse_scores(data.get("strategic_threat"), others) is None:
                return "invalid strategic_threat (missing/extra/out-of-range keys)"
            if request.kind in _PUBLIC_KINDS and parse_scores(data.get("public_suspicion"), others) is None:
                return "invalid public_suspicion (missing/extra/out-of-range keys)"

            private = parse_scores(data.get("private_suspicion"), others) or {}

            if request.kind is ActionKind.WITCH_POTIONS:
                issue = _validate_witch(data, request)
                if issue is not None:
                    return issue

            if request.kind in _PUBLIC_KINDS:
                public = parse_scores(data.get("public_suspicion"), others) or {}
                status = _deception_status(data, others, private, public, view)
                if status not in ("none", "confirmed", "pending_review"):
                    return status
        return None

    def _build(
        self,
        request: DecisionRequest,
        view: PlayerView,
        data: dict,
        fallback_reason: str | None,
        *,
        retried: bool = False,
        first_failure: str | None = None,
    ) -> tuple[DecisionRecord, Action]:
        others = view.living_others()
        if request.kind in _SUSPICION_KINDS:
            private = parse_scores(data.get("private_suspicion"), others) or {}
            threat = parse_scores(data.get("strategic_threat"), others) or {}
            if view.my_role is Role.WEREWOLF:
                pack = set(view.packmates)
                private = {pid: (1.0 if pid in pack else 0.0) for pid in others}
            public = (
                parse_scores(data.get("public_suspicion"), others) or {}
                if request.kind in _PUBLIC_KINDS
                else {}
            )
        else:
            private = {
                pid: self._last_private.get(pid, DEFAULT_SUSPICION) for pid in others
            }
            threat = dict.fromkeys(others, DEFAULT_SUSPICION)
            public = {}

        delta = compute_delta(self._last_private, private, others)
        self._last_private = dict(private)
        threat_delta = compute_delta(self._last_threat, threat, others)
        self._last_threat = dict(threat)

        deception = data.get("deception")
        plan = deception if isinstance(deception, dict) else {}
        marked = request.kind in _PUBLIC_KINDS and bool(plan.get("active"))
        status = (
            _deception_status(data, others, private, public, view)
            if request.kind in _PUBLIC_KINDS
            else "none"
        )
        action = _to_action(request, data, view)
        evidence = _evidence_text(data.get("evidence"))
        confidence = clamp_score(data.get("confidence"))
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
            threat_delta=threat_delta,
            threat_key_player=key_player(threat_delta),
            evidence=evidence,
            candidates=tuple(request.legal_targets),
            decision=_describe_action(action),
            confidence=confidence,
            rationale=str(data.get("reasoning", "")),
            deception=(status == "confirmed"),
            deception_plan=_deception_plan(plan) if marked else {},
            fallback_reason=fallback_reason,
            retried=retried,
            pending_review=(status == "pending_review"),
            first_failure=first_failure,
        )
        return record, action

    def _build_fallback(
        self, request: DecisionRequest, view: PlayerView, reason: str, *, retried: bool = False, first_failure: str | None = None
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
            threat_delta=dict.fromkeys(others, 0.0),
            threat_key_player=None,
            evidence="none",
            candidates=tuple(request.legal_targets),
            decision=_describe_action(action),
            confidence=0.0,
            rationale=reason,
            deception=False,
            deception_plan={},
            fallback_reason=reason,
            retried=retried,
            first_failure=first_failure,
        )
        return record, action


# ---------------------------------------------------------------- helpers
def _validate_evidence(evidence: object, view: PlayerView) -> str | None:
    if evidence is None:
        return None
    if isinstance(evidence, bool):
        return "invalid evidence"
    ids = evidence if isinstance(evidence, list) else [evidence]
    visible = {e.id for e in view.events}
    for item in ids:
        event_id = _parse_event_id(item)
        if event_id is None:
            return "invalid evidence"
        if event_id not in visible:
            return "evidence references unknown event"
    return None


def _parse_event_id(item: object) -> int | None:
    if isinstance(item, bool):
        return None
    if isinstance(item, int):
        return item
    text = str(item).strip()
    if text[:1].upper() == "E":
        text = text[1:]
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _evidence_text(evidence: object) -> str:
    if evidence is None:
        return "none"
    ids = evidence if isinstance(evidence, list) else [evidence]
    parsed = [eid for eid in (_parse_event_id(i) for i in ids) if eid is not None]
    return ",".join(f"E{eid}" for eid in parsed) or "none"


def _validate_witch(data: dict, request: DecisionRequest) -> str | None:
    heal = bool(data.get("heal"))
    poison = data.get("poison")
    if heal and poison is not None:
        return "illegal double potion"
    if heal and not request.can_heal:
        return "illegal heal"
    if poison is not None:
        if not request.can_poison:
            return "illegal poison"
        if not isinstance(poison, int) or poison not in request.legal_targets:
            return "illegal poison target"
    return None


def _deception_status(
    data: dict,
    others: list[int],
    private: dict[int, float],
    public: dict[int, float],
    view: PlayerView,
) -> str:
    plan = data.get("deception")
    if not isinstance(plan, dict):
        return "deception must be an object"
    marked = bool(plan.get("active"))
    if not marked:
        if any(abs(public[p] - private[p]) >= DECEPTION_THRESHOLD for p in others):
            return "public/private gap without deception mark"
        return "none"

    target = _parse_player_id(plan.get("target"))
    if target is None or target not in others:
        return "deception target is not a valid player"
    if not _plan_complete(plan):
        return "deception marked without complete plan"
    gap = abs(public.get(target, 0.0) - private.get(target, 0.0))
    if gap >= DECEPTION_THRESHOLD:
        return "confirmed"
    big_gap = [
        p for p in others if abs(public[p] - private[p]) >= DECEPTION_THRESHOLD
    ]
    if big_gap:
        return "deception target does not match the gap object"
    fabricated = plan.get("fabricated_event")
    if fabricated is not None:
        if _is_verifiable_fabrication(fabricated, view, target):
            return "confirmed"
        return "fabrication references no verifiable event"
    return "pending_review"


def _plan_complete(plan: dict) -> bool:
    return (
        bool(str(plan.get("public_statement", "")).strip())
        and bool(str(plan.get("purpose", "")).strip())
        and bool(str(plan.get("true_basis", "")).strip())
    )


def _parse_player_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lstrip("Pp")
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _is_verifiable_fabrication(
    event_id: object, view: PlayerView, target: int
) -> bool:
    """A fabrication must reference a visible, fact-bearing event about the
    deception target (so a text-only claim cannot bypass the gap rule)."""
    if not isinstance(event_id, int):
        return False
    for event in view.events:
        if event.id == event_id and event.data and event.target == target:
            return True
    return False


def _deception_plan(plan: dict) -> dict:
    return {
        "target": _parse_player_id(plan.get("target")),
        "public_statement": str(plan.get("public_statement", "")),
        "purpose": str(plan.get("purpose", "")),
        "true_basis": str(plan.get("true_basis", "")),
        "fabricated_event": plan.get("fabricated_event"),
    }


def _describe_action(action: Action) -> str:
    if action.kind in (ActionKind.STATEMENT, ActionKind.LAST_WORDS):
        return f"{action.kind.value}: {action.text[:40]}"
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
    if request.kind in (ActionKind.STATEMENT, ActionKind.LAST_WORDS):
        statement = data.get("statement")
        return Action(
            request.kind, request.actor, text=str(statement) if statement else "..."
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
    if request.kind is ActionKind.PACK_CONFIRM:
        target = (
            request.suggestions[0]
            if request.suggestions and request.suggestions[0] in request.legal_targets
            else view.rng.choice(list(request.legal_targets))
        )
        return Action(ActionKind.PACK_CONFIRM, request.actor, target=target)
    if request.kind in TARGET_ACTIONS and request.legal_targets:
        return Action(
            request.kind,
            request.actor,
            target=view.rng.choice(list(request.legal_targets)),
        )
    if request.kind is ActionKind.WITCH_POTIONS:
        return Action(ActionKind.WITCH_POTIONS, request.actor)
    if request.kind in (ActionKind.STATEMENT, ActionKind.LAST_WORDS):
        return Action(request.kind, request.actor, text="...")
    if request.kind is ActionKind.BID:
        return Action(ActionKind.BID, request.actor, priority=5)
    return Action(request.kind, request.actor)


def _parse_json(raw: str) -> dict | None:
    result, _ = _parse_json_with_diag(raw)
    return result


def _parse_json_with_diag(raw: str) -> tuple[dict | None, dict]:
    """Parse a model reply and return (result, diagnostic metadata)."""
    diag: dict = {
        "char_count": len(raw),
        "braces_balanced": raw.count("{") == raw.count("}"),
        "brackets_balanced": raw.count("[") == raw.count("]"),
        "parse_error": None,
        "recovered_by": "none",
    }
    if not raw:
        diag["parse_error"] = "empty"
        return None, diag
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    if start < 0:
        diag["parse_error"] = "no_json_object"
        return None, diag
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                result, method, error = _loads_lenient_diag(candidate)
                diag["recovered_by"] = method
                diag["parse_error"] = error
                return (result, diag) if result is not None else (None, diag)
    # Unbalanced braces: the reply was truncated. Try closing the open braces.
    candidate = text[start:]
    open_braces = candidate.count("{") - candidate.count("}")
    if open_braces > 0:
        result, method, error = _loads_lenient_diag(candidate + "}" * open_braces)
        diag["recovered_by"] = method or "brace_completion"
        diag["parse_error"] = error
        return (result, diag) if result is not None else (None, diag)
    diag["parse_error"] = "unbalanced"
    return None, diag


def _loads_lenient(candidate: str) -> dict | None:
    result, _, _ = _loads_lenient_diag(candidate)
    return result


def _loads_lenient_diag(candidate: str) -> tuple[dict | None, str, str | None]:
    import re

    try:
        result = json.loads(candidate)
        return (result, "direct", None) if isinstance(result, dict) else (None, "none", "not_a_dict")
    except json.JSONDecodeError as exc:
        repaired = re.sub(r",\s*([}\]])$", r"\1", candidate)
        repaired = re.sub(r",\s*([}\]])$", r"\1", repaired)
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                return result, "trailing_comma", None
        except json.JSONDecodeError:
            pass
        normalized = _normalize_event_refs(candidate)
        if normalized != candidate:
            try:
                result = json.loads(normalized)
                if isinstance(result, dict):
                    return result, "event_ref", None
            except json.JSONDecodeError:
                pass
        return None, "none", f"json_decode:{exc.msg}"


def _normalize_event_refs(text: str) -> str:
    """Normalize bare E{int} tokens ONLY inside evidence / fabricated_event
    values. String fields (reasoning, public_statement, true_basis, ...) are
    never touched."""
    import re

    def fix_value(match: re.Match) -> str:
        head = match.group(1)
        value = match.group(2)
        value = re.sub(r"(?<![0-9A-Za-z_\"])E(\d+)(?![0-9A-Za-z_])", r"\1", value)
        return head + value

    return re.sub(
        r'("(?:evidence|fabricated_event)"\s*:\s*)(\[[^\]]*\]|[^,\]}]+)',
        fix_value,
        text,
    )
