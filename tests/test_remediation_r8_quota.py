from __future__ import annotations

import inspect
import json
import multiprocessing
import os
import unittest
from pathlib import Path

from genesis.quota import (
    QUOTA_EVENT_SCHEMA,
    BudgetClass,
    CachedData,
    QuotaInterpretation,
    QuotaLedger,
    QuotaPolicy,
    QuotaReserveAuthorization,
    load_quota_policy,
)
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from ._support import scratch_directory


ACTIVE_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "oddspapi_quota_policy_v2.json"
)


def digest(character: str) -> str:
    return character * 64


def authorization(
    policy: QuotaPolicy,
    *,
    period: str = "2026-01",
    max_units: int = 30,
    provider_id: str | None = None,
    policy_version: str | None = None,
    policy_digest: str | None = None,
    granted_at: str = "2025-12-31T00:00:00Z",
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_through: str = "2026-02-01T00:00:00Z",
) -> QuotaReserveAuthorization:
    return QuotaReserveAuthorization.create(
        provider_id=provider_id or policy.provider_id,
        quota_policy_version=policy_version or policy.version,
        quota_policy_digest=policy_digest or policy.policy_digest,
        quota_period=period,
        max_reserve_units=max_units,
        reason="operator continuity reserve",
        approval_reference="APPROVAL-R8",
        granted_at=granted_at,
        valid_from=valid_from,
        valid_through=valid_through,
    )


def seed_legacy_normal(path: Path, *, units: int = 220) -> None:
    AppendOnlyJsonl(path).append(
        {
            "record_type": "billable_call",
            "request_id": "legacy-normal-seed",
            "occurred_at": "2026-01-01T00:00:00Z",
            "units": units,
        }
    )


def _daily_worker(path_text: str, policy_path_text: str, start, worker: int) -> None:
    ledger = QuotaLedger.from_active_config(path_text, policy_path_text)
    start.wait()
    decision = ledger.request(
        request_id=f"daily-race-{worker}",
        occurred_at="2026-01-02T00:00:00Z",
    )
    os._exit(0 if decision.allowed else 2)


def _reserve_worker(
    path_text: str,
    policy_path_text: str,
    authorization_id: str,
    start,
    worker: int,
) -> None:
    ledger = QuotaLedger.from_active_config(path_text, policy_path_text)
    start.wait()
    decision = ledger.request(
        request_id=f"reserve-race-{worker}",
        occurred_at="2026-01-02T00:01:00Z",
        budget_class=BudgetClass.RESERVE,
        authorization_id=authorization_id,
    )
    os._exit(0 if decision.allowed else 2)


def _normal_monthly_worker(path_text: str, start, worker: int) -> None:
    policy = QuotaPolicy.test_fixture(
        QuotaInterpretation.A,
        provider_monthly_allowance=250,
        normal_monthly_budget=220,
        reserve_units=30,
        daily_billable_budget=1000,
    )
    ledger = QuotaLedger(path_text, policy=policy, allow_test_policy=True)
    start.wait()
    decision = ledger.request(
        request_id=f"monthly-race-{worker}",
        occurred_at="2026-01-02T00:00:00Z",
    )
    os._exit(0 if decision.allowed else 2)


