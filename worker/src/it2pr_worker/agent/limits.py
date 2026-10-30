"""Hard caps for the agent loop (M4, MAJOR-3).

Enforces three independent limits — turns, wall-clock time, and provider-reported
dollar cost — via an injectable monotonic `clock` so tests can advance time
deterministically without sleeping.

Cost is fed from `LLMResponse.usage.cost_usd` (provider-reported, MAJOR-3). When a
response reports `cost_usd is None` the turn/time still count, but cost stays
unknown: we never fabricate a dollar figure to fill the gap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class LimitKind(StrEnum):
    OK = "ok"
    TURNS = "turns"
    TIME = "time"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class LimitStatus:
    """Result of a `LimitTracker.check()` call."""

    kind: LimitKind
    detail: str = ""

    @property
    def exceeded(self) -> bool:
        return self.kind is not LimitKind.OK


class LimitTracker:
    """Tracks turns/time/cost against hard caps.

    `clock` is a callable returning monotonic seconds (default `time.monotonic`);
    inject a fake in tests to advance time deterministically.
    """

    def __init__(
        self,
        max_turns: int = 30,
        wall_clock_seconds: float = 1800.0,
        max_cost_usd: float = 20.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_turns = max_turns
        self.wall_clock_seconds = wall_clock_seconds
        self.max_cost_usd = max_cost_usd
        self._clock = clock
        self._turns = 0
        self._cost_usd = 0.0
        self._cost_known = True
        self._started_at: float | None = None

    @property
    def turns(self) -> int:
        return self._turns

    @property
    def cost_usd(self) -> float | None:
        """Accumulated provider-reported cost, or None if any turn was unknown."""
        return self._cost_usd if self._cost_known else None

    def start(self) -> None:
        self._started_at = self._clock()

    def record_turn(self) -> None:
        self._turns += 1

    def add_cost(self, usd: float | None) -> None:
        if usd is None:
            self._cost_known = False
            return
        self._cost_usd += usd

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return self._clock() - self._started_at

    def check(self) -> LimitStatus:
        if self._turns >= self.max_turns:
            return LimitStatus(
                LimitKind.TURNS,
                f"reached max_turns={self.max_turns}",
            )
        if self.elapsed_seconds() >= self.wall_clock_seconds:
            return LimitStatus(
                LimitKind.TIME,
                f"reached wall_clock_seconds={self.wall_clock_seconds}",
            )
        if self._cost_known and self._cost_usd >= self.max_cost_usd:
            return LimitStatus(
                LimitKind.COST,
                f"reached max_cost_usd={self.max_cost_usd}",
            )
        return LimitStatus(LimitKind.OK)
