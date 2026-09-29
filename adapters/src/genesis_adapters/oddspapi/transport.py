"""Transport protocol and result type (design sections 7.7, 14.6, 17). No network code here.

Every transport returns a :class:`TransportResult`; ordinary failures are converted to the
sanitized ``NO_RESPONSE`` / ``TRUNCATED`` form (class name and errno only) and never raised.
Process-control exceptions (``KeyboardInterrupt``, ``SystemExit``) are not this module's
business: they propagate untouched (FRZ-11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from genesis_adapters.clock import TrustedClock
from genesis_adapters.oddspapi.endpoints import CanonicalRequest


@dataclass(frozen=True)
class TransportResult:
    outcome: Literal["RESPONSE", "NO_RESPONSE", "TRUNCATED"]
    http_status: int | None
    headers: tuple[tuple[str, str], ...]
    body: bytes | None
    sanitized_error: dict | None
    request_started_at: str
    response_received_at: str | None


class Transport(Protocol):
    def send(self, request: CanonicalRequest, *, clock: TrustedClock, deadline_at: str) -> TransportResult:
        """Send ``request``; the whole attempt must finish before ``deadline_at`` (= Tq + timeout)."""


def sanitize_exception(exc: BaseException) -> dict:
    """The only thing ever recorded about a transport failure: exception class name and errno.

    Never ``str(exc)``, ``exc.args``, attributes, notes, ``__cause__`` or ``__context__``.
    """

    code = getattr(exc, "errno", None)
    return {"class": type(exc).__name__, "errno": code if type(code) is int else None}
