"""C-1: one pinned composition root assembles the whole PAPER authority graph.

Invariant: ``compose_paper_deployment`` is the single place the offline PAPER
graph is composed. It reads a deployment manifest only when its SHA-256 equals
the operator's pin, binds every owner kind to the risk log in one durable row
before any owner acts, constructs every owner eagerly and verifies the whole
binding at startup. A deployment first bound piecemeal to other owners (the
first-composer route: a copied bankroll composed first) is refused rather than
operated; after composition, a forked graph over other owners cannot act (N2);
and a replaced manifest cannot rebind an initialised deployment.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from genesis.composition import (
    DEFAULT_LAYOUT, MANIFEST_NAME, compose_paper_deployment, write_deployment_manifest,
)
from genesis.config import OperationalMode
from genesis.execution import ModeState, ModeStateStore
from genesis.owner_binding import EXCLUSIVE_KINDS, OWNER_KINDS, RiskOwnerBinding, claim_log
from genesis.policy import PolicySet, RiskPolicy
from genesis.registry import RegistryConflict, StrategyRegistry
from genesis.repro import canonical_json, sha256_bytes
from genesis.risk import (
    BankrollSnapshotStore, RiskAuditLog, RiskEngine, SafetyStateStore,
)
from genesis.selection import QualificationRecordStore

from ._support import scratch_directory


def initialise_mode(root: Path) -> None:
    ModeStateStore(root / DEFAULT_LAYOUT["mode"]).append(ModeState.create(
        mode=OperationalMode.PAPER, occurred_at="2026-01-01T00:00:00Z",
        authorization_id="synthetic-offline-c1-test-only", parent_state_id=None,
    ))


def hand_composed(root: Path, *, bankroll: Path) -> RiskEngine:
    """A piecemeal composition over the deployment's files, except the bankroll."""

    return RiskEngine(
        policy=PolicySet(),
        bankrolls=BankrollSnapshotStore(bankroll),
        qualifications=QualificationRecordStore(root / DEFAULT_LAYOUT["qualification"]),
        safety=SafetyStateStore(root / DEFAULT_LAYOUT["safety"]),
        audit_log=RiskAuditLog(root / DEFAULT_LAYOUT["risk_log"]),
        strategies=StrategyRegistry(root / DEFAULT_LAYOUT["strategy"]),
        modes=ModeStateStore(root / DEFAULT_LAYOUT["mode"]),
    )


def binding_rows(root: Path) -> list[dict]:
    return RiskOwnerBinding(RiskAuditLog(root / DEFAULT_LAYOUT["risk_log"]).log).log.records()


