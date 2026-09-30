"""Acquisition ledger, UTC boundary guard, retry policy and the acquisition runner.

Order of every attempt (design sections 11.1, 14): plan -> gates -> boundary guard -> Genesis
quota reservation -> send -> classify -> durable record. The guard runs BEFORE the ledger call on
the SAME ``Tq`` read, so a refused send is never debited. Nothing here parses or normalizes a
payload; raw capture, secret scanning and normalization are later stages that plug into this
runner's ``completed`` outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from genesis.coverage import CoverageEntry, CoverageLedger, CoverageStatus
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.repro import canonical_json, immutable_write, sha256_bytes
from genesis.time import TimestampError, iso_utc, parse_utc

from genesis_adapters.clock import ClockFault, TrustedClock, is_production_clock, require_not_before
from genesis_adapters.errors import (
    AcquisitionHalt, AdapterFailure, CredentialProblem, GateMissing, reason_code,
)
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi.endpoints import RAW_CONTRACT_ID, CanonicalRequest
from genesis_adapters.oddspapi.quota_gate import QuotaCharge
from genesis_adapters.oddspapi.raw_capture import CaptureConflict, Captured
from genesis_adapters.oddspapi.transport import (
    REDACTED_EXCEPTION_CLASS, Transport, TransportResult, sanitize_exception,
)

SCHEMA_VERSION = "acquisition-ledger-v1"
ATTEMPT_DOMAIN = "genesis.adapters.oddspapi.attempt.v1"
UTC = timezone.utc
HTTP_OK = 200
HTTP_AUTH = (401, 403)
TOO_MANY_REQUESTS = 429
PURPOSES = ("SCHEDULED", "CONDITIONAL", "RETRY", "METADATA", "G2_VERIFICATION")
LIVE_SEND = "LIVE_SEND"             # the one gate check before any live send (authority.LiveGate)
# Provisional (design 21 A12, verified at G2): the provider's count of requests used in its current
# accounting window, reported in an allowlisted response header. Absent -> nothing to reconcile.
PROVIDER_USAGE_HEADER = "x-requests-used"


class AttemptOutcome:
    REFUSED = "REFUSED"
    QUOTA_BLOCKED = "QUOTA_BLOCKED"
    CACHE_HIT = "CACHE_HIT"
    NO_RESPONSE = "NO_RESPONSE"
    TRUNCATED = "TRUNCATED"
    RESPONSE = "RESPONSE"
    DUPLICATE = "DUPLICATE"
    ORPHANED = "ORPHANED"           # retry-policy input only: a reconciled, unresolved reservation


# --------------------------------------------------------------------------------------
# UTC day/month boundary guard (design 14.6, W1..W4)
# --------------------------------------------------------------------------------------
class UtcBoundaries:
    """Calendar arithmetic for the guard; tests substitute isolated calculators."""

    def day_start(self, moment: datetime) -> datetime:
        return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)

    def next_day(self, moment: datetime) -> datetime:
        return self.day_start(moment) + timedelta(days=1)

    def month_start(self, moment: datetime) -> datetime:
        return datetime(moment.year, moment.month, 1, tzinfo=UTC)

    def next_month(self, moment: datetime) -> datetime:
        if moment.month == 12:
            return datetime(moment.year + 1, 1, 1, tzinfo=UTC)
        return datetime(moment.year, moment.month + 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class GuardDecision:
    permitted: bool
    failed: str | None
    next_permitted: str | None


def boundary_guard(tq: str, policy, *, boundaries: UtcBoundaries | None = None) -> GuardDecision:
    """W1..W4: no send when ``Tq + timeout + skew`` crosses a UTC day/month boundary, or when
    ``Tq - skew`` precedes the start of Tq's UTC day/month. Every value comes from ``policy``."""

    calendar_ = boundaries or UtcBoundaries()
    moment = parse_utc(tq)
    timeout = timedelta(seconds=policy.request_timeout_seconds)
    skew = timedelta(seconds=policy.clock_skew_max_seconds)
    reach = moment + timeout + skew
    failures: list[tuple[str, datetime]] = []
    next_day, next_month = calendar_.next_day(moment), calendar_.next_month(moment)
    day_start, month_start = calendar_.day_start(moment), calendar_.month_start(moment)
    if not reach < next_day:
        failures.append(("W1", next_day))
    if not reach < next_month:
        failures.append(("W2", next_month))
    if not moment - skew >= day_start:
        failures.append(("W3", day_start))
    if not moment - skew >= month_start:
        failures.append(("W4", month_start))
    if not failures:
        return GuardDecision(True, None, None)
    return GuardDecision(False, failures[0][0], iso_utc(max(edge for _, edge in failures) + skew))


# --------------------------------------------------------------------------------------
# Retry policy (design 14.3)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    reason: str
    earliest: str | None = None


def _retryable(outcome: str, http_status: int | None, failure: AdapterFailure | None) -> bool:
    if outcome == AttemptOutcome.NO_RESPONSE:
        return failure == AdapterFailure.NO_RESPONSE
    if outcome == AttemptOutcome.ORPHANED:               # a reconciled crash: no status was ever seen
        return failure == AdapterFailure.ORPHANED_RESERVATION
    if outcome == AttemptOutcome.RESPONSE and http_status is not None:
        return http_status // 100 == 5 and failure == AdapterFailure.PROVIDER_ERROR
    return False


