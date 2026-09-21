"""Explicit UTC and point-in-time availability semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc


class TimestampError(ValueError):
    pass


def parse_utc(value: str | datetime) -> datetime:
    """Parse an aware UTC timestamp; reject naive or non-UTC values."""

    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise TimestampError(f"invalid ISO timestamp: {value!r}") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TimestampError("timestamps must include an explicit UTC offset")
    if value.utcoffset() != timedelta(0):
        raise TimestampError("timestamps must be UTC")
    return value.astimezone(UTC)


def iso_utc(value: str | datetime) -> str:
    return parse_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class AvailabilityWindow:
    """The earliest time a source value is valid for decision use."""

    available_at: datetime
    ready_at: datetime
    source_published_at: datetime | None = None

    def __post_init__(self) -> None:
        available = parse_utc(self.available_at)
        ready = parse_utc(self.ready_at)
        if ready < available:
            raise TimestampError("ready_at cannot precede available_at")
        if self.source_published_at is not None:
            published = parse_utc(self.source_published_at)
            object.__setattr__(self, "source_published_at", published)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "ready_at", ready)

    def is_ready_by(self, decision_at: datetime) -> bool:
        return self.ready_at <= parse_utc(decision_at)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "available_at": iso_utc(self.available_at),
            "ready_at": iso_utc(self.ready_at),
            "source_published_at": (
                iso_utc(self.source_published_at)
                if self.source_published_at is not None
                else None
            ),
        }


def assert_pit_available(
    *, decision_at: datetime, available_at: datetime, ready_at: datetime
) -> None:
    decision = parse_utc(decision_at)
    available = parse_utc(available_at)
    ready = parse_utc(ready_at)
    if available > decision:
        raise TimestampError("source was not available at decision time")
    if ready > decision:
        raise TimestampError("source was not parse-ready at decision time")


def reject_future_timestamp(value: Any, decision_at: datetime, *, field: str) -> None:
    """Fail closed for a timestamp that would make a value look historical."""

    if value is None:
        return
    if parse_utc(value) > parse_utc(decision_at):
        raise TimestampError(f"{field} is after decision time")
