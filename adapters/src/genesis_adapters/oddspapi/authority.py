"""Approval gate records and gate checks (design 16).

Code can CHECK gates; only a human can SATISFY them. ``authority.jsonl`` is operator-owned: the only
writer is ``cli.py approve``, which refuses to run without an interactive terminal and a typed
confirmation phrase (design 16.6). Adapter runtime code only ever reads it.

``LiveGate`` is what a live runner passes to the acquisition runner. Before any live send it requires:
a G1 record valid now whose credential fingerprint matches the loaded key; a recorded OS time-sync
attestation; and either a G2 record (live verification: only its pinned request hashes, at most
``max_calls`` sends, inside its window) or a G2R record (recurring capture: the running
``derivation_version`` and ``policy_digest``). Anything missing, expired or mismatched raises
``GateMissing``. Honest limit (design 16.6): file-level controls cannot prove a human wrote a record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from genesis.registry import AppendOnlyJsonl
from genesis.time import TimestampError, iso_utc, parse_utc

from genesis_adapters.errors import GateMissing
from genesis_adapters.oddspapi.acquisition import LIVE_SEND

SCHEMA_VERSION = "adapter-authority-v1"
MODE_VERIFICATION = "G2"
MODE_RECURRING = "G2R"
_COMMON = frozenset({"record_type", "schema_version", "gate", "approval_reference", "approver", "granted_at"})
_GATE_KEYS = {
    "G1": frozenset({"terms_snapshot_sha256", "licensing_note", "credential_fingerprint", "credential_path_policy",
                     "valid_through"}),
    "G2": frozenset({"request_hashes", "max_calls", "valid_from", "valid_through"}),
    "G2R": frozenset({"derivation_version", "policy_digest", "plan_digest", "valid_from", "valid_through"}),
    "G3": frozenset({"derivation_version", "source_id", "contract_id", "review_reference", "acceptance_evidence",
                     "unobserved_paths_accepted", "observation_window"}),
}
_CHAIN = frozenset({"previous_hash", "sequence", "record_hash"})
_ACCEPTANCE = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7", "AC-8", "AC-9")
GATE_LIMITS_FILE = "oddspapi_gate_limits.json"
_LIMIT_KEYS = frozenset({"schema", "g2_requests_cap", "g2_window_hours", "g2r_window_days"})


@dataclass(frozen=True)
class GateLimits:
    """Design 16.3/16.4 bounds, read from the pinned ``oddspapi_gate_limits.json`` (FRZ-10: no literal bounds)."""

    g2_requests_cap: int
    g2_window_hours: int
    g2r_window_days: int


def load_gate_limits(config_dir: Path) -> GateLimits:
    body = json.loads((Path(config_dir) / GATE_LIMITS_FILE).read_text(encoding="utf-8"))
    if type(body) is not dict or set(body) != _LIMIT_KEYS or body["schema"] != "genesis.adapters.gate-limits.v1":
        raise AuthorityRecordInvalid("the gate limits file has an unexpected shape")
    values = {name: body[name] for name in _LIMIT_KEYS - {"schema"}}
    if any(type(value) is not int or value < 1 for value in values.values()):
        raise AuthorityRecordInvalid("gate limits must be positive integers")
    return GateLimits(**values)


class AuthorityRecordInvalid(ValueError):
    """A gate record that is malformed (checked on append by the operator CLI and on every read)."""


def _bad(message: str) -> None:
    raise AuthorityRecordInvalid(message)


def _time(value: Any, name: str):
    if type(value) is not str:
        _bad(f"{name} must be a timestamp")
    try:
        moment = parse_utc(value)
    except TimestampError:
        _bad(f"{name} is not a UTC timestamp")
    if iso_utc(value) != value:
        _bad(f"{name} is not canonical")
    return moment


def _digest(value: Any, name: str) -> None:
    if type(value) is not str or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        _bad(f"{name} must be a lowercase SHA-256 digest")


def validate_record(row: Mapping[str, Any], limits: GateLimits) -> None:
    """Closed schema per gate (design 16.2 .. 16.5)."""

    gate = row.get("gate")
    keys = _GATE_KEYS.get(gate)
    if keys is None or row.get("record_type") != "gate_record" or row.get("schema_version") != SCHEMA_VERSION:
        _bad("unknown gate record")
    if set(row) - _CHAIN != keys | _COMMON:
        _bad(f"{gate} record has unexpected or missing keys")
    for name in ("approval_reference", "approver"):
        if type(row[name]) is not str or not row[name].strip():
            _bad(f"{name} is required")
    granted = _time(row["granted_at"], "granted_at")
    if gate == "G1":
        _digest(row["terms_snapshot_sha256"], "terms_snapshot_sha256")
        if _time(row["valid_through"], "valid_through") <= granted:
            _bad("a G1 record must be valid after it is granted")
        for name in ("licensing_note", "credential_fingerprint", "credential_path_policy"):
            if type(row[name]) is not str or not row[name]:
                _bad(f"{name} is required")
    elif gate in ("G2", "G2R"):
        start, end = _time(row["valid_from"], "valid_from"), _time(row["valid_through"], "valid_through")
        if not start < end:
            _bad("an empty validity window")
        if gate == "G2":
            hashes = row["request_hashes"]
            if type(hashes) is not list or not hashes or len(hashes) > limits.g2_requests_cap \
                    or len(set(hashes)) != len(hashes):
                _bad("G2 pins a bounded list of distinct request hashes")
            for item in hashes:
                _digest(item, "request hash")
            if row["max_calls"] != len(hashes):
                _bad("G2 max_calls equals the number of pinned requests")
            if end - start > timedelta(hours=limits.g2_window_hours):
                _bad("the G2 window is too long")
        else:
            _digest(row["policy_digest"], "policy_digest")
            _digest(row["plan_digest"], "plan_digest")
            if end - start > timedelta(days=limits.g2r_window_days):
                _bad("the G2R window is too long")
    else:
        evidence = row["acceptance_evidence"]
        if type(evidence) is not dict or set(evidence) != set(_ACCEPTANCE):
            _bad("G3 needs evidence for exactly AC-1 .. AC-9")
        for value in evidence.values():
            _digest(value, "acceptance evidence")
        window = row["observation_window"]
        if type(window) is not dict or set(window) != {"from", "to"}:
            _bad("G3 needs an observation window")
        if not _time(window["from"], "from") < _time(window["to"], "to"):
            _bad("an empty observation window")
        if type(row["unobserved_paths_accepted"]) is not list:
            _bad("unobserved_paths_accepted must be a list")


class AdapterAuthorityLedger:
    """``authority.jsonl``. Reading is for everyone; appending is for ``cli.py approve`` only."""

    def __init__(self, path: Path, *, limits: GateLimits):
        self.path = Path(path)
        self.limits = limits
        self.log = AppendOnlyJsonl(self.path, reader=self._replay)

    def _replay(self, rows) -> None:
        for row in rows:
            validate_record(row, self.limits)

    def records(self, gate: str | None = None) -> list[dict[str, Any]]:
        return [row for row in self.log.records() if gate is None or row.get("gate") == gate]

    def _valid(self, gate: str, at: str, predicate: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
        moment = parse_utc(at)
        for row in reversed(self.records(gate)):
            start = parse_utc(row.get("valid_from", row["granted_at"]))
            end = row.get("valid_through")
            if parse_utc(row["granted_at"]) <= moment and start <= moment and (end is None or moment <= parse_utc(end)) \
                    and predicate(row):
                return row
        raise GateMissing(gate)

    def require_gate(self, gate: str, *, at: str, **pins: Any) -> dict[str, Any]:
        """The newest record of ``gate`` valid at ``at`` whose fields equal every pin (``request_hash`` must be
        listed in a G2 record's ``request_hashes``)."""

        def matches(row: Mapping[str, Any]) -> bool:
            for name, value in pins.items():
                if name == "request_hash":
                    if value not in row.get("request_hashes", ()):
                        return False
                elif row.get(name) != value:
                    return False
            return True

        return self._valid(gate, at, matches)

    def append(self, row: Mapping[str, Any]) -> None:
        """Only for ``cli.py approve`` (FRZ-08-style static test: no other module calls it)."""

        validate_record(row, self.limits)
        self.log.append(dict(row))


class LiveGate:
    """The ``authority`` a live acquisition runner uses (G-01, G-02)."""

    def __init__(self, ledger: AdapterAuthorityLedger, *, mode: str, credential_fingerprint: str,
                 derivation_version: str, policy_digest: str, attestation: Mapping[str, Any] | None,
                 sent_count: Callable[[Iterable[str], str], int]):
        if mode not in (MODE_VERIFICATION, MODE_RECURRING):
            raise ValueError("mode must be G2 or G2R")
        self.ledger, self.mode = ledger, mode
        self.fingerprint, self.derivation_version, self.policy_digest = (credential_fingerprint, derivation_version,
                                                                          policy_digest)
        self.attestation = attestation
        self.sent_count = sent_count

    def require_gate(self, gate: str, *, at: str, provider_request_hash: str, role: str, **_pins) -> dict[str, Any]:
        if gate != LIVE_SEND:
            raise GateMissing(gate)
        if not (isinstance(self.attestation, Mapping) and self.attestation.get("synchronized") is True):
            raise GateMissing("TIME_SYNC_ATTESTATION")
        self.ledger.require_gate("G1", at=at, credential_fingerprint=self.fingerprint)
        if self.mode == MODE_VERIFICATION:
            record = self.ledger.require_gate("G2", at=at, request_hash=provider_request_hash)
            if self.sent_count(record["request_hashes"], record["valid_from"]) >= record["max_calls"]:
                raise GateMissing("G2_CALLS_EXHAUSTED")
            return record
        return self.ledger.require_gate("G2R", at=at, derivation_version=self.derivation_version,
                                        policy_digest=self.policy_digest)


def sent_counter(acquisition_ledger) -> Callable[[Iterable[str], str], int]:
    """How many attempts for the given request hashes reached ``sent`` at or after ``since``."""

    def count(hashes: Iterable[str], since: str) -> int:
        wanted = set(hashes)
        requests: dict[str, str] = {}
        total = 0
        for row in acquisition_ledger.rows():
            if row["record_type"] == "acq_planned":
                requests[row["acquisition_id"]] = row["provider_request_hash"]
            elif row["record_type"] == "acq_sent" and requests.get(row["acquisition_id"]) in wanted \
                    and parse_utc(row["T0"]) >= parse_utc(since):
                total += 1
        return total

    return count