def retry_decision(*, outcome: str, http_status: int | None, failure: AdapterFailure | None, attempt: int,
                   policy, failed_at: str, now: str, not_after: str | None, quota_headroom: bool,
                   circuit_open: bool) -> RetryDecision:
    """At most ``max_retries_per_window`` retries, only for NO_RESPONSE or 5xx, after the minimum
    backoff, only before ``not_after`` and only with quota headroom and a closed circuit."""

    if not _retryable(outcome, http_status, failure):
        return RetryDecision(False, "NOT_RETRYABLE")
    if attempt - 1 >= policy.max_retries_per_window:
        return RetryDecision(False, "RETRY_LIMIT_REACHED")
    if circuit_open:
        return RetryDecision(False, "CIRCUIT_OPEN")
    if not quota_headroom:
        return RetryDecision(False, "NO_QUOTA_HEADROOM")
    earliest = iso_utc(parse_utc(failed_at) + timedelta(seconds=policy.retry_min_backoff_seconds))
    if parse_utc(now) < parse_utc(earliest):
        return RetryDecision(False, "BACKOFF", earliest)
    if not_after is not None and parse_utc(now) >= parse_utc(not_after):
        return RetryDecision(False, "WINDOW_CLOSED")
    return RetryDecision(True, "RETRY", earliest)


# --------------------------------------------------------------------------------------
# Acquisition ledger (adapter-owned, hash-chained, replay-validated)
# --------------------------------------------------------------------------------------
_CHAIN = frozenset({"previous_hash", "sequence", "record_hash"})
_COMMON = frozenset({"record_type", "schema_version", "recorded_at"})
_ROW_KEYS: dict[str, frozenset[str]] = {
    "acq_planned": frozenset({"acquisition_id", "request_id", "window_id", "purpose", "attempt",
                              "provider_request_hash", "role", "provider_metering",
                              "provider_request_weight", "provider_documented_billable",
                              "genesis_debit_units"}),
    "acq_refused": frozenset({"acquisition_id", "reason", "detail", "not_before"}),
    "acq_quota_decided": frozenset({"acquisition_id", "Tq", "frozen_ledger_reason", "allowed",
                                    "genesis_units_debited", "cache_entry_id", "cache_miss_reason"}),
    "acq_sent": frozenset({"acquisition_id", "T0"}),
    "acq_completed": frozenset({"acquisition_id", "T1", "outcome", "http_status", "headers",
                                "content_encoding", "byte_length", "raw_observation_id",
                                "sanitized_error", "provider_reported_usage", "failure"}),
    "acq_normalized": frozenset({"acquisition_id", "T2", "T3", "derivation_version",
                                 "expected_scope_hash", "identity_registry_head",
                                 "normalized_observation_ids", "pit_record_ids", "coverage_entry_ids"}),
    "acq_quarantined": frozenset({"acquisition_id", "quarantine_id"}),
    "acq_reconciled": frozenset({"acquisition_id", "outcome", "quota_row_found", "send_state"}),
    "acq_circuit_opened": frozenset({"scope", "role", "reason", "until"}),
    "acq_halted": frozenset({"reason"}),
    "acq_operator_reset": frozenset({"approval_reference", "reason"}),
    "acq_sends_suspended": frozenset({"until", "reason"}),
}
_RECONCILE_OUTCOMES = ("ORPHANED_RESERVATION", "NOT_RESERVED")
# ``acq_sent`` is durable BEFORE the transport is called, so its absence proves the request was
# never handed to the transport; its presence without ``acq_completed`` proves nothing more.
_SEND_STATES = ("NOT_SENT", "MAY_HAVE_BEEN_SENT")
_COMPLETED_OUTCOMES = ("RESPONSE", "NO_RESPONSE", "TRUNCATED")
_OPEN_STATES = ("PLANNED", "DECIDED", "SENT")


class LedgerInvariantError(RegistryConflict):
    """A row that would make the acquisition ledger unreadable or inconsistent."""


def _fail(message: str) -> None:
    raise LedgerInvariantError(message)


def _canonical_time(value: Any, name: str) -> datetime:
    if type(value) is not str:
        _fail(f"{name} must be a timestamp string")
    try:
        parsed = parse_utc(value)
        if iso_utc(value) != value:
            _fail(f"{name} is not canonical")
    except TimestampError:
        _fail(f"{name} is not a valid UTC timestamp")
    return parsed


class _Attempt:
    __slots__ = ("state", "tq", "t0", "t1", "t2", "t3", "planned_at", "role", "request_id",
                 "request_hash", "failure", "outcome", "http_status", "reconciled", "send_state")

    def __init__(self):
        self.state = None
        self.tq = self.t0 = self.t1 = self.t2 = self.t3 = self.planned_at = None
        self.role = self.request_id = self.request_hash = self.failure = None
        self.outcome = self.http_status = self.reconciled = self.send_state = None


