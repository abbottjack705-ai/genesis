"""E2: a material critical-evidence change invalidates its candidate for good.

Invariant: once a critical-evidence refresh records a material change for a
candidate, that candidate never recertifies for pending or sent again; a new
candidate is required. One candidate's refreshes are ordered by
``checked_at``: a refresh that does not advance it is refused when appended,
and a durable history that does not advance fails closed when read. Both are
derived from the whole durable history on every read, so they survive restart
and hold for rows that reached the log without the store's ``append``. A
failed, non-material refresh can still be followed by a later valid one.
"""

from __future__ import annotations

import unittest

from genesis.execution import CriticalEvidenceRefresh, CriticalEvidenceRefreshStore, OrderState
from genesis.registry import AppendOnlyJsonl, RegistryConflict

from ._support import scratch_directory
from .test_remediation_r6_execution import build_execution, restart_adapter, restart_risk


BOUND = "2026-01-01T00:13:00Z"
ACTION = "2026-01-01T00:17:00Z"


def bound_case(root):
    case = build_execution(root)
    case["adapter"].create_intent(case["intent"])
    case["adapter"].bind_risk("key-a", bound_at=BOUND)
    return case


def refresh(case, checked_at: str, valid: bool, material: bool) -> CriticalEvidenceRefresh:
    return CriticalEvidenceRefresh(
        case["intent"].candidate_decision_hash, checked_at, valid, material,
    )


def write(case, item: CriticalEvidenceRefresh, *, raw: bool) -> bool:
    """Append ``item``; ``raw`` writes its row as a pre-E2 store would have.

    The raw row goes through a plain log over the same file, because the
    store's own storage now refuses a row its replay rejects (E4).
    """

    store = case["refreshes"]
    try:
        if raw:
            AppendOnlyJsonl(store.log.path).append({
                "record_type": "critical_evidence_refresh",
                "schema_version": "critical-evidence-refresh-v2",
                "refresh_id": item.refresh_id,
                **item.to_dict(),
            })
        else:
            store.append(item)
    except RegistryConflict:
        return False
    return True


class T6E2CriticalRefreshTests(unittest.TestCase):
    def assert_blocked(self, case, root, reason: str) -> None:
        # The live adapter, then one reopened over the same logs (restart).
        for adapter in (case["adapter"], restart_adapter(root, restart_risk(root))):
            result = adapter.recertify("key-a", at=ACTION)
            self.assertEqual(
                (result.passed, result.reason, result.requires_new_candidate),
                (False, reason, reason == "critical_evidence_changed"),
            )
            with self.assertRaises(RegistryConflict):
                adapter.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION,
                )
            self.assertEqual(adapter.get("key-a").state, OrderState.RISK_APPROVED)

    def test_e2_a_later_valid_refresh_never_revalidates_a_material_change(self):
        for raw in (False, True):
            with self.subTest(raw=raw), scratch_directory() as root:
                case = bound_case(root)
                self.assertTrue(write(case, refresh(case, "2026-01-01T00:14:00Z", True, True), raw=False))
                later = refresh(case, "2026-01-01T00:15:00Z", True, False)
                written = write(case, later, raw=raw)
                self.assert_blocked(case, root, "critical_evidence_changed")
                self.assertEqual(written, raw)
                current = CriticalEvidenceRefreshStore(root / "refreshes.jsonl").current(
                    later.candidate_decision_hash
                )
                self.assertTrue(current.material_change)

    def test_e2_a_refresh_that_does_not_advance_is_refused_or_fails_closed(self):
        for first_valid, first_material in ((True, True), (False, False)):
            for checked_at in ("2026-01-01T00:12:00Z", "2026-01-01T00:15:00Z"):
                for raw in (False, True):
                    label = dict(material=first_material, checked_at=checked_at, raw=raw)
                    with self.subTest(**label), scratch_directory() as root:
                        case = bound_case(root)
                        self.assertTrue(write(
                            case, refresh(case, "2026-01-01T00:15:00Z", first_valid, first_material),
                            raw=False,
                        ))
                        stale = refresh(case, checked_at, True, False)
                        written = write(case, stale, raw=raw)
                        self.assert_blocked(
                            case, root,
                            "authority_unavailable" if raw else (
                                "critical_evidence_changed" if first_material
                                else "critical_evidence_refresh_failed"
                            ),
                        )
                        self.assertEqual(written, raw)

    def test_e2_a_failed_refresh_can_be_retried_and_reappending_is_idempotent(self):
        with scratch_directory() as root:
            case = bound_case(root)
            self.assertTrue(write(case, refresh(case, "2026-01-01T00:14:00Z", False, False), raw=False))
            failed = case["adapter"].recertify("key-a", at=ACTION)
            self.assertEqual(
                (failed.passed, failed.reason, failed.requires_new_candidate),
                (False, "critical_evidence_refresh_failed", False),
            )
            retry = refresh(case, "2026-01-01T00:15:00Z", True, False)
            case["refreshes"].append(retry)
            case["refreshes"].append(retry)  # the same refresh again is not a new one
            self.assertEqual(
                case["refreshes"].current(retry.candidate_decision_hash).to_dict(),
                retry.to_dict(),
            )
            restarted = restart_adapter(root, restart_risk(root))
            self.assertTrue(restarted.recertify("key-a", at=ACTION).passed)
            self.assertEqual(
                restarted.transition(
                    "key-a", OrderState.SUBMISSION_PENDING, occurred_at=ACTION,
                ).state,
                OrderState.SUBMISSION_PENDING,
            )


if __name__ == "__main__":
    unittest.main()
