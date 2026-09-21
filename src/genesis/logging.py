"""Structured append-only operational logging with stable reason codes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .repro import canonical_json
from .time import iso_utc


SENSITIVE_KEYS = frozenset({"password", "token", "secret", "api_key", "certificate", "private_key"})


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(child) for child in value]
    return value


@dataclass(frozen=True)
class LogEvent:
    event_type: str
    occurred_at: str
    component: str
    mode: str
    reason_codes: tuple[str, ...] = ()
    correlation_id: str | None = None
    fields: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _redact(
            {
                "event_type": self.event_type,
                "occurred_at": iso_utc(self.occurred_at),
                "component": self.component,
                "mode": self.mode,
                "reason_codes": list(self.reason_codes),
                "correlation_id": self.correlation_id,
                "fields": self.fields or {},
            }
        )


class JsonlAuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def emit(self, event: LogEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json(event.to_dict())
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