def _replay(rows) -> dict[str, _Attempt]:
    attempts: dict[str, _Attempt] = {}
    last = None
    for row in rows:
        kind = row.get("record_type")
        keys = _ROW_KEYS.get(kind)
        if keys is None or row.get("schema_version") != SCHEMA_VERSION:
            _fail("unknown acquisition ledger record")
        if set(row) - _CHAIN != keys | _COMMON:
            _fail(f"{kind} has unexpected or missing keys")
        recorded = _canonical_time(row["recorded_at"], "recorded_at")
        if last is not None and recorded < last:
            _fail("recorded_at regressed")
        last = recorded
        if "acquisition_id" not in keys:
            _check_control_row(kind, row)
            continue
        aid = row["acquisition_id"]
        if type(aid) is not str or len(aid) != 64:
            _fail("acquisition_id must be a 64-hex digest")
        item = attempts.setdefault(aid, _Attempt())
        _apply(kind, row, item, recorded)
    return attempts


def _check_control_row(kind: str, row: Mapping[str, Any]) -> None:
    if kind == "acq_circuit_opened":
        if row["scope"] not in ("ROLE", "ALL") or (row["scope"] == "ROLE") != (row["role"] is not None):
            _fail("circuit scope and role disagree")
        if row["until"] is not None:
            _canonical_time(row["until"], "until")
    elif kind == "acq_sends_suspended":
        _canonical_time(row["until"], "until")


def _apply(kind: str, row: Mapping[str, Any], item: _Attempt, recorded: datetime) -> None:
    state = item.state
    if kind == "acq_planned":
        if state is not None:
            _fail("acquisition planned twice")
        item.state, item.planned_at = "PLANNED", recorded
        item.role, item.request_id, item.request_hash = row["role"], row["request_id"], row["provider_request_hash"]
        if row["request_id"] != "oddspapi-attempt:" + row["acquisition_id"]:
            _fail("request_id does not derive from acquisition_id")
        return
    if state is None:
        _fail(f"{kind} without a planned acquisition")
    if kind == "acq_refused":
        if state != "PLANNED":
            _fail("refused only after planned")
        item.state, item.failure = "REFUSED", row["reason"]
        if row["not_before"] is not None:
            _canonical_time(row["not_before"], "not_before")
    elif kind == "acq_quota_decided":
        if state != "PLANNED":
            _fail("quota decision only after planned")
        item.tq = _canonical_time(row["Tq"], "Tq")
        if item.tq < item.planned_at or recorded < item.tq:
            _fail("Tq ordering violated")
        allowed, units = row["allowed"], row["genesis_units_debited"]
        if type(allowed) is not bool or type(units) is not int or units < 0:
            _fail("quota decision fields are malformed")
        if not allowed:
            if units != 0:
                _fail("a blocked decision cannot debit")
            item.state, item.failure = "BLOCKED", "QUOTA_BLOCKED"
        elif row["cache_entry_id"] is not None:
            if units != 0:
                _fail("a cache hit cannot debit")
            item.state = "CACHED"
        else:
            if units < 1:
                _fail("an allowed live attempt debits at least one Genesis unit")
            item.state = "DECIDED"
    elif kind == "acq_sent":
        if state != "DECIDED":
            _fail("sent requires an allowed quota decision")
        item.t0 = _canonical_time(row["T0"], "T0")
        if item.t0 < item.tq or recorded < item.t0:
            _fail("T0 ordering violated")
        item.state = "SENT"
    elif kind == "acq_completed":
        if state not in ("SENT", "DECIDED") or (state == "DECIDED" and row["outcome"] != "NO_RESPONSE"):
            _fail("completed requires a sent attempt")
        if row["outcome"] not in _COMPLETED_OUTCOMES:
            _fail("unknown completed outcome")
        if row["T1"] is None:
            if row["outcome"] != "NO_RESPONSE":
                _fail("T1 is required unless there was no response")
        else:
            if state != "SENT":
                _fail("T1 without a sent attempt")
            item.t1 = _canonical_time(row["T1"], "T1")
            if not item.t1 > item.t0:
                _fail("T1 must follow T0")
            if recorded < item.t1:
                _fail("completed recorded before T1")
        item.state, item.outcome, item.http_status, item.failure = (
            "COMPLETED", row["outcome"], row["http_status"], row["failure"])
    elif kind == "acq_normalized":
        if state != "COMPLETED" or item.t1 is None:
            _fail("normalized requires a completed response")
        item.t2 = _canonical_time(row["T2"], "T2")
        item.t3 = _canonical_time(row["T3"], "T3")
        if not item.t1 <= item.t2 <= item.t3 <= recorded:
            _fail("T1 <= T2 <= T3 ordering violated")
        item.state = "NORMALIZED"
    elif kind == "acq_quarantined":
        if state != "COMPLETED":
            _fail("quarantine only after completed")
        item.state = "QUARANTINED"
    elif kind == "acq_reconciled":
        if state not in _OPEN_STATES or row["outcome"] not in _RECONCILE_OUTCOMES:
            _fail("reconciliation only for an open attempt")
        if row["send_state"] not in _SEND_STATES or type(row["quota_row_found"]) is not bool:
            _fail("reconciliation send_state or quota_row_found is malformed")
        if (row["send_state"] == "MAY_HAVE_BEEN_SENT") != (state == "SENT"):
            _fail("reconciliation send_state contradicts the durable sent row")
        if row["outcome"] == "NOT_RESERVED" and row["send_state"] != "NOT_SENT":
            _fail("an attempt that may have been sent cannot be unreserved")
        item.state, item.reconciled, item.send_state = "RECONCILED", row["outcome"], row["send_state"]