class T6C1CompositionRootTests(unittest.TestCase):
    def test_c1_one_pinned_manifest_binds_every_owner_kind_eagerly(self):
        with scratch_directory() as root:
            pin = write_deployment_manifest(root, policy=PolicySet())
            initialise_mode(root)
            deployment = compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())
            [row] = binding_rows(root)
            self.assertEqual(set(row["owners"]), OWNER_KINDS)
            for kind in EXCLUSIVE_KINDS:
                path = root / DEFAULT_LAYOUT[kind]
                self.assertEqual(len(claim_log(path).records()), 1, kind)
            self.assertIs(deployment.execution.risk, deployment.risk)
            self.assertIs(deployment.risk.qualifications, deployment.qualifications)
            self.assertIs(deployment.risk.strategies, deployment.strategies)
            self.assertIs(deployment.execution.strategy_view.registry, deployment.strategies)
            self.assertIs(deployment.risk.modes, deployment.modes)
            self.assertIs(deployment.execution.modes, deployment.modes)
            self.assertIs(deployment.risk.release_proofs, deployment.release_proofs)
            self.assertEqual(deployment.risk.owner_mismatches(), ())
            restarted = compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())
            self.assertEqual(restarted.risk.owner_mismatches(), ())
            self.assertEqual(len(binding_rows(root)), 1)

    def test_c1_an_unpinned_or_malformed_manifest_is_refused_before_binding(self):
        good = {
            "schema_version": "genesis-paper-deployment-manifest-v1", "scope": "PAPER",
            "policy_digest": PolicySet().digest, "owners": dict(DEFAULT_LAYOUT),
        }
        variants = {
            "extra key": {**good, "adapter": "none"},
            "live scope": {**good, "scope": "LIVE"},
            "missing owner kind": {**good, "owners": {
                key: value for key, value in DEFAULT_LAYOUT.items() if key != "ledger"
            }},
            "parent traversal": {**good, "owners": {**DEFAULT_LAYOUT, "ledger": "../ledger.jsonl"}},
            "absolute path": {**good, "owners": {**DEFAULT_LAYOUT, "ledger": "/ledger.jsonl"}},
            "backslash path": {**good, "owners": {**DEFAULT_LAYOUT, "ledger": "a\\ledger.jsonl"}},
            "shared path": {**good, "owners": {**DEFAULT_LAYOUT, "ledger": DEFAULT_LAYOUT["order"]}},
        }
        raw_variants = {name: canonical_json(body) for name, body in variants.items()}
        raw_variants["non-canonical bytes"] = canonical_json(good)[:-1] + b" \n"
        raw_variants["repeated key"] = (
            b'{"scope":"PAPER",' + canonical_json(good)[1:]
        )
        for name, raw in raw_variants.items():
            with self.subTest(name), scratch_directory() as root:
                (root / MANIFEST_NAME).write_bytes(raw)
                initialise_mode(root)
                with self.assertRaises(RegistryConflict):
                    compose_paper_deployment(
                        root, manifest_sha256=sha256_bytes(raw), policy=PolicySet(),
                    )
                self.assertEqual(binding_rows(root), [])
        with scratch_directory() as root:
            pin = write_deployment_manifest(root, policy=PolicySet())
            initialise_mode(root)
            for label, arguments in (
                ("wrong pin", dict(manifest_sha256="0" * 64, policy=PolicySet())),
                ("other policy", dict(manifest_sha256=pin, policy=PolicySet(
                    risk=RiskPolicy(version="c1-other-policy"),
                ))),
            ):
                with self.subTest(label):
                    with self.assertRaises(RegistryConflict):
                        compose_paper_deployment(root, **arguments)
                    self.assertEqual(binding_rows(root), [])

    def test_c1_a_first_composer_over_other_owners_is_refused_not_operated(self):
        with scratch_directory() as root:
            pin = write_deployment_manifest(root, policy=PolicySet())
            initialise_mode(root)
            copy = hand_composed(root, bankroll=root / "copy" / "bankroll.jsonl")
            self.assertEqual(copy.owner_mismatches(), ())  # first use binds the copy
            with self.assertRaises(RegistryConflict):
                compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())

    def test_c1_after_composition_a_forked_graph_cannot_act(self):
        with scratch_directory() as root:
            pin = write_deployment_manifest(root, policy=PolicySet())
            initialise_mode(root)
            compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())
            fork = hand_composed(root, bankroll=root / "copy" / "bankroll.jsonl")
            self.assertEqual(fork.owner_mismatches(), ("bankroll",))
            restarted = compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())
            self.assertEqual(restarted.risk.owner_mismatches(), ())

    def test_c1_a_replaced_manifest_cannot_rebind_an_initialised_deployment(self):
        with scratch_directory() as root:
            pin = write_deployment_manifest(root, policy=PolicySet())
            initialise_mode(root)
            compose_paper_deployment(root, manifest_sha256=pin, policy=PolicySet())
            (root / MANIFEST_NAME).unlink()
            other = write_deployment_manifest(
                root, policy=PolicySet(),
                owners={**DEFAULT_LAYOUT, "bankroll": "elsewhere/bankroll.jsonl"},
            )
            with self.assertRaises(RegistryConflict):
                compose_paper_deployment(root, manifest_sha256=other, policy=PolicySet())
            self.assertEqual(len(binding_rows(root)), 1)


if __name__ == "__main__":
    unittest.main()
