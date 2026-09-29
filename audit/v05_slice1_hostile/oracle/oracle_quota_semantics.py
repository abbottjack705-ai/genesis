#!/usr/bin/env python3
"""Oracle 9/2 - frozen QuotaLedger semantics the adapter must respect (areas 2, 9).

Runs the FROZEN genesis.quota.QuotaLedger with the test fixture (250, 220, 30, 7) and
records what the frozen authority actually does. These are the facts behind the
request-identity / replay attacks:

  Q-A  same request_id + IDENTICAL fingerprint (same Tq, units, hash) -> the ledger
       returns the ORIGINAL allowed decision again and writes no row. It does NOT
       raise. => An adapter restart that re-derives the same request_id and re-uses
       the persisted Tq would be told "allowed" and could re-send under the old debit.
       c8dfafd 14.4 only promises RegistryConflict for a NEW occurred_at. The candidate
       must therefore never call request() for an attempt that already has a
       quota_decided row (must reconcile as ORPHANED_RESERVATION first). Attack A-2.
  Q-B  same request_id + different occurred_at -> RegistryConflict (14.4 as written)
  Q-C  occurred_at earlier than the latest ledger row -> BLOCKED with reason
       quota_event_time_regressed (a decision, not an exception). The adapter must map
       this to a halt (F-03), not to a quiet NOT_ATTEMPTED that retries later.
  Q-D  8th unit in a UTC day -> daily_quota_exhausted; 221st normal unit -> blocked
  Q-E  RESERVE class without authorization -> blocked (reserve never self-authorizes)
  Q-F  billable_units <= 0 -> ValueError (why NON_METERED still debits >= 1)
  Q-G  day attribution is by occurred_at (Tq) UTC date: 7 units at 23:59:59.999999 and
       the 8th at 00:00:00.000000 next day is ALLOWED. This is the edge 14.6 guards.
  Q-H  a CachedData object with verified=True from the caller never yields a cache hit
       (only VerifiedCacheStore proof does), so a cache hit cannot be forged.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.repo) / "src"))
    from genesis.quota import BudgetClass, QuotaInterpretation, QuotaLedger, QuotaPolicy, CachedData
    from genesis.registry import RegistryConflict

    policy = QuotaPolicy.test_fixture(QuotaInterpretation.A, provider_monthly_allowance=250,
                                      normal_monthly_budget=220, reserve_units=30, daily_billable_budget=7)
    H = "b" * 64
    out = {}
    with tempfile.TemporaryDirectory() as td:
        led = QuotaLedger(Path(td) / "ledger.jsonl", policy=policy, allow_test_policy=True)
        d1 = led.request(request_id="oddspapi-attempt:1", occurred_at="2026-10-03T10:00:00Z",
                         provider_id="oddspapi", provider_request_hash=H)
        rows_before = len(led.log.records())
        d1b = led.request(request_id="oddspapi-attempt:1", occurred_at="2026-10-03T10:00:00Z",
                          provider_id="oddspapi", provider_request_hash=H)
        out["Q-A_identical_replay"] = {"first": d1.reason, "replay": d1b.reason, "replay_allowed": d1b.allowed,
                                       "new_rows_written": len(led.log.records()) - rows_before,
                                       "raised": False}
        try:
            led.request(request_id="oddspapi-attempt:1", occurred_at="2026-10-03T10:00:01Z",
                        provider_id="oddspapi", provider_request_hash=H)
            out["Q-B_new_time_same_id"] = {"raised": False}
        except RegistryConflict as exc:
            out["Q-B_new_time_same_id"] = {"raised": True, "message": str(exc)}
        d = led.request(request_id="oddspapi-attempt:2", occurred_at="2026-10-03T09:59:59Z",
                        provider_id="oddspapi", provider_request_hash=H)
        out["Q-C_time_regression"] = {"allowed": d.allowed, "reason": d.reason, "raised": False}
        # Q-D daily
        led2 = QuotaLedger(Path(td) / "daily.jsonl", policy=policy, allow_test_policy=True)
        reasons = []
        for i in range(8):
            r = led2.request(request_id=f"d{i}", occurred_at=f"2026-10-03T10:00:{i:02d}Z",
                             provider_id="oddspapi", provider_request_hash=H)
            reasons.append((r.allowed, r.reason))
        out["Q-D_daily_8th"] = {"seventh": reasons[6], "eighth": reasons[7]}
        led3 = QuotaLedger(Path(td) / "monthly.jsonl", policy=policy, allow_test_policy=True)
        last = None
        n = 0
        for day in range(1, 32):
            for k in range(7):
                n += 1
                last = led3.request(request_id=f"m{n}", occurred_at=f"2026-10-{day:02d}T10:00:{k:02d}Z",
                                    provider_id="oddspapi", provider_request_hash=H)
                if not last.allowed:
                    break
            if not last.allowed:
                break
        out["Q-D_normal_221st"] = {"requests_possible_in_31_day_month_at_1_unit": n, "last_reason": last.reason,
                                   "normal_used": last.normal_monthly_used,
                                   "note": "31 days x 7/day = 217 < 220: the monthly NORMAL cap is unreachable with 1-unit "
                                           "debits under the frozen active policy. A Q-03 test must use billable_units > 1 "
                                           "or a test policy; a test claiming to reach the 221st unit with 1-unit ODDS calls is impossible."}
        led5 = QuotaLedger(Path(td) / "reserve.jsonl", policy=policy, allow_test_policy=True)
        r = led5.request(request_id="reserve-try", occurred_at="2026-10-31T11:00:00Z", budget_class=BudgetClass.RESERVE,
                         provider_id="oddspapi", provider_request_hash=H)
        out["Q-E_reserve_unauthorized"] = {"allowed": r.allowed, "reason": r.reason}
        try:
            led.request(request_id="zero", occurred_at="2026-10-03T12:00:00Z", billable_units=0,
                        provider_id="oddspapi", provider_request_hash=H)
            out["Q-F_zero_units"] = {"raised": False}
        except ValueError as exc:
            out["Q-F_zero_units"] = {"raised": True, "message": str(exc)}
        led4 = QuotaLedger(Path(td) / "edge.jsonl", policy=policy, allow_test_policy=True)
        for i in range(7):
            led4.request(request_id=f"e{i}", occurred_at=f"2026-10-31T23:59:5{i}.999999Z",
                         provider_id="oddspapi", provider_request_hash=H)
        r = led4.request(request_id="e-next", occurred_at="2026-11-01T00:00:00.000000Z",
                         provider_id="oddspapi", provider_request_hash=H)
        out["Q-G_day_boundary_by_Tq"] = {"eighth_across_midnight_allowed": r.allowed, "reason": r.reason,
                                         "daily_used_after": r.daily_used, "monthly_used_after": r.monthly_used}
        forged = CachedData("forged", H, "oddspapi", policy.policy_digest,
                            "2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z", True)
        r = led.request(request_id="forged-hit", occurred_at="2026-10-03T13:00:00Z", cache=forged,
                        provider_id="oddspapi", provider_request_hash=H)
        out["Q-H_forged_cache"] = {"reason": r.reason, "billable_units": r.billable_units}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
