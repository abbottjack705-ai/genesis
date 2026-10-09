"""Operator command line (design 7.7, 16.6): ``run``, ``verify``, ``plan``, ``report``, ``approve``, ``approve-ready``.

Startup refuses unless the interpreter runs with ``-B`` and a fresh ``PYTHONPYCACHEPREFIX`` and the module-
provenance guard passes (FRZ-09, F-41). The excepthooks installed here are sanitizing and flow-neutral: they
print only an exception class name and never change control flow or exit status; there is no
``BaseException`` handler anywhere in this module (FRZ-11), so ``KeyboardInterrupt`` and ``SystemExit``
reach the interpreter unchanged.

``approve``, ``approve-ready`` and ``reset`` are the ONLY writers of approval records, READY capability rows and halt resets. All
refuse without an interactive terminal, a typed confirmation phrase and an ``approval_reference`` that names
an out-of-band human artifact. Nothing in the adapter runtime can call them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence

EXIT_OK, EXIT_REFUSED, EXIT_FAILED = 0, 2, 3
CONFIRMATION_PHRASE = "I AM A HUMAN OPERATOR AND I APPROVE THIS GATE"
_REFERENCE_PREFIXES = ("adr:", "signed-tag:", "pr-approval:", "https://")


def _print_class(name: str) -> None:
    sys.stderr.write(f"error: {name}\n")


def _sanitizing_excepthook(kind, value, traceback) -> None:        # prints the class name, nothing else
    _print_class(getattr(kind, "__name__", "Exception"))


def _sanitizing_thread_hook(args) -> None:
    _print_class(getattr(args.exc_type, "__name__", "Exception"))


def _sanitizing_unraisable_hook(unraisable) -> None:
    _print_class(getattr(unraisable.exc_type, "__name__", "Exception"))


def install_hooks() -> None:
    sys.excepthook = _sanitizing_excepthook
    threading.excepthook = _sanitizing_thread_hook
    sys.unraisablehook = _sanitizing_unraisable_hook


def _repo() -> Path:
    return Path(__file__).resolve().parents[3]


def _config_dir(value: str | None) -> Path:
    return Path(value) if value else _repo() / "adapters" / "config"


def startup_guard(config_dir: Path) -> dict:
    """FRZ-09 at runner startup: -B, fresh pycache prefix, pinned frozen modules (raises on failure)."""

    import importlib

    from genesis_adapters import provenance_guard
    from genesis_adapters.oddspapi import verify

    for name in ("time", "repro", "registry", "provenance", "evidence", "pit", "feature_manifest", "quota",
                 "coverage", "reasons"):
        importlib.import_module("genesis." + name)
    return provenance_guard.verify_loaded_genesis_modules(
        _repo(), manifest_path=config_dir / "frozen_genesis_modules.json",
        expected_manifest_sha256=verify.FROZEN_MANIFEST_SHA256)


def _interactive_confirmation(prompt: Callable[[str], str] | None) -> bool:
    if prompt is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        prompt = input
    return prompt(f"Type exactly: {CONFIRMATION_PHRASE}\n> ").strip() == CONFIRMATION_PHRASE


# --------------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------------
def cmd_plan(args) -> int:
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi import scheduler

    policy = load_policy(_config_dir(args.config) / "oddspapi_slice1_policy.json")
    fixtures = json.loads(Path(args.fixtures).read_text(encoding="utf-8"))
    kickoffs = [scheduler.Kickoff(item["fixture_id"], item["start"]) for item in fixtures]
    plan = scheduler.plan_month(kickoffs, policy=policy, month=args.month,
                                used=scheduler.QuotaUsage(as_of=args.as_of, monthly_used=args.used))
    sys.stdout.write(json.dumps({"month": plan.month, "digest": plan.digest,
                                 "windows": [w.__dict__ for w in plan.windows],
                                 "changes": [c.__dict__ for c in plan.changes]}, sort_keys=True, indent=1) + "\n")
    return EXIT_OK


def usage_report(root: Path) -> str:
    """A plain-text usage report (BILL-04). Ledger figures are labelled as the Genesis debit (an internal budget
    unit, never evidence of what the provider counted); header figures are labelled provider-reported usage."""

    from genesis.registry import AppendOnlyJsonl

    debited = 0
    reported = []
    quota = Path(root) / "quota" / "ledger.jsonl"
    if quota.exists():
        for row in AppendOnlyJsonl(quota).records():
            if row.get("record_type") == "quota_billable_call":
                debited += int(row.get("billable_units", 0))
    acquisition = Path(root) / "acquisition.jsonl"
    if acquisition.exists():
        for row in AppendOnlyJsonl(acquisition).records():
            usage = row.get("provider_reported_usage") if row.get("record_type") == "acq_completed" else None
            if usage:
                reported.append(usage.get("reported"))
    lines = [f"Genesis debit (internal budget units): {debited}",
             f"provider-reported usage (last header value): {reported[-1] if reported else 'not reported'}"]
    return "\n".join(lines) + "\n"


def cmd_report(args) -> int:
    sys.stdout.write(usage_report(Path(args.root)))
    return EXIT_OK


def cmd_verify(args) -> int:
    from genesis.evidence import EvidenceStore
    from genesis.provenance import SourceContractRegistry

    from genesis_adapters.config import load_adapter_config
    from genesis_adapters.oddspapi import derivation, normalize, pipeline
    from genesis_adapters.oddspapi.maps import maps_from_config

    root = Path(args.root)
    config = load_adapter_config(_config_dir(args.config), allow_fixture_only=True, code_version=normalize.CODE_VERSION)
    stores = pipeline.build_stores(root, derivation_version=config.derivation_version, policy=config.policy,
                                   licensing_note=args.licensing_note)
    count = derivation.verify_all(stores, config, maps_from_config(config))
    manifest_rows = EvidenceStore(root / "evidence", contracts=SourceContractRegistry(root / "contracts.jsonl")
                                  ).verify_manifest()
    sys.stdout.write(json.dumps({"derivations_verified": count, "evidence_observations": manifest_rows}) + "\n")
    return EXIT_OK


def cmd_approve(args, *, prompt=None) -> int:
    """Append one gate record (operator only). Its ``granted_at`` is the trusted clock's reading at approval (design
    16.2), never a time chosen in the record file: a file naming a time further than ``clock_skew_max_seconds`` from
    that reading is refused (hostile audit P:HA-013), so no gate can be made retroactively valid."""

    from datetime import timedelta

    from genesis.time import TimestampError, parse_utc

    from genesis_adapters.clock import ClockFault, SystemUtcClock
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    reference = str(record.get("approval_reference", ""))
    if not reference.startswith(_REFERENCE_PREFIXES):
        sys.stderr.write("refused: approval_reference must name an out-of-band human artifact\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: approval needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    config_dir = _config_dir(args.config)
    policy = load_policy(config_dir / "oddspapi_slice1_policy.json")
    ledger = AdapterAuthorityLedger(Path(args.root) / "authority.jsonl", limits=load_gate_limits(config_dir))
    granted = [row["granted_at"] for row in ledger.records()]
    try:
        now = SystemUtcClock(drift_max_ms=policy.wall_monotonic_drift_max_ms,
                             floor=max(granted, key=parse_utc) if granted else None).now()
    except ClockFault:
        sys.stderr.write("refused: the trusted clock is behind the authority ledger\n")
        return EXIT_REFUSED
    stated = record.get("granted_at")
    if stated is not None:
        try:
            off = abs(parse_utc(stated) - parse_utc(now))
        except (TimestampError, TypeError, ValueError):
            off = None
        if off is None or off > timedelta(seconds=policy.clock_skew_max_seconds):
            sys.stderr.write("refused: granted_at is stamped by the trusted clock at approval, not chosen in the "
                             "record\n")
            return EXIT_REFUSED
    ledger.append({**record, "granted_at": now})
    sys.stdout.write("approved\n")
    return EXIT_OK


def cmd_approve_ready(args, *, prompt=None) -> int:
    """Mark a market-book source READY after a G3 record (design 16.5; G-03). Operator only.

    The READY row is recorded at the trusted clock's reading (design 16.5, ``recorded_at=now``), never at a time the
    operator chooses, and never earlier than the source's latest capability row (the clock's floor), so READY can
    never be made retroactively usable at an earlier cutoff (hostile audit P:HA-013)."""

    from genesis.feature_manifest import SourceInputBindingStore
    from genesis.pit import OperationalStatus, SourceCapability, SourceCapabilityRegistry
    from genesis.time import iso_utc

    from genesis_adapters.clock import ClockFault, SystemUtcClock
    from genesis_adapters.config import load_policy
    from genesis_adapters.errors import GateMissing
    from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits

    root = Path(args.root)
    config_dir = _config_dir(args.config)
    policy = load_policy(config_dir / "oddspapi_slice1_policy.json")
    ledger = AdapterAuthorityLedger(root / "authority.jsonl", limits=load_gate_limits(config_dir))
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    history = capabilities.history(args.source_id)
    try:
        now = SystemUtcClock(drift_max_ms=policy.wall_monotonic_drift_max_ms,
                             floor=iso_utc(history[-1].recorded_at) if history else None).now()
    except ClockFault:
        sys.stderr.write("refused: the trusted clock is behind the source's latest capability row\n")
        return EXIT_REFUSED
    try:
        record = ledger.require_gate("G3", at=now, derivation_version=args.derivation_version,
                                     source_id=args.source_id, contract_id=args.contract_id)
    except GateMissing:
        sys.stderr.write("refused: no G3 record for this source\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: approval needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    capabilities.register(SourceCapability(
        source_id=args.source_id, provider="oddspapi", access_method="rest_pregame_v4", cost_tier=args.cost_tier,
        entitlement_class="read_only_personal_research", historical_availability_class="none",
        point_in_time_reliability="prospective_verified", revision_behaviour="append_only_supersede",
        coverage="soccer.eng.premier-league,soccer.esp.laliga", rate_quota_limits="frozen quota policy",
        schema_version="v1", operational_status=OperationalStatus.READY, recorded_at=now,
        version=args.derivation_version + "-ready-1"))
    SourceInputBindingStore(root / "bindings.jsonl").register(
        source_id=args.source_id, source_contract_id=args.contract_id, provider="oddspapi",
        approval_reference=record["approval_reference"])
    sys.stdout.write("ready\n")
    return EXIT_OK


def time_sync_attestation() -> dict:
    """The OS time-sync attestation a live run records at startup (design 6.1). No attestation, no live send."""

    import subprocess

    if sys.platform == "win32":
        status = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, text=True, check=False)
        return windows_time_sync_attestation(status.returncode, status.stdout)
    status = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True,
                            text=True, check=False)
    return {"synchronized": status.returncode == 0 and status.stdout.strip() == "yes", "method": "timedatectl",
            "source": status.stdout.strip()}


# Forbidden Source names as keys: letters and digits only, lower case, so spacing, case and punctuation variants
# compare equal. Only printable ASCII reaches this comparison (_W32TM_PRINTABLE), so no control or Unicode character
# can hide one.
_W32TM_UNSYNCHRONIZED_SOURCES = ("localcmosclock", "freerunningsystemclock")
_W32TM_PRINTABLE = re.compile(r"[\x20-\x7e]+")
# A note that contradicts a stratum above zero: the clock is not, or does not claim to be, synchronized.
_W32TM_UNSYNCHRONIZED_NOTE = re.compile(r"not synchronized|unsynchronized|unspecified", re.IGNORECASE)
# The English w32tm numeric fields, each with its NTP wire-format width: Leap Indicator is a 2-bit field (0-3) and
# Stratum an 8-bit one (0-255). Each is an unsigned decimal with no sign and no leading zero, then optionally one
# balanced parenthetical note with one level of nesting, as in ``(secondary reference - syncd by (S)NTP)``. Anything
# else after the number, an unbalanced or empty note, or a non-ASCII digit makes the field malformed.
_W32TM_NOTE = r"(?: ?\((?P<note>(?:[\x20-\x27\x2a-\x7e]|\((?:[\x20-\x27\x2a-\x7e])*\))+)\))?"
_W32TM_LEAP = re.compile(r"(?P<number>[0-3])" + _W32TM_NOTE)
_W32TM_STRATUM = re.compile(r"(?P<number>0|[1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])" + _W32TM_NOTE)
# Required labels, keyed by a stem that marks a line as one of them. A line whose label contains a stem must match its
# label exactly (case aside); a near miss such as ``Leap\tIndicator`` is malformed and fails closed rather than ignored.
_W32TM_LABELS = {"leap": "leap indicator", "stratum": "stratum", "source": "source",
                 "successful sync": "last successful sync time"}


def windows_time_sync_attestation(returncode: int, stdout: str) -> dict:
    """Design 6.1 Windows rule, ratified for WC7-003. Healthy only when ``w32tm /query /status`` exits 0, Leap
    Indicator is exactly 0 with no note or the note ``no warning``, Stratum is greater than 0 with no note that says it
    is unsynchronized, and Source is printable ASCII and neither Local CMOS Clock nor Free-running System Clock in any
    case or spacing. A required field that is missing, repeated, malformed or contradictory fails closed. The parsed
    fields are kept as evidence for the decision; Last Successful Sync Time is recorded but not gated, because no
    maximum age is approved."""

    seen: dict[str, list[str | None]] = {stem: [] for stem in _W32TM_LABELS}
    for line in stdout.split("\n"):
        parts = re.split(r"[:=]", line.rstrip("\r"), maxsplit=1)
        label = parts[0].strip(" ").casefold()
        value = parts[1].strip(" ") if len(parts) == 2 else None
        for stem, exact in _W32TM_LABELS.items():
            if stem in label:
                seen[stem].append(value if label == exact else None)

    def single(stem: str) -> str | None:
        values = seen[stem]
        return values[0] if len(values) == 1 else None      # missing, repeated or malformed: ambiguous, so unusable

    leap = _w32tm_numeric(_W32TM_LEAP, single("leap"))
    stratum = _w32tm_numeric(_W32TM_STRATUM, single("stratum"))
    source = single("source")
    leap_ok = leap is not None and leap[0] == 0 and (leap[1] is None or leap[1].casefold() == "no warning")
    stratum_ok = (stratum is not None and stratum[0] > 0
                  and not (stratum[1] and _W32TM_UNSYNCHRONIZED_NOTE.search(stratum[1])))
    source_ok = (bool(source) and _W32TM_PRINTABLE.fullmatch(source) is not None
                 and re.sub(r"[^a-z0-9]", "", source.casefold()) not in _W32TM_UNSYNCHRONIZED_SOURCES)
    healthy = returncode == 0 and leap_ok and stratum_ok and source_ok
    return {"synchronized": healthy, "method": "w32tm", "source": source or "",
            "leap_indicator": leap[0] if leap else None, "stratum": stratum[0] if stratum else None,
            "last_successful_sync": single("successful sync")}


def _w32tm_numeric(grammar: re.Pattern, text: str | None) -> tuple[int, str | None] | None:
    """A required numeric field as (number, note), or None when it is malformed or outside the field's width."""

    match = grammar.fullmatch(text or "")
    return (int(match["number"]), match["note"]) if match else None