class AcquisitionLedger:
    """Append-only, replay-validated attempt history (``acquisition.jsonl``)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.log = AppendOnlyJsonl(self.path, reader=_replay)

    def append(self, record_type: str, *, recorded_at: str, **fields: Any) -> None:
        self.log.append({"record_type": record_type, "schema_version": SCHEMA_VERSION,
                         "recorded_at": recorded_at, **fields})

    def rows(self) -> list[dict]:
        return self.log.records()

    def attempts(self) -> dict[str, _Attempt]:
        return _replay(self.log.records())

    def last_recorded_at(self) -> str | None:
        rows = self.log.records()
        return rows[-1]["recorded_at"] if rows else None

    def circuit_open(self, role: str, at: str) -> str | None:
        """Reason code of the circuit/halt/suspension that blocks ``role`` at ``at``, else None."""

        moment = parse_utc(at)
        blocking = None
        for row in self.log.records():
            kind = row["record_type"]
            if kind == "acq_operator_reset":
                blocking = None
            elif kind == "acq_halted":
                blocking = row["reason"]
            elif kind == "acq_sends_suspended":
                if moment < parse_utc(row["until"]):
                    blocking = row["reason"]
            elif kind == "acq_circuit_opened":
                if row["scope"] == "ALL" or row["role"] == role:
                    if row["until"] is None or moment < parse_utc(row["until"]):
                        blocking = row["reason"]
        return blocking

    def rate_limited_today(self, moment: datetime) -> int:
        count = 0
        for row in self.log.records():
            if row["record_type"] == "acq_completed" and row["failure"] == AdapterFailure.RATE_LIMITED.value \
                    and row["T1"] is not None and parse_utc(row["T1"]).date() == moment.date():
                count += 1
        return count


# --------------------------------------------------------------------------------------
# Plan items, outcomes and the runner
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanItem:
    window_id: str
    purpose: str
    request: CanonicalRequest
    attempt: int = 1
    not_after: str | None = None


@dataclass(frozen=True)
class AcquisitionOutcome:
    acquisition_id: str
    request_id: str
    outcome: str
    failure: AdapterFailure | None
    charge: QuotaCharge | None = None
    result: TransportResult | None = None
    detail: str | None = None
    next_not_before: str | None = None
    cached_bytes: bytes | None = None
    parsed: Any = None
    captured: Captured | None = None


def attempt_id(request_hash: str, window_id: str, attempt: int) -> str:
    return sha256_bytes(canonical_json({"domain": ATTEMPT_DOMAIN, "provider_request_hash": request_hash,
                                        "window_id": window_id, "attempt": attempt}))


def validate_plan_item(item: PlanItem, config) -> None:
    """Refuse at plan time a role that cannot be bounded before sending (BILL-03)."""

    if item.purpose not in PURPOSES:
        raise ValueError("unknown plan purpose")
    if type(item.attempt) is not int or item.attempt < 1:
        raise ValueError("attempt must be a positive integer")
    config.endpoints[item.request.role].require_usable()


_COVERAGE_STATUS = {
    AdapterFailure.NO_RESPONSE: CoverageStatus.MISSING,
    AdapterFailure.PROVIDER_ERROR: CoverageStatus.MISSING,
    AdapterFailure.ORPHANED_RESERVATION: CoverageStatus.MISSING,
    AdapterFailure.REDIRECT_REFUSED: CoverageStatus.REJECTED,
    AdapterFailure.AUTH_REJECTED: CoverageStatus.REJECTED,
    AdapterFailure.TRUNCATED_BODY: CoverageStatus.REJECTED,
    AdapterFailure.OVERSIZE_BODY: CoverageStatus.REJECTED,
    AdapterFailure.NOT_JSON: CoverageStatus.REJECTED,
    AdapterFailure.INVALID_UTF8: CoverageStatus.REJECTED,
    AdapterFailure.DUPLICATE_KEYS: CoverageStatus.REJECTED,
    AdapterFailure.NONFINITE_NUMBER: CoverageStatus.REJECTED,
    AdapterFailure.WRONG_CONTENT_TYPE: CoverageStatus.REJECTED,
    AdapterFailure.ENVELOPE_SCHEMA_MISMATCH: CoverageStatus.REJECTED,
    AdapterFailure.SCHEMA_DRIFT: CoverageStatus.REJECTED,
    AdapterFailure.CLOCK_SKEW: CoverageStatus.QUARANTINED,
    AdapterFailure.SECRET_ECHO: CoverageStatus.QUARANTINED,
    AdapterFailure.UNINSPECTABLE_BODY: CoverageStatus.QUARANTINED,
    AdapterFailure.QUOTA_REPLAY_BROKEN: CoverageStatus.QUARANTINED,
    AdapterFailure.EVIDENCE_CONFLICT: CoverageStatus.QUARANTINED,
}


class AcquisitionRunner:
    """Reserve -> send -> record, for one plan item at a time (fixture mode until G1/G2)."""

    def __init__(self, *, root: Path, clock: TrustedClock, transport: Transport, quota, authority, config,
                 live: bool, credential_check: Callable[[], None] | None = None,
                 checkpoint: Callable[[str], None] | None = None,
                 capability_blocker: Callable[[str], None] | None = None,
                 capture: Any = None):
        self.capture = capture
        self.root = Path(root)
        self.clock = clock
        self.transport = transport
        self.quota = quota
        self.authority = authority
        self.config = config
        self.live = live
        self.credential_check = credential_check
        self.checkpoint = checkpoint
        self.capability_blocker = capability_blocker
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = AcquisitionLedger(self.root / "acquisition.jsonl")
        self.coverage = CoverageLedger(self.root / "coverage.jsonl")

    # -- small helpers -----------------------------------------------------------------
    def _mark(self, step: str) -> None:
        if self.checkpoint is not None:
            self.checkpoint(step)

    def _stamp(self) -> str:
        return self.clock.now()

    def _record(self, kind: str, at: str, **fields: Any) -> None:
        self.ledger.append(kind, recorded_at=at, **fields)

    def _coverage(self, aid: str, request: CanonicalRequest, status: CoverageStatus, failure: AdapterFailure,
                  at: str) -> None:
        reasons = (reason_code(failure),) if status != CoverageStatus.AVAILABLE else ()
        self.coverage.append(CoverageEntry(
            entry_id=gid("cov", acquisition_id=aid, note=failure.value), entity_id=f"oddspapi-request:"
            f"{request.provider_request_hash}", source_contract_id=RAW_CONTRACT_ID, status=status,
            recorded_at=at, reason_codes=reasons, note=failure.value))

    def _halt(self, aid: str | None, request: CanonicalRequest, failure: AdapterFailure, at: str,
              *, refused: bool, detail: str | None = None) -> None:
        if at:                                              # no timestamp at all: nothing can be recorded
            if refused and aid is not None:
                self._record("acq_refused", at, acquisition_id=aid, reason=failure.value, detail=detail,
                             not_before=None)
            self._record("acq_halted", at, reason=failure.value)
            if aid is not None:
                self._coverage(aid, request, _COVERAGE_STATUS.get(failure, CoverageStatus.NOT_ATTEMPTED),
                               failure, at)
        raise AcquisitionHalt(failure)

    def _refuse(self, aid: str, request_id: str, request: CanonicalRequest, failure: AdapterFailure, at: str,
                *, detail: str | None = None, not_before: str | None = None) -> AcquisitionOutcome:
        self._record("acq_refused", at, acquisition_id=aid, reason=failure.value, detail=detail,
                     not_before=not_before)
        self._coverage(aid, request, CoverageStatus.NOT_ATTEMPTED, failure, at)
        return AcquisitionOutcome(aid, request_id, AttemptOutcome.REFUSED, failure, detail=detail,
                                  next_not_before=not_before)

    def _durable_heads(self) -> tuple[str | None, str | None]:
        return self.quota.head_time(), self.ledger.last_recorded_at()

    # -- live gates ----------------------------------------------------------------------
    def _live_failure(self, tq: str, request: CanonicalRequest) -> tuple[AdapterFailure, str | None] | None:
        if not self.live:
            return None
        if not is_production_clock(self.clock):
            return AdapterFailure.LIVE_CLOCK_REQUIRED, None
        if self.quota.ledger.policy.test_only:
            return AdapterFailure.TEST_POLICY_IN_LIVE, None
        if self.authority is None:
            return AdapterFailure.GATE_MISSING, None
        try:
            self.authority.require_gate(LIVE_SEND, at=tq, provider_request_hash=request.provider_request_hash,
                                        role=request.role)
        except GateMissing as missing:
            return AdapterFailure.GATE_MISSING, str(missing)
        return None

    # -- the attempt -----------------------------------------------------------------------
    def acquire(self, item: PlanItem) -> AcquisitionOutcome:
        request = item.request
        aid = attempt_id(request.provider_request_hash, item.window_id, item.attempt)
        request_id = f"oddspapi-attempt:{aid}"
        existing = self.ledger.attempts().get(aid)
        if existing is not None:
            return self._duplicate(aid, request_id, existing)

        spec = self.config.endpoints[request.role]
        try:
            tq = self._stamp()
        except ClockFault:
            self._halt(None, request, AdapterFailure.CLOCK_FAULT, self.ledger.last_recorded_at() or "",
                       refused=False)
        head_quota, head_ledger = self._durable_heads()
        immutable_write(self.root / "requests" / f"{request.provider_request_hash}.json",
                        request.canonical_bytes())
        behind = False
        try:
            require_not_before(tq, head_quota, head_ledger)
        except ClockFault:
            behind = True
        stamp = max(tq, head_ledger) if behind and head_ledger else tq
        self._record("acq_planned", stamp, acquisition_id=aid, request_id=request_id,
                     window_id=item.window_id, purpose=item.purpose, attempt=item.attempt,
                     provider_request_hash=request.provider_request_hash, role=request.role,
                     provider_metering=spec.provider_metering.value,
                     provider_request_weight=spec.provider_request_weight,
                     provider_documented_billable=spec.provider_documented_billable,
                     genesis_debit_units=spec.genesis_debit_units)
        if not spec.usable:
            return self._refuse(aid, request_id, request, AdapterFailure.ROLE_NOT_USABLE, stamp)
        refusal = self._live_failure(tq, request)
        if refusal is not None:
            return self._refuse(aid, request_id, request, refusal[0], stamp, detail=refusal[1])
        blocking = self.ledger.circuit_open(request.role, stamp)
        if blocking is not None:                            # a durable halt/circuit is honoured first
            return self._refuse(aid, request_id, request, AdapterFailure.CIRCUIT_OPEN, stamp, detail=blocking)
        if behind:
            self._halt(aid, request, AdapterFailure.CLOCK_FAULT, stamp, refused=True)
        if self.live and (self.capture is None or not self.capture.scans_for_secret):
            # live evidence must never be stored unscanned: no scanner, no send (F-04)
            self._halt(aid, request, AdapterFailure.CREDENTIAL_MISSING, tq, refused=True)
        if self.credential_check is not None:
            try:
                self.credential_check()
            except CredentialProblem as problem:
                self._halt(aid, request, AdapterFailure(problem.code), tq, refused=True)
        decision = boundary_guard(tq, self.config.policy)
        if not decision.permitted:
            return self._refuse(aid, request_id, request, AdapterFailure.WINDOW_BOUNDARY_GUARD, tq,
                                detail=decision.failed, not_before=decision.next_permitted)

        self._mark("before_quota")
        try:
            charge = self.quota.reserve(request=request, request_id=request_id, occurred_at=tq,
                                        billable_units=spec.genesis_debit_units)
        except RegistryConflict:
            self._halt(aid, request, AdapterFailure.QUOTA_REPLAY_BROKEN, self._stamp(), refused=True)
        self._mark("after_quota")
        now = self._stamp()
        self._record("acq_quota_decided", now, acquisition_id=aid, Tq=tq,
                     frozen_ledger_reason=charge.reason, allowed=charge.allowed,
                     genesis_units_debited=charge.billable_units, cache_entry_id=charge.cache_entry_id,
                     cache_miss_reason=charge.cache_miss_reason)
        if charge.reason == "quota_event_time_regressed":
            self._halt(aid, request, AdapterFailure.CLOCK_FAULT, now, refused=False)
        if not charge.allowed:
            self._coverage(aid, request, CoverageStatus.NOT_ATTEMPTED, AdapterFailure.QUOTA_BLOCKED, now)
            return AcquisitionOutcome(aid, request_id, AttemptOutcome.QUOTA_BLOCKED,
                                      AdapterFailure.QUOTA_BLOCKED, charge=charge)
        if charge.cache_entry_id is not None:
            return AcquisitionOutcome(aid, request_id, AttemptOutcome.CACHE_HIT, None, charge=charge,
                                      cached_bytes=self.quota.cached_bytes(charge, request))
        self._mark("after_quota_decided")
        return self._send(aid, request_id, request, tq, charge)

    def _send(self, aid: str, request_id: str, request: CanonicalRequest, tq: str,
              charge: QuotaCharge) -> AcquisitionOutcome:
        deadline = parse_utc(tq) + timedelta(seconds=self.config.policy.request_timeout_seconds)
        t0 = self._stamp()
        if parse_utc(t0) >= deadline:                       # not written: the deadline already passed
            error = {"class": "DeadlineElapsedBeforeSend", "errno": None}
            return self._finish_no_response(aid, request_id, request, charge, t0, error, sent=False)
        self._record("acq_sent", t0, acquisition_id=aid, T0=t0)
        self._mark("after_sent")
        try:
            result = self.transport.send(request, clock=self.clock, deadline_at=iso_utc(deadline))
        except ClockFault:
            self._finish_no_response(aid, request_id, request, charge, self._safe_stamp(t0),
                                     {"class": "ClockFault", "errno": None}, sent=True)
            self._halt(aid, request, AdapterFailure.CLOCK_FAULT, self._safe_stamp(t0), refused=False)
        except Exception as exc:                            # a transport that raised: sanitize it
            error = sanitize_exception(exc)
            return self._finish_no_response(aid, request_id, request, charge, self._safe_stamp(t0), error,
                                            sent=True)
        return self._complete(aid, request_id, request, charge, t0, deadline, result)

    def _safe_stamp(self, floor: str) -> str:
        try:
            return max(self._stamp(), floor)
        except ClockFault:
            return floor

    def _scanned_error(self, error: dict) -> dict:
        """Design 7.6 item 3 (hostile audit F-01): the sanitized record is itself scanned before it is persisted.

        Every non-empty ``sanitized_error`` - from ``sanitize_exception`` or reported by a transport - reaches the
        ledger only through ``_finish_no_response``, which calls this first. A record that carries any section-7.6
        form of the key (an exception class named after it, say) keeps its row, because the attempt happened,
        but not its content: a fixed placeholder class and no errno. With no key configured (fixture mode) there
        is no form to find, so the record is kept as sanitized."""

        if self.capture is None or not self.capture.scans_for_secret:
            return error
        if self.capture.hits_secret(canonical_json(error)):
            return {"class": REDACTED_EXCEPTION_CLASS, "errno": None}
        return error

    def _finish_no_response(self, aid, request_id, request, charge, at, error, *, sent: bool) -> AcquisitionOutcome:
        error = self._scanned_error(error)
        self._record("acq_completed", at, acquisition_id=aid, T1=None, outcome="NO_RESPONSE", http_status=None,
                     headers=[], content_encoding=None, byte_length=None, raw_observation_id=None,
                     sanitized_error=error, provider_reported_usage=None,
                     failure=AdapterFailure.NO_RESPONSE.value)
        self._coverage(aid, request, CoverageStatus.MISSING, AdapterFailure.NO_RESPONSE, at)
        return AcquisitionOutcome(aid, request_id, AttemptOutcome.NO_RESPONSE, AdapterFailure.NO_RESPONSE,
                                  charge=charge, detail=error["class"])

    def _classify(self, result: TransportResult) -> AdapterFailure | None:
        status = result.http_status
        if result.outcome == "TRUNCATED":
            return AdapterFailure.TRUNCATED_BODY
        if status == HTTP_OK:
            return None
        if status is not None and status // 100 == 3:
            return AdapterFailure.REDIRECT_REFUSED
        if status in HTTP_AUTH:
            return AdapterFailure.AUTH_REJECTED
        if status == TOO_MANY_REQUESTS:
            return AdapterFailure.RATE_LIMITED
        return AdapterFailure.PROVIDER_ERROR

    def _complete(self, aid, request_id, request, charge, t0, deadline, result: TransportResult) -> AcquisitionOutcome:
        t1 = result.response_received_at
        started = result.request_started_at
        if result.outcome == "NO_RESPONSE":
            error = result.sanitized_error or {"class": "NoResponse", "errno": None}
            return self._finish_no_response(aid, request_id, request, charge, self._safe_stamp(t0), error, sent=True)
        ordered = (t1 is not None and parse_utc(started) >= parse_utc(t0) and parse_utc(t1) > parse_utc(started))
        if not ordered:
            at = self._safe_stamp(t0)
            self._finish_no_response(aid, request_id, request, charge, at,
                                     {"class": "ClockOrderViolation", "errno": None}, sent=True)
            self._halt(aid, request, AdapterFailure.CLOCK_FAULT, at, refused=False)
        if parse_utc(t1) >= deadline:                       # past the hard deadline: the body is discarded
            return self._finish_no_response(aid, request_id, request, charge, self._safe_stamp(t1),
                                            {"class": "DeadlineExceeded", "errno": None}, sent=True)
        failure = self._classify(result)
        captured = None
        if self.capture is not None and result.body is not None:
            try:
                captured = self.capture.store(aid=aid, request=request, result=result, t1=t1)
            except CaptureConflict:
                at = self._safe_stamp(t1)
                self._record("acq_completed", at, acquisition_id=aid, T1=t1, outcome=result.outcome,
                             http_status=result.http_status, headers=[], content_encoding=None,
                             byte_length=None, raw_observation_id=None, sanitized_error=None,
                             provider_reported_usage=None, failure=AdapterFailure.EVIDENCE_CONFLICT.value)
                self._halt(aid, request, AdapterFailure.EVIDENCE_CONFLICT, at, refused=False)
            self._mark("after_raw")
        if captured is not None and captured.kind == "SECRET":
            failure = captured.failure
        elif captured is not None and captured.failure is not None and failure is None:
            failure = captured.failure
        length = captured.byte_length if captured is not None else (
            len(result.body) if result.body is not None else None)
        at = self._safe_stamp(t1)
        usage = self._provider_usage(captured, t1)
        self._record("acq_completed", at, acquisition_id=aid, T1=t1, outcome=result.outcome,
                     http_status=result.http_status,
                     headers=[list(pair) for pair in captured.headers] if captured is not None else [],
                     content_encoding=captured.content_encoding if captured is not None else None,
                     byte_length=length,
                     raw_observation_id=captured.raw_observation_id if captured is not None else None,
                     sanitized_error=None, provider_reported_usage=usage,
                     failure=failure.value if failure else None)
        if usage is not None and usage["reported"] is not None and usage["reported"] > usage["genesis_debited"]:
            # the provider counted more than Genesis debited: the budget can no longer be trusted (F-37)
            self._halt(aid, request, AdapterFailure.QUOTA_DIVERGENCE, at, refused=False)
        parsed = None
        moment = parse_utc(t1)
        if captured is not None and captured.kind in ("SECRET", "UNINSPECTABLE"):
            self._record("acq_quarantined", at, acquisition_id=aid, quarantine_id=captured.quarantine_id)
            if captured.kind == "SECRET":
                self._coverage(aid, request, CoverageStatus.QUARANTINED, AdapterFailure.SECRET_ECHO, at)
                if self.capability_blocker is not None:
                    self.capability_blocker(AdapterFailure.SECRET_ECHO.value)
                self._record("acq_halted", at, reason=AdapterFailure.SECRET_ECHO.value)
                raise AcquisitionHalt(AdapterFailure.SECRET_ECHO)
            self._after_failure(aid, request, failure, at, moment)
        elif failure is not None:
            self._after_failure(aid, request, failure, at, moment)
        elif captured is not None:
            failure, parsed = self._after_success(aid, request, result, captured, t1, at)
        return AcquisitionOutcome(aid, request_id, AttemptOutcome.RESPONSE if result.outcome == "RESPONSE"
                                  else AttemptOutcome.TRUNCATED, failure, charge=charge, result=result,
                                  parsed=parsed, captured=captured)

    def _provider_usage(self, captured: Captured | None, t1: str) -> dict | None:
        """The provider-reported usage (provisional header) next to the Genesis debit of the same UTC month."""

        if captured is None:
            return None
        values = [value for name, value in captured.headers if name == PROVIDER_USAGE_HEADER]
        if not values:
            return None
        text = values[0].strip()
        reported = int(text) if text.isascii() and text.isdigit() else None
        return {"header": PROVIDER_USAGE_HEADER, "reported": reported,
                "genesis_debited": self.quota.ledger.usage(t1)[1], "window": "utc_month"}

    def _after_success(self, aid: str, request: CanonicalRequest, result: TransportResult, captured: Captured,
                       t1: str, at: str) -> tuple[AdapterFailure | None, Any]:
        """HTTP 200 with stored raw bytes: metadata cache publish, then skew/type/JSON/envelope."""

        spec = self.config.endpoints[request.role]
        verdict = self.capture.validate(request=request, captured=captured, t1=t1)
        if verdict.failure is None:
            if spec.cacheable:                # only a response that passed every content check is cached
                self.quota.publish_cache(request, captured.decoded, captured_at=t1,
                                         ttl_seconds=spec.cache_ttl_seconds)
            return None, verdict.parsed
        failure = verdict.failure
        if failure == AdapterFailure.CLOCK_SKEW:
            quarantine_id = self.capture.write_quarantine(aid, request, result, t1, failure.value, set(),
                                                          captured.byte_length)
            self._record("acq_quarantined", at, acquisition_id=aid, quarantine_id=quarantine_id)
            self._record("acq_sends_suspended", at, reason=failure.value,
                         until=iso_utc(UtcBoundaries().next_day(parse_utc(t1))))
        self._coverage(aid, request, _COVERAGE_STATUS.get(failure, CoverageStatus.REJECTED), failure, at)
        return failure, None

    def _after_failure(self, aid: str, request: CanonicalRequest, failure: AdapterFailure, at: str,
                       t1: datetime) -> None:
        status = _COVERAGE_STATUS.get(failure, CoverageStatus.NOT_ATTEMPTED)
        self._coverage(aid, request, status, failure, at)
        if failure == AdapterFailure.AUTH_REJECTED:
            self._record("acq_circuit_opened", at, scope="ALL", role=None, reason=failure.value, until=None)
            if self.capability_blocker is not None:
                self.capability_blocker(failure.value)
        elif failure == AdapterFailure.RATE_LIMITED:
            until = iso_utc(UtcBoundaries().next_day(t1))
            if self.ledger.rate_limited_today(t1) >= 2:
                self._record("acq_circuit_opened", at, scope="ALL", role=None, reason=failure.value, until=until)
            else:
                self._record("acq_circuit_opened", at, scope="ROLE", role=request.role,
                             reason=failure.value, until=until)

    # -- duplicates, restart and retry -------------------------------------------------------
    def _duplicate(self, aid: str, request_id: str, item: _Attempt) -> AcquisitionOutcome:
        if item.state == "RECONCILED" and item.reconciled == "ORPHANED_RESERVATION":
            return AcquisitionOutcome(aid, request_id, AttemptOutcome.REFUSED,
                                      AdapterFailure.ORPHANED_RESERVATION, detail=item.send_state)
        failure = AdapterFailure(item.failure) if item.failure else None
        return AcquisitionOutcome(aid, request_id, AttemptOutcome.DUPLICATE, failure)

    def reconcile_after_restart(self) -> tuple[str, ...]:
        """Close every attempt left open by a crash. Debits stand; nothing is re-sent."""

        now = self._stamp()
        require_not_before(now, *self._durable_heads())
        reconciled: list[str] = []
        for aid, item in self.ledger.attempts().items():
            if item.state not in _OPEN_STATES:
                continue
            row = self.quota.find_request(item.request_id)
            debited = row is not None and row.get("record_type") == "quota_billable_call"
            orphan = item.state in ("DECIDED", "SENT") or (item.state == "PLANNED" and debited)
            at = self._stamp()
            self._record("acq_reconciled", at, acquisition_id=aid,
                         outcome="ORPHANED_RESERVATION" if orphan else "NOT_RESERVED",
                         quota_row_found=row is not None,
                         send_state="MAY_HAVE_BEEN_SENT" if item.state == "SENT" else "NOT_SENT")
            self.coverage.append(CoverageEntry(
                entry_id=gid("cov", acquisition_id=aid, note="RECONCILED"),
                entity_id=f"oddspapi-request:{item.request_hash}", source_contract_id=RAW_CONTRACT_ID,
                status=CoverageStatus.MISSING if orphan else CoverageStatus.NOT_ATTEMPTED, recorded_at=at,
                reason_codes=(reason_code(AdapterFailure.ORPHANED_RESERVATION),),
                note=AdapterFailure.ORPHANED_RESERVATION.value if orphan else "NOT_RESERVED"))
            reconciled.append(aid)
        return tuple(reconciled)
