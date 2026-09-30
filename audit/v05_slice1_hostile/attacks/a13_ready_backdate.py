"""New finding HA-013: the operator READY row and gate records carry operator-supplied times.

c8dfafd 16.5 says the operator CLI appends ``SourceCapability(..., operational_status=READY, recorded_at=now,
...)``; 16.2 says a G1 record's ``granted_at`` comes from the trusted clock; 16.4 says that during G2R the
market-book source is registered ``UNKNOWN``. The candidate's ``approve-ready`` stamps the READY row with the
operator's ``--at`` argument, ``approve`` stores ``granted_at`` exactly as written in the record file, and no
runtime code ever registers the G2R ``UNKNOWN`` row - so nothing anchors the capability timeline, and a READY
row can be dated before the approval (even before the captures it makes consumable).

The attack drives the real CLI command functions with an injected confirmation prompt (the interactive TTY
check is the operator control; it is not what is under test here).

    python -B attacks/a13_ready_backdate.py --repo <candidate>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

BACKDATED = "2000-01-01T00:00:00.000000Z"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    from genesis_adapters import cli
    from genesis_adapters.oddspapi import reader

    root = c.scratch("ready-")
    clock = c.StepClock()
    body = c.fixture_bytes(repo, "odds_by_tournaments.json")
    rt = c.open_runtime(repo, root, clock=clock, transport=c.CountingTransport(default=(200, c.JSON_HEADERS, body)))
    rt.acquire(c.odds_item(repo))
    caps = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"]
    c.check("A13", "16.4: a G2R-style capture leaves an UNKNOWN capability row for its market-book source",
            any(r["source_id"] == rt.stores.source_id and r["operational_status"].upper() == "UNKNOWN" for r in caps),
            capability_rows=len(caps))

    record = {"record_type": "gate_record", "schema_version": "adapter-authority-v1", "gate": "G3",
              "approval_reference": "adr:ADR-A999-audit-probe", "approver": "auditor-probe",
              "granted_at": BACKDATED, "derivation_version": rt.stores.derivation_version,
              "source_id": rt.stores.source_id, "contract_id": rt.stores.contract_id,
              "review_reference": "audit-probe", "acceptance_evidence": {f"AC-{i}": "0" * 64 for i in range(1, 10)},
              "unobserved_paths_accepted": [], "observation_window": {"from": BACKDATED, "to": c.START}}
    record_path = root / "g3.json"
    record_path.write_bytes(json.dumps(record).encode())
    phrase = lambda _prompt: cli.CONFIRMATION_PHRASE                       # noqa: E731
    code1 = cli.cmd_approve(SimpleNamespace(record=str(record_path), root=str(root), config=None), prompt=phrase)
    stored = [r for r in c.jsonl(root / "authority.jsonl") if r.get("gate") == "G3"]
    c.check("A13", "16.2/16.6: a gate record's granted_at is stamped by the trusted clock, not taken from the file",
            code1 != 0 or (stored and stored[-1]["granted_at"] != BACKDATED),
            exit=code1, stored_granted_at=stored[-1]["granted_at"] if stored else None)
    code2 = cli.cmd_approve_ready(SimpleNamespace(root=str(root), config=None, at=BACKDATED,
                                                  derivation_version=rt.stores.derivation_version,
                                                  source_id=rt.stores.source_id, contract_id=rt.stores.contract_id,
                                                  cost_tier="t"), prompt=phrase)
    caps = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"
            and r["operational_status"].upper() == "READY"]
    c.check("A13", "16.5: the READY row is recorded at the trusted-clock 'now' of the approval, never at an "
                   "operator-chosen earlier time", code2 != 0 or (caps and caps[-1]["recorded_at"] != BACKDATED),
            exit=code2, ready_recorded_at=caps[-1]["recorded_at"] if caps else None)
    pit = [r for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record"]
    open_row = next(r for r in pit if json.loads(rt.stores.evidence.get_bytes(r["payload_hash"]))["market_state"] == "OPEN")
    clock.jump(1800)
    approval_moment = clock.now()                     # when the operator actually ran approve-ready (scenario clock)
    decision = c.add(open_row["ready_at"], seconds=1)  # a cutoff between the capture and that moment
    head = reader.admissible_head(open_row["entity_id"], decision, stores=rt.stores)
    c.check("A13", "consequence: a cutoff taken between capture and the approval moment must not replay as usable",
            not isinstance(head, reader.UsableBook), decision_at=decision, approval_moment=approval_moment,
            reader=type(head).__name__, note="usable here means the capability timeline was rewritten after the fact")
    # HA-014: `reset` clears a SECRET_ECHO halt without any newer G1 / different credential fingerprint
    from genesis_adapters.oddspapi.acquisition import AcquisitionLedger

    # (own root with past timestamps: `reset` stamps with the real SystemUtcClock, floored at the ledger head)
    halt_root = c.scratch("reset-")
    ledger = AcquisitionLedger(halt_root / "acquisition.jsonl")
    ledger.append("acq_halted", recorded_at="2026-09-01T00:00:00.000000Z", reason="SECRET_ECHO")
    before = ledger.circuit_open("ODDS", "2026-09-01T00:00:01.000000Z")
    code3 = cli.cmd_reset(SimpleNamespace(root=str(halt_root), config=None, approval_reference="adr:audit-probe",
                                          reason="probe"), prompt=phrase)
    after = ledger.circuit_open("ODDS", c.add(ledger.last_recorded_at(), seconds=1))
    g1 = [r for r in c.jsonl(halt_root / "authority.jsonl") if r.get("gate") == "G1"]
    c.remove(halt_root)
    c.check("A13", "7.6/F-11: after SECRET_ECHO, sends stay halted until a re-G1 with a new credential exists",
            not (code3 == 0 and before == "SECRET_ECHO" and after is None and not g1),
            halted_before=before, reset_exit=code3, blocking_after=after, g1_records=len(g1))
    c.remove(root)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
