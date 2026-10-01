"""Transport protocol and result type (design sections 7.7, 14.6, 17). No network code here.

Every transport returns a :class:`TransportResult`; ordinary failures are converted to the
sanitized ``NO_RESPONSE`` / ``TRUNCATED`` form (class name and errno only) and never raised.
Process-control exceptions (``KeyboardInterrupt``, ``SystemExit``) are not this module's
business: they propagate untouched (FRZ-11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

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


# What a sanitized error record holds instead of a class name that is not safe to keep: one carrying a form of
# the key (design 7.6 item 3, "the scanner still guards the sanitized record") or one that is not a plain
# bounded identifier. An exception class name is untrusted text (hostile audit HA-01).
REDACTED_EXCEPTION_CLASS = "REDACTED_EXCEPTION_CLASS"
_PLAIN_LABEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def safe_label(name: object, *, max_chars: int, hit: Callable[[bytes], bool] | None = None) -> str:
    """``name`` if it may be recorded: a plain ASCII identifier of at most ``max_chars`` characters that carries no
    section-7.6 form of the key according to ``hit`` (None when no key is configured); otherwise the fixed
    placeholder. Used by every transport boundary and again before persistence."""

    if type(name) is not str or not _PLAIN_LABEL.match(name) or len(name) > max_chars:
        return REDACTED_EXCEPTION_CLASS
    if hit is not None and hit(name.encode("utf-8")):
        return REDACTED_EXCEPTION_CLASS
    return name


def safe_errno(code: object, *, max_chars: int, hit: Callable[[bytes], bool] | None = None) -> int | None:
    """``code`` if it may be recorded: an ``int`` whose decimal form has at most ``max_chars`` characters and carries
    no section-7.6 form of the key according to ``hit``; otherwise None. An ``errno`` attribute is as untrusted as a
    class name (HA-01): it could carry key digits, or be too large to serialize at all."""

    if type(code) is not int:
        return None
    try:
        text = str(code)
    except ValueError:                                    # beyond the interpreter's int-to-text limit: never an errno
        return None
    if len(text) > max_chars or (hit is not None and hit(text.encode("ascii"))):
        return None
    return code


def sanitize_exception(exc: BaseException, *, max_chars: int) -> dict:
    """The only thing ever recorded about a transport failure: a safe class label and a safe integer errno.

    Never ``str(exc)``, ``exc.args``, attributes, notes, ``__cause__`` or ``__context__``. Both are checked for
    shape here; the acquisition runner also scans the record for the key before it is persisted.
    """

    return {"class": safe_label(type(exc).__name__, max_chars=max_chars),
            "errno": safe_errno(getattr(exc, "errno", None), max_chars=max_chars)}
