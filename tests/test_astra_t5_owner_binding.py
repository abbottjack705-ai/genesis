"""T5 / N2: one risk authority acts through exactly one owner per authority kind.

Invariant: every durable fact that admits, consumes, submits, proves or
releases a PAPER action is read from the same authoritative owner that the risk
authority is bound to. Individually valid but different owners (a copied or
split strategy registry, safety/bankroll/mode/qualification store, order log,
market/refresh store or settlement ledger) must fail closed at admission,
consumption, submission, proof issuance, attachment and release. The same
owner reopened through another object or an equivalent path remains usable.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from genesis.accounting import SettlementKind
from genesis.execution import (
        ExecutionMarketStateStore,
    ModeController,
    ModeStateStore,
    OrderState,
    PaperExecutionAdapter,
    RegistryStrategyExecutionView,
)
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import RegistryConflict, StrategyLifecycle, StrategyRegistry
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.risk import (
    BankrollSnapshotStore,
    RiskAuditLog,
    RiskEngine,
    SafetyStateStore,
)

from ._support import SyntheticQualificationRecordStore, scratch_directory
from .test_remediation_r5_risk import build_risk, request
from .test_remediation_r6_execution import build_execution, restart_adapter, restart_risk


PENDING = OrderState.SUBMISSION_PENDING
SENT = OrderState.SUBMISSION_SENT


def bound(f):
    f["adapter"].create_intent(f["intent"])
    f["adapter"].bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")


def settle_on(adapter, ledger, f):
    adapter.transition("key-a", OrderState.ACK_RECEIVED, occurred_at="2026-01-01T00:15:10Z")
    ledger.record_fill(FillRecord(
        fill_id="fill-1", order_id=f["intent"].order_id,
        candidate_decision_hash=f["intent"].candidate_decision_hash,
        side=f["intent"].side, odds=f["intent"].odds, stake=f["intent"].stake,
        filled_at="2026-01-01T00:16:01Z",
    ))
    adapter.transition("key-a", OrderState.FULLY_MATCHED, occurred_at="2026-01-01T00:17:00Z")
    ledger.settle(event_id="settlement-1", fill_id="fill-1", kind=SettlementKind.WIN,
                  occurred_at="2026-01-01T00:18:01Z")
    adapter.transition("key-a", OrderState.SETTLED, occurred_at="2026-01-01T00:20:00Z")


def risk_like(fixture_root: Path, **replacements) -> RiskEngine:
    """Open a risk engine over the fixture's exact risk log with named owners."""

    owners = {
        "policy": None,
        "bankrolls": BankrollSnapshotStore(fixture_root / "bankroll.jsonl"),
        "qualifications": SyntheticQualificationRecordStore(fixture_root / "qualifications.jsonl"),
        "safety": SafetyStateStore(fixture_root / "safety.jsonl"),
        "audit_log": RiskAuditLog(fixture_root / "risk.jsonl"),
        "strategies": StrategyRegistry(fixture_root / "strategies.jsonl"),
        "modes": ModeStateStore(fixture_root / "mode.jsonl"),
    }
    owners.update(replacements)
    from genesis.policy import PolicySet

    owners["policy"] = PolicySet()
    return RiskEngine(action_clock=lambda requested_at: requested_at, **owners)


def admitted(action) -> bool:
    """True only when risk admission positively passes; refusal is False."""

    try:
        return action().passed
    except (RegistryConflict, ValueError, TypeError):
        return False


