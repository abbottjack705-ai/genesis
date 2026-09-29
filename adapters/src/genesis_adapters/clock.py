"""Trusted clock (design section 6.1).

``SystemUtcClock`` is the only production clock. It is monotonic, checks wall-clock jumps
against a monotonic source, and never returns a value earlier than its previous one.
Parsers and normalizers never read a clock; every time they use is passed in.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from genesis.time import TimestampError, iso_utc, parse_utc

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ClockFault(RuntimeError):
    """The clock cannot be trusted; the runner halts. ``code`` is a stable reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TrustedClock(Protocol):
    def now(self) -> str:
        """Canonical ``iso_utc`` (microseconds, ``Z``)."""


class SystemUtcClock:
    """Wall time with a monotonic drift check, a monotonicity check and an optional floor."""

    def __init__(self, *, drift_max_ms: int, floor: str | None = None,
                 wall_ns: Callable[[], int] = time.time_ns,
                 mono_ns: Callable[[], int] = time.monotonic_ns):
        if type(drift_max_ms) is not int or drift_max_ms <= 0:
            raise ValueError("drift_max_ms must be a positive integer")
        self._drift_ns = drift_max_ms * 10 ** 6
        self._wall_ns = wall_ns
        self._mono_ns = mono_ns
        self._wall0 = wall_ns()
        self._mono0 = mono_ns()
        self._last: int | None = None
        self._floor_ns: int | None = None
        if floor is not None:
            floor_delta = parse_utc(floor) - _EPOCH
            self._floor_ns = (floor_delta // timedelta(microseconds=1)) * 10 ** 3

    def now(self) -> str:
        wall = self._wall_ns()
        mono = self._mono_ns()
        if abs((wall - self._wall0) - (mono - self._mono0)) > self._drift_ns:
            raise ClockFault("WALL_CLOCK_JUMP")
        if self._last is not None and wall < self._last:
            raise ClockFault("CLOCK_REGRESSION")
        if self._floor_ns is not None and wall < self._floor_ns:
            raise ClockFault("CLOCK_BEHIND_FLOOR")
        self._last = wall
        return iso_utc(_EPOCH + timedelta(microseconds=wall // 10 ** 3))


def require_not_before(now: str, *durable_heads: str | None) -> None:
    """The clock must not be earlier than any durable head it is about to extend."""

    try:
        current = parse_utc(now)
        for head in durable_heads:
            if head is not None and current < parse_utc(head):
                raise ClockFault("CLOCK_BEHIND_DURABLE")
    except TimestampError:
        raise ClockFault("CLOCK_UNPARSEABLE") from None


def is_production_clock(candidate: object) -> bool:
    """True only for a genuine ``SystemUtcClock`` (no subclass, no look-alike)."""

    return type(candidate) is SystemUtcClock
