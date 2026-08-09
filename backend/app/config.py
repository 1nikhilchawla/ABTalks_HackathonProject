"""Runtime configuration, loaded once from the environment.

Every knob that affects interview behaviour lives here so the engine itself
stays free of magic numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent.parent


def _env_str(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "").strip() or default)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env_str(key).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class InterviewLimits:
    """Hard bounds that make the interview provably terminate."""

    min_questions: int = 8
    max_questions: int = 14
    min_distinct_days: int = 4
    max_followups_per_topic: int = 2
    max_turns: int = 60
    max_consecutive_non_answers: int = 3
    max_answer_chars: int = 6000
    soft_time_budget_seconds: int = 20 * 60


@dataclass(frozen=True)
class Settings:
    # --- LLM providers -------------------------------------------------
    anthropic_api_key: str = field(default_factory=lambda: _env_str("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(
        default_factory=lambda: _env_str("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    )
    anthropic_base_url: str = field(
        default_factory=lambda: _env_str("ANTHROPIC_API_BASE", "https://api.anthropic.com")
    )

    openai_api_key: str = field(default_factory=lambda: _env_str("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env_str("OPENAI_MODEL", "gpt-4o-mini"))
    openai_base_url: str = field(
        default_factory=lambda: _env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )

    groq_api_key: str = field(default_factory=lambda: _env_str("GROQ_API_KEY"))
    groq_model: str = field(
        default_factory=lambda: _env_str("GROQ_MODEL", "llama-3.3-70b-versatile")
    )
    groq_base_url: str = field(
        default_factory=lambda: _env_str("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    )

    # Explicit override: anthropic | openai | groq | heuristic | auto
    llm_provider: str = field(default_factory=lambda: _env_str("LLM_PROVIDER", "auto").lower())

    # --- Reliability ---------------------------------------------------
    llm_timeout_seconds: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 45.0))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))
    llm_breaker_threshold: int = field(default_factory=lambda: _env_int("LLM_BREAKER_THRESHOLD", 4))
    llm_breaker_cooldown: float = field(
        default_factory=lambda: _env_float("LLM_BREAKER_COOLDOWN", 30.0)
    )

    # --- Storage -------------------------------------------------------
    db_path: str = field(
        default_factory=lambda: _env_str("DB_PATH", str(PROJECT_ROOT / "data" / "sessions.db"))
    )
    session_ttl_seconds: int = field(
        default_factory=lambda: _env_int("SESSION_TTL_SECONDS", 24 * 3600)
    )

    # --- Server --------------------------------------------------------
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in _env_str(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if o.strip()
        )
    )
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 90))
    expose_trace: bool = field(default_factory=lambda: _env_bool("EXPOSE_TRACE", True))
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())

    limits: InterviewLimits = field(default_factory=InterviewLimits)

    #: Point this at any curriculum JSON with the same shape. Nothing in the
    #: engine hardcodes day numbers, so a different cohort needs no code change.
    curriculum_file: str = field(default_factory=lambda: _env_str("CURRICULUM_PATH"))

    @property
    def curriculum_path(self) -> Path:
        if self.curriculum_file:
            candidate = Path(self.curriculum_file)
            if not candidate.is_absolute():
                candidate = APP_ROOT / "data" / self.curriculum_file
            return candidate
        return APP_ROOT / "data" / "curriculum.json"

    @property
    def candidates_path(self) -> Path:
        return APP_ROOT / "data" / "candidates.json"

    def resolved_provider_chain(self) -> list[str]:
        """Ordered provider names to try. Always ends with the offline engine."""
        if self.llm_provider != "auto":
            chain = [self.llm_provider]
        else:
            chain = []
            if self.anthropic_api_key:
                chain.append("anthropic")
            if self.openai_api_key:
                chain.append("openai")
            if self.groq_api_key:
                chain.append("groq")
        if "heuristic" not in chain:
            chain.append("heuristic")
        return chain


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
