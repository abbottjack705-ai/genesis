"""Re-audit probe helpers (re-auditor written). Builds on the prior audit's ``_common_37b86fb.py`` (copied
verbatim from 37b86fb attacks/_common.py, sha256 c37a1bf2...246b), which drives the candidate through its
PUBLIC production API only.

Fail-closed reporting: a probe whose setup cannot bind to the candidate's API records CANNOT_RUN (never a
PASS). A FAIL is a probe verdict, not yet a finding: confirm it by reading the cited code first.

The API used is the one the cfcff3d attacks used (pipeline.open_runtime, PlanItem, transport.send(request,
*, clock, deadline_at), emit.emit_invalidation(..., checkpoint=...), reader.admissible_head, cli.cmd_*).
If b22263e renamed any of these, adapt the binding here, not the assertions.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common_37b86fb as c  # noqa: E402

RESULTS = c.RESULTS
CAP_TIME = "2026-09-30T00:00:00.000000Z"


def cannot_run(area: str, name: str, exc: BaseException) -> None:
    RESULTS.append({"area": area, "check": name, "pass": False, "status": "CANNOT_RUN",
                    "error": f"{type(exc).__name__}: {exc}",
                    "where": traceback.format_exception(exc)[-2].strip()[:300]})
    print(f"[CANNOT_RUN] {area} {name}: {type(exc).__name__}: {exc}")


def guarded(area: str, name: str):
    """Decorator: an exception escaping a probe body is CANNOT_RUN, never PASS."""

    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except c.Crash:
                raise
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                cannot_run(area, name, exc)
                return None
        return inner
    return wrap


def approve_ready(rt, at: str = CAP_TIME) -> None:
    """READY + binding in the probe's scratch registries (what G3 produces; test roots only)."""

    from genesis.pit import OperationalStatus, SourceCapability

    rt.stores.capabilities.register(SourceCapability(
        source_id=rt.stores.source_id, provider="oddspapi", access_method="rest_pregame_v4", cost_tier="t",
        entitlement_class="e", historical_availability_class="none", point_in_time_reliability="prospective_verified",
        revision_behaviour="append_only_supersede", coverage="c", rate_quota_limits="r", schema_version="v1",
        operational_status=OperationalStatus.READY, recorded_at=at, version=rt.stores.derivation_version + "-ready-1"))
    rt.stores.bindings.register(source_id=rt.stores.source_id, source_contract_id=rt.stores.contract_id,
                                provider="oddspapi", approval_reference="synthetic-test-only-reaudit")


def pit_rows(rt) -> list[dict]:
    return [r for r in rt.stores.pit.log.records() if r.get("record_type") == "pit_record"]


def doc(rt, row) -> dict:
    return json.loads(rt.stores.evidence.get_bytes(row["payload_hash"]))


def crash_on_row(record_type: str, after: bool):
    """Patch: die (BaseException) just before / just after the named acquisition-ledger row."""

    def patch(rt):
        ledger = rt.runner.ledger
        original = ledger.append

        def append(kind, **kw):
            if kind == record_type and not after:
                ledger.append = original
                raise c.Crash(f"before {kind}")
            original(kind, **kw)
            if kind == record_type and after:
                ledger.append = original
                raise c.Crash(f"after {kind}")

        ledger.append = append
        return lambda: setattr(ledger, "append", original)
    return patch


def http_date(iso: str) -> str:
    from email.utils import format_datetime

    return format_datetime(c.parse(iso), usegmt=True)


def finish(out: str | None) -> int:
    cannot = [r for r in RESULTS if r.get("status") == "CANNOT_RUN"]
    failed = [r for r in RESULTS if not r["pass"] and r.get("status") != "CANNOT_RUN"]
    summary = {"checks": len(RESULTS), "failed": len(failed), "cannot_run": len(cannot), "results": RESULTS}
    if out:
        Path(out).write_bytes((json.dumps(summary, indent=1, default=str) + "\n").encode("utf-8"))
    print(f"== {len(RESULTS)} checks, {len(failed)} failed, {len(cannot)} cannot run")
    return 1 if failed else (2 if cannot else 0)