def cmd_run(args) -> int:
    """A gated live run (G2 verification: raw capture only; G2R: full pipeline). Refuses without the gates, and while
    another adapter phase holds the runtime root's run lock (design 6.3), which it holds for the whole run."""

    from genesis_adapters.oddspapi import quiescence

    try:
        with quiescence.run_lock(Path(args.root)):
            return _run(args)
    except quiescence.QuiescenceBusy:
        sys.stderr.write("refused: another adapter phase holds the run lock\n")
        return EXIT_REFUSED


def _run(args) -> int:
    from genesis_adapters.clock import SystemUtcClock
    from genesis_adapters.config import load_adapter_config
    from genesis_adapters.credential import CredentialSource
    from genesis_adapters.errors import CredentialProblem, PlanRefused
    from genesis_adapters.oddspapi import capability, emit, endpoints, normalize, pipeline
    from genesis_adapters.oddspapi.acquisition import AcquisitionLedger, PlanItem
    from genesis_adapters.oddspapi.authority import (
        MODE_VERIFICATION, AdapterAuthorityLedger, LiveGate, load_gate_limits, sent_counter,
    )
    from genesis_adapters.oddspapi.quota_gate import open_operational_ledger
    from genesis_adapters.oddspapi.transport_http import HttpsTransport

    config_dir, root = _config_dir(args.config), Path(args.root)
    attestation = time_sync_attestation()
    config = load_adapter_config(config_dir, allow_fixture_only=args.mode == MODE_VERIFICATION,
                                 code_version=normalize.CODE_VERSION)
    authority = AdapterAuthorityLedger(root / "authority.jsonl", limits=load_gate_limits(config_dir))
    grants = authority.records("G1")
    if not grants:
        sys.stderr.write("refused: no G1 record\n")
        return EXIT_REFUSED
    try:
        secret = CredentialSource(repo=_repo(), runtime_root=root,
                                  expected_fingerprint=grants[-1]["credential_fingerprint"]).load()
    except CredentialProblem as problem:
        sys.stderr.write(f"refused: {problem.code}\n")
        return EXIT_REFUSED
    specs = config.endpoints
    # always the system trust store and the pinned host: the operator path has no CA or address option (P:HA-006)
    transport = HttpsTransport(secret, credential_param=specs["ODDS"].credential_param, policy=config.policy)
    ledger, cache = open_operational_ledger(root)
    clock = SystemUtcClock(drift_max_ms=config.policy.wall_monotonic_drift_max_ms)
    gate = LiveGate(authority, mode=args.mode, credential_fingerprint=secret.fingerprint,
                    derivation_version=config.derivation_version, policy_digest=config.policy.digest,
                    attestation=attestation, sent_count=sent_counter(AcquisitionLedger(root / "acquisition.jsonl")))
    rt = pipeline.open_runtime(root, config_dir=config_dir, clock=clock, transport=transport, quota_ledger=ledger,
                               cache=cache, secret=secret, live=True, authority=gate, require_date=True,
                               licensing_note=grants[-1]["licensing_note"],
                               allow_fixture_only=args.mode == MODE_VERIFICATION,
                               provenance_check=lambda: startup_guard(config_dir))
    # every start first finishes what a crash left (design 13.2, 14.4; hostile audit HA-04, HA-05)
    if args.mode == MODE_VERIFICATION:                          # G2: raw only, nothing normalized
        rt.runner.reconcile_after_restart()
        emit.complete_pending_invalidations(rt.stores, clock=clock)
    else:                                                       # G2R: the source's timeline starts UNKNOWN (16.4)
        capability.anchor_unknown(rt.stores.capabilities, rt.stores.source_id, at=clock.now(), reason="G2R_START")
        rt.resume()
    entries = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    clock_check = bool(getattr(args, "clock_check", False))
    if clock_check and len(entries) != 1:
        sys.stderr.write("refused: a clock-check run sends exactly one probe (design 14.6 rule 5)\n")
        return EXIT_REFUSED
    for entry in entries:
        item = PlanItem(window_id=entry["window"], purpose=entry.get("purpose", "G2_VERIFICATION"),
                        request=endpoints.build_request(specs[entry["role"]], **entry["params"]),
                        attempt=entry.get("attempt", 1), not_after=entry.get("not_after"))
        try:
            if args.mode == MODE_VERIFICATION:                  # G2: raw only, nothing normalized
                outcome = rt.runner.acquire(item, clock_check=clock_check)
            else:
                outcome = rt.acquire(item, clock_check=clock_check).outcome
        except PlanRefused as refused:                          # design 14.3: nothing was recorded, debited or sent
            sys.stderr.write(f"refused: {item.window_id}: retry not permitted ({refused.reason})\n")
            return EXIT_REFUSED
        sys.stdout.write(f"{item.window_id}: {outcome.outcome} {outcome.failure or ''}\n")
    return EXIT_OK