class R8QuotaPolicyTests(unittest.TestCase):
    def test_active_record_is_digest_pinned_approved_interpretation_a(self):
        policy = load_quota_policy(ACTIVE_POLICY_PATH)
        self.assertEqual(policy.policy_interpretation, QuotaInterpretation.A)
        self.assertEqual(
            (
                policy.provider_monthly_allowance,
                policy.normal_monthly_budget,
                policy.reserve_units,
                policy.daily_billable_budget,
            ),
            (250, 220, 30, 7),
        )
        self.assertTrue(policy.approved_active)
        self.assertFalse(policy.test_only)
        self.assertEqual(policy.approval_reference, "D-REM-001")
        self.assertTrue(policy.provider_terms_reverification_required)

    def test_missing_corrupt_revoked_or_test_only_active_policy_fails_closed(self):
        with scratch_directory() as root:
            with self.assertRaises(RegistryConflict):
                load_quota_policy(root / "missing.json")
            corrupt = root / "corrupt.json"
            corrupt.write_text('{"policy_interpretation":"B"}', encoding="utf-8")
            with self.assertRaises(RegistryConflict):
                load_quota_policy(corrupt)

            active = load_quota_policy(ACTIVE_POLICY_PATH)
            revoked_fields = active.unsigned_dict() | {"approval_revoked": True}
            revoked = QuotaPolicy.create(**revoked_fields)
            with self.assertRaises(RegistryConflict):
                QuotaLedger(root / "revoked.jsonl", policy=revoked)

            policy_b = QuotaPolicy.test_fixture(
                QuotaInterpretation.B,
                provider_monthly_allowance=250,
                normal_monthly_budget=190,
                reserve_units=30,
                daily_billable_budget=1000,
            )
            with self.assertRaises(RegistryConflict):
                QuotaLedger(root / "b-active.jsonl", policy=policy_b)
            QuotaLedger(
                root / "b-test.jsonl",
                policy=policy_b,
                allow_test_policy=True,
            )

    def test_legacy_policy_migration_requires_named_interpretation(self):
        policy_a = QuotaPolicy.from_legacy(
            interpretation=QuotaInterpretation.A,
            provider_monthly_allowance=250,
            daily_billable_limit=7,
            monthly_billable_limit=220,
            monthly_reserve=30,
        )
        policy_b = QuotaPolicy.from_legacy(
            interpretation=QuotaInterpretation.B,
            provider_monthly_allowance=250,
            daily_billable_limit=7,
            monthly_billable_limit=220,
            monthly_reserve=30,
        )
        self.assertEqual(policy_a.normal_monthly_budget, 220)
        self.assertEqual(policy_b.normal_monthly_budget, 190)
        with self.assertRaises(TypeError):
            QuotaPolicy.from_legacy(  # type: ignore[call-arg]
                provider_monthly_allowance=250,
                daily_billable_limit=7,
                monthly_billable_limit=220,
                monthly_reserve=30,
            )

    def test_interpretation_a_boundaries_190_191_220_221_250_251(self):
        with scratch_directory() as root:
            policy = QuotaPolicy.test_fixture(
                QuotaInterpretation.A,
                provider_monthly_allowance=250,
                normal_monthly_budget=220,
                reserve_units=30,
                daily_billable_budget=1000,
            )
            ledger = QuotaLedger(root / "a.jsonl", policy=policy, allow_test_policy=True)
            self.assertTrue(
                ledger.request(
                    request_id="through-190",
                    occurred_at="2026-01-01T00:00:00Z",
                    billable_units=190,
                ).allowed
            )
            self.assertTrue(
                ledger.request(
                    request_id="call-191",
                    occurred_at="2026-01-01T00:01:00Z",
                ).allowed
            )
            self.assertTrue(
                ledger.request(
                    request_id="through-220",
                    occurred_at="2026-01-01T00:02:00Z",
                    billable_units=29,
                ).allowed
            )
            call_221 = ledger.request(
                request_id="normal-221",
                occurred_at="2026-01-01T00:03:00Z",
            )
            self.assertFalse(call_221.allowed)
            self.assertEqual(call_221.reason, "normal_monthly_budget_exhausted")

            reserve = authorization(policy)
            self.assertEqual(ledger.grant_authorization(reserve), reserve.authorization_id)
            self.assertEqual(ledger.grant_authorization(reserve), reserve.authorization_id)
            through_250 = ledger.request(
                request_id="through-250",
                occurred_at="2026-01-01T00:04:00Z",
                billable_units=30,
                budget_class=BudgetClass.RESERVE,
                authorization_id=reserve.authorization_id,
            )
            self.assertTrue(through_250.allowed)
            self.assertEqual(through_250.monthly_used, 250)
            call_251 = ledger.request(
                request_id="call-251",
                occurred_at="2026-01-01T00:05:00Z",
                budget_class=BudgetClass.RESERVE,
                authorization_id=reserve.authorization_id,
            )
            self.assertFalse(call_251.allowed)
            self.assertEqual(ledger.usage("2026-01-01T12:00:00Z"), (250, 250))

    def test_interpretation_b_is_parameterized_but_stops_at_220(self):
        with scratch_directory() as root:
            policy = QuotaPolicy.test_fixture(
                QuotaInterpretation.B,
                provider_monthly_allowance=250,
                normal_monthly_budget=190,
                reserve_units=30,
                daily_billable_budget=1000,
            )
            ledger = QuotaLedger(root / "b.jsonl", policy=policy, allow_test_policy=True)
            self.assertTrue(
                ledger.request(
                    request_id="normal-190",
                    occurred_at="2026-01-01T00:00:00Z",
                    billable_units=190,
                ).allowed
            )
            self.assertFalse(
                ledger.request(
                    request_id="normal-191",
                    occurred_at="2026-01-01T00:01:00Z",
                ).allowed
            )
            reserve = authorization(policy)
            ledger.grant_authorization(reserve)
            self.assertTrue(
                ledger.request(
                    request_id="through-220",
                    occurred_at="2026-01-01T00:02:00Z",
                    billable_units=30,
                    budget_class=BudgetClass.RESERVE,
                    authorization_id=reserve.authorization_id,
                ).allowed
            )
            self.assertFalse(
                ledger.request(
                    request_id="call-221",
                    occurred_at="2026-01-01T00:03:00Z",
                    budget_class=BudgetClass.RESERVE,
                    authorization_id=reserve.authorization_id,
                ).allowed
            )
            self.assertEqual(ledger.usage("2026-01-01T12:00:00Z"), (220, 220))

    def test_verified_fresh_cache_is_zero_billable_but_stale_is_not(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            fresh = CachedData(
                "market-1",
                digest("a"),
                policy.provider_id,
                policy.policy_digest,
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                True,
            )
            ledger = QuotaLedger(root / "fresh.jsonl", policy=policy)
            decision = ledger.request(
                request_id="cache-hit",
                occurred_at="2026-01-01T00:30:00Z",
                cache=fresh,
            )
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.billable_units, 0)
            self.assertEqual(ledger.usage("2026-01-01T00:30:00Z"), (0, 0))

            stale = CachedData(
                "market-1",
                digest("a"),
                policy.provider_id,
                policy.policy_digest,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:15:00Z",
                True,
            )
            stale_ledger = QuotaLedger(root / "stale.jsonl", policy=policy)
            stale_decision = stale_ledger.request(
                request_id="stale",
                occurred_at="2026-01-01T00:30:00Z",
                cache=stale,
            )
            self.assertTrue(stale_decision.allowed)
            self.assertEqual(stale_decision.billable_units, 1)
            self.assertEqual(stale_ledger.usage("2026-01-01T00:30:00Z"), (1, 1))

            wrong_binding = CachedData(
                "market-1",
                digest("a"),
                "other-provider",
                digest("b"),
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                True,
            )
            bound_ledger = QuotaLedger(root / "wrong-binding.jsonl", policy=policy)
            bound_decision = bound_ledger.request(
                request_id="wrong-cache-binding",
                occurred_at="2026-01-01T00:30:00Z",
                cache=wrong_binding,
            )
            self.assertTrue(bound_decision.allowed)
            self.assertEqual(bound_decision.billable_units, 1)

    def test_daily_seventh_allowed_eighth_blocked_and_no_account_bypass_api(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            ledger = QuotaLedger(root / "daily.jsonl", policy=policy)
            for item in range(7):
                self.assertTrue(
                    ledger.request(
                        request_id=f"daily-{item}",
                        occurred_at=f"2026-01-01T00:0{item}:00Z",
                    ).allowed
                )
            eighth = ledger.request(
                request_id="daily-8", occurred_at="2026-01-01T00:08:00Z"
            )
            self.assertFalse(eighth.allowed)
            self.assertEqual(eighth.reason, "daily_quota_exhausted")
            self.assertFalse(
                ledger.request(
                    request_id="wrong-provider",
                    occurred_at="2026-01-02T00:00:00Z",
                    provider_id="second-account-provider",
                ).allowed
            )
            self.assertNotIn("account_id", inspect.signature(ledger.request).parameters)
            with self.assertRaises(TypeError):
                ledger.request(  # type: ignore[call-arg]
                    request_id="account-bypass",
                    occurred_at="2026-01-02T00:01:00Z",
                    account_id="second-key",
                )

    def test_reserve_authority_binding_expiry_revocation_and_grant_limit(self):
        policy = load_quota_policy(ACTIVE_POLICY_PATH)
        cases: list[tuple[str, QuotaReserveAuthorization | None, str, bool]] = [
            (
                "wrong-provider",
                authorization(policy, provider_id="other-provider"),
                "reserve_authorization_wrong_provider",
                True,
            ),
            (
                "wrong-policy",
                authorization(
                    policy,
                    policy_version="other-policy",
                    policy_digest=digest("b"),
                ),
                "reserve_authorization_wrong_policy",
                True,
            ),
            (
                "wrong-period",
                authorization(policy, period="2026-02"),
                "reserve_authorization_wrong_period",
                False,
            ),
            (
                "expired",
                authorization(
                    policy,
                    valid_through="2026-01-15T00:00:00Z",
                ),
                "reserve_authorization_expired",
                False,
            ),
            ("missing", None, "reserve_authorization_required", False),
        ]
        with scratch_directory() as root:
            for name, reserve, expected, raw in cases:
                with self.subTest(name=name):
                    path = root / f"{name}.jsonl"
                    seed_legacy_normal(path)
                    ledger = QuotaLedger(path, policy=policy)
                    authorization_id = None
                    if reserve is not None:
                        authorization_id = reserve.authorization_id
                        if raw:
                            ledger.log.append(
                                {
                                    "record_type": "quota_reserve_authorization_granted",
                                    "event_schema_version": QUOTA_EVENT_SCHEMA,
                                    **reserve.to_dict(),
                                }
                            )
                        else:
                            ledger.grant_authorization(reserve)
                    decision = ledger.request(
                        request_id=f"request-{name}",
                        occurred_at="2026-01-20T00:00:00Z",
                        budget_class=BudgetClass.RESERVE,
                        authorization_id=authorization_id,
                    )
                    self.assertFalse(decision.allowed)
                    self.assertEqual(decision.reason, expected)

            revoked_path = root / "revoked.jsonl"
            seed_legacy_normal(revoked_path)
            revoked_ledger = QuotaLedger(revoked_path, policy=policy)
            reserve = authorization(policy)
            revoked_ledger.grant_authorization(reserve)
            revoked_ledger.revoke_authorization(
                reserve.authorization_id,
                revoked_at="2026-01-10T00:00:00Z",
                reason="operator revoked",
                approval_reference="APPROVAL-REVOKE",
            )
            revoked_ledger.revoke_authorization(
                reserve.authorization_id,
                revoked_at="2026-01-10T00:00:00Z",
                reason="operator revoked",
                approval_reference="APPROVAL-REVOKE",
            )
            decision = revoked_ledger.request(
                request_id="request-revoked",
                occurred_at="2026-01-20T00:00:00Z",
                budget_class=BudgetClass.RESERVE,
                authorization_id=reserve.authorization_id,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "reserve_authorization_revoked")

            limited_path = root / "limited.jsonl"
            seed_legacy_normal(limited_path)
            limited = QuotaLedger(limited_path, policy=policy)
            grant = authorization(policy, max_units=2)
            limited.grant_authorization(grant)
            self.assertTrue(
                limited.request(
                    request_id="grant-1",
                    occurred_at="2026-01-20T00:00:00Z",
                    billable_units=2,
                    budget_class=BudgetClass.RESERVE,
                    authorization_id=grant.authorization_id,
                ).allowed
            )
            self.assertFalse(
                limited.request(
                    request_id="grant-3",
                    occurred_at="2026-01-20T00:01:00Z",
                    budget_class=BudgetClass.RESERVE,
                    authorization_id=grant.authorization_id,
                ).allowed
            )

    def test_valid_reserve_authority_cannot_bypass_eighth_daily_call(self):
        with scratch_directory() as root:
            path = root / "quota.jsonl"
            seed_legacy_normal(path)
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            ledger = QuotaLedger(path, policy=policy)
            reserve = authorization(policy)
            ledger.grant_authorization(reserve)
            for item in range(7):
                self.assertTrue(
                    ledger.request(
                        request_id=f"reserve-daily-{item}",
                        occurred_at=f"2026-01-02T00:0{item}:00Z",
                        budget_class=BudgetClass.RESERVE,
                        authorization_id=reserve.authorization_id,
                    ).allowed
                )
            eighth = ledger.request(
                request_id="reserve-daily-8",
                occurred_at="2026-01-02T00:08:00Z",
                budget_class=BudgetClass.RESERVE,
                authorization_id=reserve.authorization_id,
            )
            self.assertFalse(eighth.allowed)
            self.assertEqual(eighth.reason, "daily_quota_exhausted")

    def test_request_id_replay_restart_schema_and_conflict(self):
        with scratch_directory() as root:
            path = root / "quota.jsonl"
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            ledger = QuotaLedger(path, policy=policy)
            first = ledger.request(
                request_id="one", occurred_at="2026-01-01T00:00:00Z"
            )
            count = ledger.verify()
            self.assertEqual(
                ledger.request(
                    request_id="one", occurred_at="2026-01-01T00:00:00Z"
                ),
                first,
            )
            self.assertEqual(ledger.verify(), count)
            with self.assertRaises(RegistryConflict):
                ledger.request(
                    request_id="one", occurred_at="2026-01-01T00:01:00Z"
                )
            restarted = QuotaLedger(path, policy=policy)
            self.assertEqual(restarted.usage("2026-01-01T12:00:00Z"), (1, 1))
            row = AppendOnlyJsonl(path).records()[-1]
            self.assertEqual(row["schema_version"], QUOTA_EVENT_SCHEMA)
            self.assertEqual(row["budget_class"], "normal")

    def test_semantic_replay_rejects_hash_valid_forged_allowance(self):
        with scratch_directory() as root:
            path = root / "forged.jsonl"
            policy = QuotaPolicy.test_fixture(
                QuotaInterpretation.A,
                provider_monthly_allowance=2,
                normal_monthly_budget=1,
                reserve_units=1,
                daily_billable_budget=2,
            )
            AppendOnlyJsonl(path).append(
                {
                    "record_type": "quota_billable_call",
                    "schema_version": QUOTA_EVENT_SCHEMA,
                    "request_id": "forged",
                    "request_fingerprint": digest("c"),
                    "occurred_at": "2026-01-01T00:00:00Z",
                    "provider_id": policy.provider_id,
                    "quota_policy_version": policy.version,
                    "quota_policy_digest": policy.policy_digest,
                    "billable_units": 2,
                    "requested_billable_units": 2,
                    "budget_class": "normal",
                    "authorization_id": None,
                    "allowed": True,
                    "reason": "billable_call_reserved",
                    "daily_used": 2,
                    "monthly_used": 2,
                    "normal_monthly_used": 2,
                    "reserve_monthly_used": 0,
                }
            )
            with self.assertRaises(RegistryConflict):
                QuotaLedger(path, policy=policy, allow_test_policy=True)

    def test_daily_concurrency_admits_exactly_seven(self):
        with scratch_directory() as root:
            path = root / "quota.jsonl"
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(
                    target=_daily_worker,
                    args=(str(path), str(ACTIVE_POLICY_PATH), start, worker),
                )
                for worker in range(8)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
            self.assertEqual(
                sorted(process.exitcode for process in processes),
                [0, 0, 0, 0, 0, 0, 0, 2],
            )
            ledger = QuotaLedger.from_active_config(path, ACTIVE_POLICY_PATH)
            self.assertEqual(ledger.usage("2026-01-02T12:00:00Z"), (7, 7))

    def test_normal_monthly_concurrency_stops_exactly_at_220(self):
        with scratch_directory() as root:
            path = root / "quota.jsonl"
            seed_legacy_normal(path, units=219)
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(
                    target=_normal_monthly_worker,
                    args=(str(path), start, worker),
                )
                for worker in range(4)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
            self.assertEqual(sorted(process.exitcode for process in processes), [0, 2, 2, 2])
            policy = QuotaPolicy.test_fixture(
                QuotaInterpretation.A,
                provider_monthly_allowance=250,
                normal_monthly_budget=220,
                reserve_units=30,
                daily_billable_budget=1000,
            )
            ledger = QuotaLedger(path, policy=policy, allow_test_policy=True)
            self.assertEqual(ledger.usage("2026-01-02T12:00:00Z"), (1, 220))

    def test_partial_reserve_rehydrates_and_concurrency_cannot_oversubscribe(self):
        with scratch_directory() as root:
            path = root / "quota.jsonl"
            seed_legacy_normal(path)
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            ledger = QuotaLedger(path, policy=policy)
            reserve = authorization(policy, max_units=3)
            ledger.grant_authorization(reserve)
            self.assertTrue(
                ledger.request(
                    request_id="reserve-before-restart",
                    occurred_at="2026-01-02T00:00:00Z",
                    budget_class=BudgetClass.RESERVE,
                    authorization_id=reserve.authorization_id,
                ).allowed
            )
            restarted = QuotaLedger(path, policy=policy)
            self.assertEqual(restarted.usage("2026-01-02T00:00:30Z"), (1, 221))

            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(
                    target=_reserve_worker,
                    args=(
                        str(path),
                        str(ACTIVE_POLICY_PATH),
                        reserve.authorization_id,
                        start,
                        worker,
                    ),
                )
                for worker in range(4)
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
            self.assertEqual(sorted(process.exitcode for process in processes), [0, 0, 2, 2])
            final = QuotaLedger(path, policy=policy)
            self.assertEqual(final.usage("2026-01-02T12:00:00Z"), (3, 223))
            reserve_calls = [
                row
                for row in final.log.records()
                if row.get("record_type") == "quota_billable_call"
                and row.get("budget_class") == "reserve"
            ]
            self.assertEqual(len(reserve_calls), 3)
            self.assertTrue(
                all(row["authorization_id"] == reserve.authorization_id for row in reserve_calls)
            )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
