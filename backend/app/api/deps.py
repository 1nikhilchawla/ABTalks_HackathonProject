"""Process-wide singletons wired at startup."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings, get_settings
from ..engine.orchestrator import Orchestrator
from ..llm.router import LLMRouter
from ..security.ratelimit import RateLimiter
from ..store.session_store import SessionLocks, SessionStore


@dataclass
class Services:
    settings: Settings
    router: LLMRouter
    store: SessionStore
    locks: SessionLocks
    limiter: RateLimiter
    orchestrator: Orchestrator


_services: Services | None = None


def build_services(settings: Settings | None = None) -> Services:
    global _services
    settings = settings or get_settings()
    router = LLMRouter(settings)
    _services = Services(
        settings=settings,
        router=router,
        store=SessionStore(settings.db_path, settings.session_ttl_seconds),
        locks=SessionLocks(),
        limiter=RateLimiter(settings.rate_limit_per_minute),
        orchestrator=Orchestrator(router, settings),
    )
    return _services


def get_services() -> Services:
    if _services is None:  # pragma: no cover - startup always builds them
        return build_services()
    return _services


async def shutdown_services() -> None:
    global _services
    if _services is None:
        return
    await _services.router.aclose()
    _services.store.close()
    _services = None