class T5OwnerBindingTests(unittest.TestCase):
    def assert_refused(self, action, message: str) -> None:
        try:
            action()
        except (RegistryConflict, ValueError, TypeError):
            return
        self.fail(message)

    # --- auditor N2 inventory -------------------------------------------------

    def test_split_strategy_registry_cannot_submit(self):
        for phase in (PENDING, SENT):
            with self.subTest(phase=phase.value), scratch_directory() as root:
                f = build_execution(root)
                adapter = f["adapter"]
                bound(f)
                if phase == SENT:
                    adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
                prior = adapter.get("key-a").state
                copy = root / "view-strategies.jsonl"
                shutil.copyfile(f["risk_fixture"]["strategies"].log.path, copy)
                adapter.strategy_view = RegistryStrategyExecutionView(StrategyRegistry(copy))
                self.assert_refused(
                    lambda: adapter.transition("key-a", phase, occurred_at="2026-01-01T00:16:00Z"),
                    "N2-a: submission was fenced on a different strategy registry than risk reads",
                )
                self.assertEqual(adapter.get("key-a").state, prior)

    def test_split_strategy_registry_withdrawal_is_not_bypassed(self):
        # Guard, not RED on T4: risk re-reads its own registry at send.
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            copy = root / "view-strategies.jsonl"
            shutil.copyfile(f["risk_fixture"]["strategies"].log.path, copy)
            f["risk_fixture"]["strategies"].transition(
                "strategy", "v1", StrategyLifecycle.RETIRED, occurred_at="2026-01-01T00:13:30Z",
            )

            def split_submit():
                adapter = PaperExecutionAdapter(
                    root / "orders.jsonl", risk=f["risk_fixture"]["engine"],
                    markets=f["markets"], refreshes=f["refreshes"],
                    strategy_view=RegistryStrategyExecutionView(StrategyRegistry(copy)),
                    modes=f["modes"], action_clock=lambda at: at,
                )
                adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")

            self.assert_refused(split_submit, "N2-a: a withdrawn strategy was submitted via a copy")

    def test_second_order_log_cannot_submit_a_consumed_approval(self):
        with scratch_directory() as root:
            f = build_execution(root)
            real = f["adapter"]
            bound(f)
            shutil.copyfile(real._audit.path, root / "second-orders.jsonl")
            real.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
            real.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z")

            def second_send():
                second = PaperExecutionAdapter(
                    root / "second-orders.jsonl", risk=real.risk, markets=real.markets,
                    refreshes=real.refreshes, strategy_view=real.strategy_view,
                    modes=real.modes, action_clock=lambda at: at,
                )
                second.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:30Z")
                second.transition("key-a", SENT, occurred_at="2026-01-01T00:15:30Z")

            self.assert_refused(second_send, "N2-c: one approval was sent from two order logs")
            consumed = [
                row for row in real.risk.audit_log.log.records()
                if row.get("record_type") == "risk_approval_consumed"
            ]
            self.assertEqual(len(consumed), 1)

    def test_shadow_release_owner_cannot_release_a_live_sent_order(self):
        with scratch_directory() as root:
            f = build_execution(root)
            real = f["adapter"]
            bound(f)
            shadow_path = root / "shadow-orders.jsonl"
            shutil.copyfile(real._audit.path, shadow_path)
            real.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
            real.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z")

            def shadow_release():
                shadow = PaperExecutionAdapter(
                    shadow_path, risk=real.risk, markets=real.markets,
                    refreshes=real.refreshes, strategy_view=real.strategy_view,
                    modes=real.modes, action_clock=lambda at: at,
                )
                shadow.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:10Z")
                shadow.transition("key-a", SENT, occurred_at="2026-01-01T00:15:05Z")
                shadow_ledger = SettlementLedger(root / "shadow-ledger.jsonl")
                settle_on(shadow, shadow_ledger, f)
                owner = OfflinePaperReleaseProofStore(
                    root / "shadow-proofs.jsonl", risk=real.risk,
                    execution=shadow, ledger=shadow_ledger,
                )
                proof = owner.issue_full_settlement(
                    f["intent"].order_id, occurred_at="2026-01-01T00:21:00Z",
                )
                real.risk.attach_release_proofs(owner)
                real.risk.release_with_proof(proof, occurred_at="2026-01-01T00:22:00Z")

            self.assert_refused(shadow_release, "N2-b: a shadow proof owner released a live order")
            self.assertEqual(real.get("key-a").state, SENT)
            self.assertEqual(len(real.risk.reserved_exposures()), 1)

    # --- the same class across every other authority owner --------------------

    def test_split_risk_owned_authority_cannot_admit_risk(self):
        for name, filename, store in (
            ("safety", "safety.jsonl", SafetyStateStore),
            ("bankrolls", "bankroll.jsonl", BankrollSnapshotStore),
            ("strategies", "strategies.jsonl", StrategyRegistry),
            ("modes", "mode.jsonl", ModeStateStore),
            ("qualifications", "qualifications.jsonl", SyntheticQualificationRecordStore),
        ):
            with self.subTest(owner=name), scratch_directory() as root:
                f = build_risk(root)
                copy = root / f"split-{filename}"
                shutil.copyfile(root / filename, copy)
                self.assertFalse(
                    admitted(lambda: risk_like(root, **{name: store(copy)}).approve(request(f))),
                    f"N2: risk admission used a split {name} owner",
                )

    def test_split_safety_and_mode_owners_cannot_hide_a_kill_switch(self):
        with scratch_directory() as root:
            f = build_risk(root)
            safety_copy = root / "split-safety.jsonl"
            mode_copy = root / "split-mode.jsonl"
            shutil.copyfile(root / "safety.jsonl", safety_copy)
            shutil.copyfile(root / "mode.jsonl", mode_copy)
            ModeController(f["modes"], f["safety"]).activate_kill_switch(
                occurred_at="2026-01-01T00:05:00Z",
            )
            self.assertFalse(
                admitted(lambda: risk_like(
                    root, safety=SafetyStateStore(safety_copy), modes=ModeStateStore(mode_copy),
                ).approve(request(f))),
                "N2: stale safety/mode copies admitted risk after the kill switch",
            )

    def test_swapped_owner_attribute_is_refused_at_action_time(self):
        with scratch_directory() as root:
            f = build_risk(root)
            copy = root / "split-safety.jsonl"
            shutil.copyfile(root / "safety.jsonl", copy)
            engine = f["engine"]
            engine.safety = SafetyStateStore(copy)
            self.assertFalse(
                admitted(lambda: engine.approve(request(f))),
                "N2: a swapped safety owner admitted risk",
            )

    def test_split_market_owner_cannot_submit(self):
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            copy = root / "split-markets.jsonl"
            shutil.copyfile(f["markets"].log.path, copy)

            def split_submit():
                adapter = PaperExecutionAdapter(
                    root / "orders.jsonl", risk=f["risk_fixture"]["engine"],
                    markets=ExecutionMarketStateStore(copy), refreshes=f["refreshes"],
                    strategy_view=f["adapter"].strategy_view, modes=f["modes"],
                    action_clock=lambda at: at,
                )
                adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")

            self.assert_refused(split_submit, "N2: submission used a split market owner")

    def test_ledger_owner_cannot_be_substituted_after_binding(self):
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            engine = f["risk_fixture"]["engine"]
            engine.attach_release_proofs(OfflinePaperReleaseProofStore(
                root / "proofs.jsonl", risk=engine, execution=f["adapter"],
                ledger=SettlementLedger(root / "ledger.jsonl"),
            ))
            restarted = restart_risk(root)
            adapter = restart_adapter(root, restarted)
            self.assert_refused(
                lambda: restarted.attach_release_proofs(OfflinePaperReleaseProofStore(
                    root / "proofs.jsonl", risk=restarted, execution=adapter,
                    ledger=SettlementLedger(root / "other-ledger.jsonl"),
                )),
                "N2: a different settlement ledger replaced the bound ledger",
            )

    # --- legitimate compositions must keep working ----------------------------

    def test_restarted_identical_owners_still_submit_prove_and_release(self):
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            risk = restart_risk(root)
            adapter = restart_adapter(root, risk)
            adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
            adapter.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z")
            ledger = SettlementLedger(root / "ledger.jsonl")
            settle_on(adapter, ledger, f)
            owner = OfflinePaperReleaseProofStore(
                root / "proofs.jsonl", risk=risk, execution=adapter, ledger=ledger,
            )
            proof = owner.issue_full_settlement(f["intent"].order_id, occurred_at="2026-01-01T00:21:00Z")
            risk.attach_release_proofs(owner)
            risk.release_with_proof(proof, occurred_at="2026-01-01T00:22:00Z")
            self.assertEqual(risk.reserved_exposures(), ())

    def test_equivalent_path_to_the_same_owner_is_the_same_owner(self):
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            (root / "alias").mkdir()
            adapter = PaperExecutionAdapter(
                root / "alias" / ".." / "orders.jsonl", risk=f["risk_fixture"]["engine"],
                markets=ExecutionMarketStateStore(root / "alias" / ".." / "markets.jsonl"),
                refreshes=f["refreshes"], strategy_view=f["adapter"].strategy_view,
                modes=f["modes"], action_clock=lambda at: at,
            )
            self.assertEqual(
                adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z").state,
                PENDING,
            )

    def test_relocated_complete_deployment_keeps_working(self):
        with scratch_directory() as root:
            original = root / "original"
            f = build_execution(original)
            bound(f)
            moved = root / "moved"
            shutil.copytree(original, moved)
            risk = restart_risk(moved)
            adapter = restart_adapter(moved, risk)
            adapter.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
            self.assertEqual(
                adapter.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z").state, SENT,
            )


if __name__ == "__main__":
    unittest.main()
