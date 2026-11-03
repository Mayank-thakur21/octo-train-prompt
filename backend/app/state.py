"""Per-application runtime objects shared by routers and services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from app.db import Database
    from app.providers.registry import ProviderRegistry
    from app.security import ApiKeyVerifier, RateLimiter


@dataclass
class AppState:
    """Everything one app instance owns. Stored as ``app.state.studio``."""

    settings: Settings
    registry: ProviderRegistry
    db: Database
    limiter: RateLimiter
    verifier: ApiKeyVerifier
    provider_semaphore: asyncio.Semaphore
    #: Background evaluation tasks by eval run id (removed when they finish).
    eval_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
