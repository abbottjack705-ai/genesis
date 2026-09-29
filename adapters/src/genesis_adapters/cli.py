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
    """Append one gate record (operator only)."""

    from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    reference = str(record.get("approval_reference", ""))
    if not reference.startswith(_REFERENCE_PREFIXES):
        sys.stderr.write("refused: approval_reference must name an out-of-band human artifact\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: approval needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    ledger = AdapterAuthorityLedger(Path(args.root) / "authority.jsonl", limits=load_gate_limits(_config_dir(args.config)))
    ledger.append(record)
    sys.stdout.write("approved\n")
    return EXIT_OK


def cmd_approve_ready(args, *, prompt=None) -> int:
    """Mark a market-book source READY after a G3 record (design 16.5; G-03). Operator only."""

    from genesis.feature_manifest import SourceInputBindingStore
    from genesis.pit import OperationalStatus, SourceCapability, SourceCapabilityRegistry
    from genesis.time import iso_utc

    from genesis_adapters.errors import GateMissing
    from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits

    root = Path(args.root)
    ledger = AdapterAuthorityLedger(root / "authority.jsonl", limits=load_gate_limits(_config_dir(args.config)))
    try:
        record = ledger.require_gate("G3", at=args.at, derivation_version=args.derivation_version,
                                     source_id=args.source_id, contract_id=args.contract_id)
    except GateMissing:
        sys.stderr.write("refused: no G3 record for this source\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: approval needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    capabilities.register(SourceCapability(
        source_id=args.source_id, provider="oddspapi", access_method="rest_pregame_v4", cost_tier=args.cost_tier,
        entitlement_class="read_only_personal_research", historical_availability_class="none",
        point_in_time_reliability="prospective_verified", revision_behaviour="append_only_supersede",
        coverage="soccer.eng.premier-league,soccer.esp.laliga", rate_quota_limits="frozen quota policy",
        schema_version="v1", operational_status=OperationalStatus.READY, recorded_at=iso_utc(args.at),
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
        source = next((line.split(":", 1)[1].strip() for line in status.stdout.splitlines()
                       if line.strip().lower().startswith("source:")), "")
        synced = status.returncode == 0 and bool(source) and source.lower() not in (
            "local cmos clock", "free-running system clock")
        return {"synchronized": synced, "method": "w32tm", "source": source}
    status = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True,
                            text=True, check=False)
    return {"synchronized": status.returncode == 0 and status.stdout.strip() == "yes", "method": "timedatectl",
            "source": status.stdout.strip()}


def _loopback(value: str | None):
    """``HOST:PORT`` for loopback tests only; any other address is refused (the key never goes elsewhere)."""

    import ipaddress

    if value is None:
        return None
    host, _, port = value.rpartition(":")
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("--connect accepts loopback addresses only")
    return host, int(port)


def cmd_run(args) -> int:
    """A gated live run (G2 verification: raw capture only; G2R: full pipeline). Refuses without the gates."""

    from genesis_adapters.clock import SystemUtcClock
    from genesis_adapters.config import load_adapter_config
    from genesis_adapters.credential import CredentialSource
    from genesis_adapters.errors import CredentialProblem
    from genesis_adapters.oddspapi import endpoints, normalize, pipeline
    from genesis_adapters.oddspapi.acquisition import AcquisitionLedger, PlanItem
    from genesis_adapters.oddspapi.authority import (
        MODE_VERIFICATION, AdapterAuthorityLedger, LiveGate, load_gate_limits, sent_counter,
    )
    from genesis_adapters.oddspapi.quota_gate import open_operational_ledger
    from genesis_adapters.oddspapi.transport_http import HttpsTransport, tls_context

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
    address = _loopback(args.connect)
    if args.ca_file and address is None:
        sys.stderr.write("refused: a test CA is only accepted together with a loopback address\n")
        return EXIT_REFUSED
    specs = config.endpoints
    transport = HttpsTransport(secret, credential_param=specs["ODDS"].credential_param, policy=config.policy,
                               ssl_context=tls_context(args.ca_file), connect_address=address)
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
    for entry in json.loads(Path(args.plan).read_text(encoding="utf-8")):
        item = PlanItem(window_id=entry["window"], purpose=entry.get("purpose", "G2_VERIFICATION"),
                        request=endpoints.build_request(specs[entry["role"]], **entry["params"]),
                        attempt=entry.get("attempt", 1))
        if args.mode == MODE_VERIFICATION:                      # G2: raw only, nothing normalized
            outcome = rt.runner.acquire(item)
        else:
            outcome = rt.acquire(item).outcome
        sys.stdout.write(f"{item.window_id}: {outcome.outcome} {outcome.failure or ''}\n")
    return EXIT_OK


def cmd_reset(args, *, prompt=None) -> int:
    """Clear a durable halt or open circuit (operator only, after the cause was fixed - e.g. a rotated key and a
    new G1 record after SECRET_ECHO or AUTH_REJECTED). Writes one ``acq_operator_reset`` row."""

    from genesis_adapters.clock import SystemUtcClock
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.acquisition import AcquisitionLedger

    if not str(args.approval_reference).startswith(_REFERENCE_PREFIXES):
        sys.stderr.write("refused: approval_reference must name an out-of-band human artifact\n")
        return EXIT_REFUSED
    if not _interactive_confirmation(prompt):
        sys.stderr.write("refused: a reset needs an interactive terminal and the typed confirmation phrase\n")
        return EXIT_REFUSED
    policy = load_policy(_config_dir(args.config) / "oddspapi_slice1_policy.json")
    ledger = AcquisitionLedger(Path(args.root) / "acquisition.jsonl")
    ledger.append("acq_operator_reset", recorded_at=SystemUtcClock(drift_max_ms=policy.wall_monotonic_drift_max_ms,
                                                                    floor=ledger.last_recorded_at()).now(),
                  approval_reference=args.approval_reference, reason=args.reason)
    sys.stdout.write("reset\n")
    return EXIT_OK


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
    run.add_argument("--connect")
    run.add_argument("--ca-file")
    ready = commands.add_parser("approve-ready")
    for name in ("--root", "--at", "--derivation-version", "--source-id", "--contract-id", "--cost-tier"):
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
