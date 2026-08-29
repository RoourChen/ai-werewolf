"""ai_werewolf — an LLM werewolf engine (AI狼人杀).

ai_werewolf does two things with the game of Werewolf (Mafia):

* **self-play arena** — LLM agents play each other so you can benchmark how
  well a model reasons, deceives and deduces under hidden information;
* **human copilot** — an explainable advisor that estimates who the werewolves
  are and recommends your vote while *you* play.

It is an independent project derived from `deepwolf
<https://github.com/JuneQQQ/deepwolf>`_ (see the LICENSE for attribution). The
public API is re-exported here; see the README for usage.
"""

from ai_werewolf.agents.base import Agent
from ai_werewolf.agents.human_agent import HumanAgent
from ai_werewolf.agents.llm_agent import LLMAgent
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.arena.leaderboard import Leaderboard, LeaderboardReport
from ai_werewolf.arena.runner import Arena, ArenaReport
from ai_werewolf.copilot.advisor import Advice, Suspicion, advise
from ai_werewolf.copilot.calibration import CalibrationReport, evaluate_copilot
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import GameConfig, GameResult, PlayerView
from ai_werewolf.i18n import LANGUAGES, Translator
from ai_werewolf.llm.mock import MockProvider
from ai_werewolf.llm.provider import (
    LLMConfig,
    LLMError,
    LLMProvider,
    OpenAICompatProvider,
)

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "HumanAgent",
    "LLMAgent",
    "RandomAgent",
    "Arena",
    "ArenaReport",
    "Leaderboard",
    "LeaderboardReport",
    "Advice",
    "Suspicion",
    "advise",
    "CalibrationReport",
    "evaluate_copilot",
    "GameEngine",
    "Faction",
    "Role",
    "GameConfig",
    "GameResult",
    "PlayerView",
    "LANGUAGES",
    "Translator",
    "MockProvider",
    "LLMConfig",
    "LLMError",
    "LLMProvider",
    "OpenAICompatProvider",
    "__version__",
]
