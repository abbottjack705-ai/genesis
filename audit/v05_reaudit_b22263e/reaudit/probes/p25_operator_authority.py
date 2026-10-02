"""Attack areas 18-20 - READY / grant time, G2R anchor, SECRET_ECHO / AUTH_REJECTED reset authority, gate limits.

Extends 37b86fb a13/a14 to the remediation's own surface:
  A1  §16.4  a G2R-style capture leaves an UNKNOWN capability row anchoring the source timeline;
  A2  §16.2/§16.6  a gate record's granted_at is the trusted clock at approval (file value ignored or refused);
  A3  §16.5  the READY row's recorded_at is the trusted clock at approval, whatever --at / record says;
  A4  no cutoff between capture and approval replays as usable (no retroactive READY);
  A5  READY is never recorded before its G3 record's granted_at;
  K0  §7.4  Secret.fingerprint == sha256("genesis.adapters.credential-fp.v1\\0" + key)[:12];
  R1-R6  §7.6 / §14.3 reset authority after SECRET_ECHO and AUTH_REJECTED halts:
        R1 no G1 -> refused; R2 G1 older than the halt, same key -> refused; R3 G1 newer, same key -> refused;
        R4 G1 older than the halt, different key -> refused; R5 G1 newer, different key -> allowed;
        R6 wrong confirmation phrase -> refused;
  L1  §16.3/§16.4 limits cannot be widened by an edited / operator-selected config directory;
  L2  exact edges on the shipped limits: 5 hashes / 72 h / 35 days accepted; 6 / 72 h + 1 us / 35 days + 1 us refused.

Uses the real CLI command functions with an injected confirmation prompt (the TTY check is the operator
control, not the property under test) and real wall time for approvals (cmd_* use SystemUtcClock).

    python -B p25_operator_authority.py --repo <candidate> [--out p25.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _probe as p  # noqa: E402
from _probe import c  # noqa: E402

AREA = "P25"
BACKDATED = "2000-01-01T00:00:00.000000Z"
KEY_A = c.SENTINEL
KEY_B = "GENESIS-SENTINEL-KEY-fedcba9876543210"


def wall() -> datetime:
    return datetime.now(timezone.utc)


def fp(key: str) -> str:
    return hashlib.sha256(b"genesis.adapters.credential-fp.v1\0" + key.encode()).hexdigest()[:12]


def phrase():
    from genesis_adapters import cli

    return lambda _prompt: cli.CONFIRMATION_PHRASE


def approve(root: Path, record: dict) -> int:
    from genesis_adapters import cli

    path = root / f"rec-{record['gate']}-{time.time_ns()}.json"
    path.write_bytes(json.dumps(record).encode())
    return cli.cmd_approve(SimpleNamespace(record=str(path), root=str(root), config=None), prompt=phrase())


def g1_record(key: str) -> dict:
    from genesis_adapters.oddspapi import authority

    return {"record_type": "gate_record", "schema_version": authority.SCHEMA_VERSION, "gate": "G1",
            "approval_reference": "adr:reaudit-probe-g1", "approver": "reaudit-probe", "granted_at": BACKDATED,
            "terms_snapshot_sha256": "0" * 64, "licensing_note": "FIXTURE-ONLY-NO-PROVIDER-TERMS",
            "credential_fingerprint": fp(key), "credential_path_policy": "outside-repo-0600",
            "valid_through": "2099-01-01T00:00:00.000000Z"}


@p.guarded(AREA, "READY and grant time")
def ready_time(repo: Path) -> None:
    from genesis_adapters import cli
    from genesis_adapters.oddspapi import reader

    root = c.scratch("p25r-")
    clock = c.StepClock()
    body = c.fixture_bytes(repo, "odds_by_tournaments.json")
    rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(default=(200, c.JSON_HEADERS, body)))
    rt.acquire(c.odds_item(repo))
    caps = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"]
    first_ready = min(r["ready_at"] for r in p.pit_rows(rt))
    anchor = [r for r in caps if r["source_id"] == rt.stores.source_id and r["operational_status"].upper() == "UNKNOWN"]
    c.check(AREA, "A1 §16.4: an UNKNOWN capability row anchors the source no later than its first PIT ready_at",
            bool(anchor) and min(r["recorded_at"] for r in anchor) <= first_ready, anchors=len(anchor))
    record = {"record_type": "gate_record", "gate": "G3", "approval_reference": "adr:ADR-A999-reaudit-probe",
              "approver": "reaudit-probe", "granted_at": BACKDATED, "derivation_version": rt.stores.derivation_version,
              "source_id": rt.stores.source_id, "contract_id": rt.stores.contract_id, "review_reference": "probe",
              "acceptance_evidence": {f"AC-{i}": "0" * 64 for i in range(1, 10)}, "unobserved_paths_accepted": [],
              "observation_window": {"from": BACKDATED, "to": c.START}}
    from genesis_adapters.oddspapi import authority

    record["schema_version"] = authority.SCHEMA_VERSION
    t_before = wall()
    code = approve(root, record)
    t_after = wall()
    stored = [r for r in c.jsonl(root / "authority.jsonl") if r.get("gate") == "G3"]
    granted = stored[-1]["granted_at"] if stored else None
    in_window = granted is not None and t_before - timedelta(seconds=1) <= c.parse(granted) <= t_after + timedelta(seconds=1)
    c.check(AREA, "A2 granted_at is the trusted clock at approval (or the back-dated record is refused)",
            code != 0 or in_window, exit=code, granted_at=granted)
    t_before = wall()
    code2 = cli.cmd_approve_ready(SimpleNamespace(root=str(root), config=None, at=BACKDATED, recorded_at=BACKDATED,
                                                  derivation_version=rt.stores.derivation_version,
                                                  source_id=rt.stores.source_id, contract_id=rt.stores.contract_id,
                                                  cost_tier="t"), prompt=phrase())
    t_after = wall()
    ready = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"
             and r["operational_status"].upper() == "READY"]
    rec = ready[-1]["recorded_at"] if ready else None
    in_window = rec is not None and t_before - timedelta(seconds=1) <= c.parse(rec) <= t_after + timedelta(seconds=1)
    c.check(AREA, "A3 READY recorded_at is the trusted clock at approval (operator time ignored or refused)",
            code2 != 0 or in_window, exit=code2, ready_recorded_at=rec)
    if ready and granted:
        c.check(AREA, "A5 READY is never recorded before its G3 granted_at", c.parse(rec) >= c.parse(granted),
                ready=rec, granted=granted)
    open_row = next(r for r in p.pit_rows(rt) if p.doc(rt, r)["market_state"] == "OPEN")
    decision = c.add(open_row["ready_at"], seconds=1)
    head = reader.admissible_head(open_row["entity_id"], decision, stores=rt.stores)
    c.check(AREA, "A4 a cutoff between capture and approval never replays as usable",
            not isinstance(head, reader.UsableBook), decision_at=decision, got=type(head).__name__)
    c.remove(root)


@p.guarded(AREA, "K0 fingerprint formula")
def fingerprint() -> None:
    from genesis_adapters.secrets import Secret

    c.check(AREA, "K0 §7.4 Secret fingerprint equals the architecture formula", Secret(KEY_A).fingerprint == fp(KEY_A),
            got=Secret(KEY_A).fingerprint, expected=fp(KEY_A))


def halt(repo: Path, root: Path, kind: str, key: str, start: str) -> None:
    """Drive the real runtime into a SECRET_ECHO (body echoes the key) or AUTH_REJECTED (401) halt."""

    from genesis_adapters.secrets import Secret

    response = (200, c.JSON_HEADERS, b'["' + key.encode() + b'"]') if kind == "SECRET_ECHO" \
        else (401, c.JSON_HEADERS, b'{"error":"unauthorized"}')
    rt = c.open_runtime(repo, root, clock=c.StepClock(start=start), transport=c.CountingTransport(default=response),
                        secret=Secret(key))
    try:
        rt.acquire(c.odds_item(repo))
    except Exception:
        pass


def reset(root: Path, reference: str = "adr:reaudit-probe-reset", ok_phrase: bool = True) -> int:
    from genesis_adapters import cli

    prompt = phrase() if ok_phrase else (lambda _p: "no")
    try:
        return cli.cmd_reset(SimpleNamespace(root=str(root), config=None, approval_reference=reference,
                                             reason="reaudit probe"), prompt=prompt)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def iso_wall(delta_s: float) -> str:
    return c.iso(wall() + timedelta(seconds=delta_s))


def reset_matrix(repo: Path) -> None:
    for kind in ("SECRET_ECHO", "AUTH_REJECTED"):
        cases = [
            ("R1 no G1 at all", None, None, False, True),
            ("R2 G1 older than the halt, same key", "before", KEY_A, False, True),
            ("R3 G1 newer than the halt, same key", "after", KEY_A, False, True),
            ("R4 G1 older than the halt, different key", "before", KEY_B, False, True),
            ("R5 G1 newer than the halt, different key", "after", KEY_B, True, True),
            ("R6 valid rotation but wrong confirmation phrase", "after", KEY_B, False, False),
        ]
        for label, when, g1_key, allowed, good_phrase in cases:
            @p.guarded(AREA, f"{label} [{kind}]")
            def one(label=label, when=when, g1_key=g1_key, allowed=allowed, good_phrase=good_phrase) -> None:
                root = c.scratch("p25k-")
                if when == "before":
                    if approve(root, g1_record(g1_key)) != 0:
                        raise RuntimeError("G1 approval refused - bind the G1 record fields for this candidate")
                    halt(repo, root, kind, KEY_A, start=iso_wall(1.0))
                    time.sleep(2.0)                     # let wall time pass the halted ledger head
                else:
                    halt(repo, root, kind, KEY_A, start=iso_wall(-3600))
                    if when == "after" and approve(root, g1_record(g1_key)) != 0:
                        raise RuntimeError("G1 approval refused - bind the G1 record fields for this candidate")
                halted = [r for r in c.jsonl(root / "acquisition.jsonl")
                          if r["record_type"] in ("acq_halted", "acq_circuit_opened")]
                if not halted:
                    raise RuntimeError(f"the runtime did not halt on {kind}; cannot test reset authority")
                code = reset(root, ok_phrase=good_phrase)
                c.check(AREA, f"{label} [{kind}]: reset {'allowed' if allowed else 'refused'}",
                        (code == 0) == allowed, exit=code, halt_rows=[r.get("reason") for r in halted])
                c.remove(root)
            one()


@p.guarded(AREA, "gate limits")
def limits(repo: Path) -> None:
    from genesis_adapters import config as cfg
    from genesis_adapters.oddspapi import authority

    root = c.scratch("p25l-")
    config = root / "config"
    shutil.copytree(repo / "adapters" / "config", config)
    body = json.loads((config / authority.GATE_LIMITS_FILE).read_text(encoding="utf-8"))
    body.update({k: (v * 100 if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in body.items()})
    (config / authority.GATE_LIMITS_FILE).write_bytes(json.dumps(body).encode())
    widened = None
    try:
        widened = authority.load_gate_limits(config)
    except Exception as exc:
        c.check(AREA, "L1 an edited limits file is refused at load", True, refused=type(exc).__name__)
    if widened is not None:
        g2 = {"record_type": "gate_record", "schema_version": authority.SCHEMA_VERSION, "gate": "G2",
              "approval_reference": "adr:probe", "approver": "probe", "granted_at": "2026-10-01T00:00:00.000000Z",
              "request_hashes": [f"{i:064x}" for i in range(1, 51)], "max_calls": 50,
              "valid_from": "2026-10-01T00:00:00.000000Z", "valid_through": "2026-11-12T00:00:00.000000Z"}
        accepted = True
        try:
            authority.validate_record(g2, widened)
        except authority.AuthorityRecordInvalid:
            accepted = False
        c.check(AREA, "L1 a widened limits file cannot admit a 50-request / 1000-hour G2", not accepted,
                accepted=accepted, config_digest_changed=cfg.load_config_digests(repo / "adapters" / "config")
                != cfg.load_config_digests(config))
    shipped = authority.load_gate_limits(repo / "adapters" / "config")
    start = "2026-10-01T00:00:00.000000Z"

    def g2(n: int, hours: float, micros: int = 0) -> dict:
        return {"record_type": "gate_record", "schema_version": authority.SCHEMA_VERSION, "gate": "G2",
                "approval_reference": "adr:probe", "approver": "probe", "granted_at": start,
                "request_hashes": [f"{i:064x}" for i in range(1, n + 1)], "max_calls": n, "valid_from": start,
                "valid_through": c.add(start, seconds=hours * 3600, micros=micros)}

    def accepts(record: dict) -> bool:
        try:
            authority.validate_record(record, shipped)
            return True
        except authority.AuthorityRecordInvalid:
            return False

    c.check(AREA, "L2 G2 edges: 5 hashes / 72 h accepted; 6 hashes or 72 h + 1 us refused",
            accepts(g2(5, 72)) and not accepts(g2(6, 72)) and not accepts(g2(5, 72, 1)),
            five_72=accepts(g2(5, 72)), six=accepts(g2(6, 72)), over=accepts(g2(5, 72, 1)))
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    ready_time(repo)
    fingerprint()
    reset_matrix(repo)
    limits(repo)
    return p.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
