"""ai_werewolf — AI狼人杀: a werewolf engine for human vs AI multi-agent play.

The public API is re-exported here. See the README for the product overview
and the architecture document for how the layers fit together.
"""

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.personas import NEUTRAL, PERSONAS, Persona, assign_personas
from ai_werewolf.ai.provider import (
    PRESETS,
    ModelConfig,
    ModelRunStats,
    OpenAICompatProvider,
    Prompt,
    Provider,
    ProviderError,
)
from ai_werewolf.analysis import (
    DecisionQualityReport,
    analyze_decision_quality,
    analyze_transcript,
    classify_failure,
)
from ai_werewolf.balance import BalanceReport, run_balance
from ai_werewolf.benchmark import ArenaReport, run_arena
from ai_werewolf.copilot.advisor import Advice, Suspicion, advise
from ai_werewolf.copilot.calibration import CalibrationReport, evaluate_copilot
from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import GamePhase, Referee
from ai_werewolf.domain.roles import MVP_SEATS, Faction, Role, build_roster
from ai_werewolf.domain.state import (
    DecisionRequest,
    GameConfig,
    GameState,
    PlayerView,
    Seat,
    build_view,
)
from ai_werewolf.domain.trace import DECEPTION_THRESHOLD, DecisionRecord
from ai_werewolf.players.human import HumanPlayer
from ai_werewolf.players.llm_bot import LLMBot
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.replay.recorder import (
    SCHEMA,
    load,
    record_game,
    record_session,
    replay_text,
    save,
    traces_text,
)
from ai_werewolf.server.admin import AdminBackend, ServerStats
from ai_werewolf.server.matchmaking import Matchmaker
from ai_werewolf.server.room import AIConfig, Room, RoomConfig, RoomStatus
from ai_werewolf.server.session import GameSession
from ai_werewolf.stats.ledger import PlayerRecord, StatsLedger

__version__ = "0.2.0"

__all__ = [
    "MockProvider",
    "DecisionQualityReport",
    "analyze_decision_quality",
    "analyze_transcript",
    "classify_failure",
    "NEUTRAL",
    "PERSONAS",
    "Persona",
    "assign_personas",
    "PRESETS",
    "ModelConfig",
    "ModelRunStats",
    "OpenAICompatProvider",
    "Prompt",
    "Provider",
    "ProviderError",
    "ArenaReport",
    "run_arena",
    "BalanceReport",
    "run_balance",
    "Advice",
    "Suspicion",
    "advise",
    "CalibrationReport",
    "evaluate_copilot",
    "Action",
    "ActionKind",
    "EventKind",
    "GameEvent",
    "GamePhase",
    "Referee",
    "Faction",
    "MVP_SEATS",
    "Role",
    "build_roster",
    "DecisionRequest",
    "GameConfig",
    "GameState",
    "PlayerView",
    "Seat",
    "build_view",
    "DECEPTION_THRESHOLD",
    "DecisionRecord",
    "HumanPlayer",
    "LLMBot",
    "RandomBot",
    "SCHEMA",
    "load",
    "record_game",
    "record_session",
    "replay_text",
    "save",
    "traces_text",
    "AdminBackend",
    "ServerStats",
    "Matchmaker",
    "AIConfig",
    "Room",
    "RoomConfig",
    "RoomStatus",
    "GameSession",
    "PlayerRecord",
    "StatsLedger",
    "__version__",
]