def cmd_reset(args, *, prompt=None) -> int:
    """Clear a durable halt or open circuit (operator only, after the cause was fixed). Writes one
    ``acq_operator_reset`` row.

    A security halt is cleared only by what the design prescribes (hostile audit P:HA-014): a SECRET_ECHO halt only
    after a G1 record granted after it for a rotated key - a fingerprint other than the one in force at the halt
    (design 7.6: "a human must rotate the key (re-G1)") - and an AUTH_REJECTED circuit only after a G1 record granted
    after it (design 14.3: "a human must re-approve (G1 re-check)"). A CLOCK_SKEW suspension is never cleared by a
    reset (design 14.6 rule 5: only the next UTC day and a clean Date check)."""

    from genesis_adapters.clock import SystemUtcClock
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
    from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits

    if not str(args.approval_reference).startswith(_REFERENCE_PREFIXES):
        sys.stderr.write("refused: approval_reference must name an out-of-band human artifact\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: a reset needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    config_dir = _config_dir(args.config)
    policy = load_policy(config_dir / "oddspapi_slice1_policy.json")
    ledger = AcquisitionLedger(Path(args.root) / "acquisition.jsonl")
    grants = AdapterAuthorityLedger(Path(args.root) / "authority.jsonl", limits=load_gate_limits(config_dir))
    refusal = _security_halt_unresolved(ledger.rows(), grants.records("G1"))
    if refusal is not None:
        sys.stderr.write(f"refused: {refusal}\n")
        return EXIT_REFUSED
    ledger.append("acq_operator_reset", recorded_at=SystemUtcClock(drift_max_ms=policy.wall_monotonic_drift_max_ms,
                                                                    floor=ledger.last_recorded_at()).now(),
                  approval_reference=args.approval_reference, reason=args.reason)
    sys.stdout.write("reset\n")
    return EXIT_OK


def _security_halt_unresolved(rows, grants) -> str | None:
    """Why a reset may not clear the security halts in the acquisition ledger, or None if it may. Every such halt
    is checked, not only those since the last reset: one resolved stays resolved, as gate records are only added."""

    from genesis.time import parse_utc

    from genesis_adapters.errors import AdapterFailure

    for row in rows:
        secret = row["record_type"] == "acq_halted" and row["reason"] == AdapterFailure.SECRET_ECHO.value
        rejected = row["record_type"] == "acq_circuit_opened" and row["reason"] == AdapterFailure.AUTH_REJECTED.value
        if not (secret or rejected):
            continue
        at = parse_utc(row["recorded_at"])
        after = [grant for grant in grants if parse_utc(grant["granted_at"]) > at]
        if secret:
            # the echoed key was authorized by some G1 granted at or before the halt (a gate is valid only from its
            # granted_at); no send records which, so a rotated key is one that no such G1 ever named (fail closed)
            approved = {grant["credential_fingerprint"] for grant in grants if parse_utc(grant["granted_at"]) <= at}
            if not any(grant["credential_fingerprint"] not in approved for grant in after):
                return "a SECRET_ECHO halt is cleared only after a new G1 record for a rotated key (design 7.6)"
        elif not after:
            return "an AUTH_REJECTED circuit is cleared only after a new G1 record (design 14.3)"
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="genesis-adapters-oddspapi")
    parser.add_argument("--config")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--fixtures", required=True)
    plan.add_argument("--month", required=True)
    plan.add_argument("--as-of", required=True)
    plan.add_argument("--used", type=int, required=True)
    report = commands.add_parser("report")
    report.add_argument("--root", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", required=True)
    verify.add_argument("--licensing-note", default="FIXTURE-ONLY-NO-PROVIDER-TERMS")
    approve = commands.add_parser("approve")
    approve.add_argument("--root", required=True)
    approve.add_argument("--record", required=True)
    reset = commands.add_parser("reset")
    reset.add_argument("--root", required=True)
    reset.add_argument("--approval-reference", required=True)
    reset.add_argument("--reason", required=True)
    run = commands.add_parser("run")
    run.add_argument("--root", required=True)
    run.add_argument("--plan", required=True)
    run.add_argument("--mode", choices=("G2", "G2R"), required=True)
    run.add_argument("--clock-check", action="store_true")     # the one probe that may re-arm sends (14.6 rule 5)
    ready = commands.add_parser("approve-ready")
    for name in ("--root", "--derivation-version", "--source-id", "--contract-id", "--cost-tier"):
        ready.add_argument(name, required=True)
    return parser


COMMANDS = {"plan": cmd_plan, "report": cmd_report, "verify": cmd_verify, "approve": cmd_approve,
            "approve-ready": cmd_approve_ready, "run": cmd_run, "reset": cmd_reset}


def main(argv: Sequence[str] | None = None) -> int:
    install_hooks()
    args = _parser().parse_args(argv)
    try:
        startup_guard(_config_dir(args.config))
    except Exception as exc:                                  # any guard failure: refuse to start (F-41)
        _print_class(f"MODULE_PROVENANCE ({type(exc).__name__})")
        return EXIT_REFUSED
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
