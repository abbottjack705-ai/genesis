"""T5 hostile pre-audit: attacks on the repaired N2/N3/O-5/package boundaries.

Each test states an invariant that must hold for the T5 repair to be complete,
including cases outside the auditor's original inventory:

* H1 (N2 reverse direction): an owner that carries portfolio capacity or
  candidate lineage (bankroll, qualification log, decision-output store)
  serves exactly one risk authority. A second risk log composed over the same
  owners must not approve the same candidate or spend the same bankroll.
* H2 (N2 attribute substitution): swapping an engine's release-proof owner or
  an adapter's order log after construction is refused at action time.
* H3 (N2 aliasing): a directory alias of a bound owner is the same owner; a
  file symlink is a different owner because it takes a different lock.
* H4 (N3 generality): every risk append is replay-checked, not only
  ``record_exposure``.
* H5 (package): schema downgrade, non-canonical manifest bytes, undeclared or
  unpinned members and source-path disagreement are rejected.
* H6 (O-5 foreign ledger): a genuine prior grant held in some other approval
  ledger is not the store's grant, so the qualification is never recorded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import unittest
import zipfile
from pathlib import Path

from genesis.execution import OrderState, PaperExecutionAdapter
from genesis.ledger import SettlementLedger
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.release_proof import OfflinePaperReleaseProofStore
from genesis.risk import Exposure, ExposureState, RiskAuditLog

from . import test_astra_t4_evidence_package as t4_package
from ._support import scratch_directory
from .test_astra_t4_evidence_package import MANIFEST_NAME, sha256
from .test_astra_t5_owner_binding import admitted, bound, risk_like, settle_on
from .test_remediation_r5_risk import build_risk, request
from .test_remediation_r6_execution import build_execution


PENDING = OrderState.SUBMISSION_PENDING
SENT = OrderState.SUBMISSION_SENT


def refused(action) -> bool:
    try:
        action()
    except (RegistryConflict, ValueError, TypeError):
        return True
    return False


class T5HostileOwnerTests(unittest.TestCase):
    def test_h1_one_qualification_and_bankroll_serve_one_risk_authority(self):
        with scratch_directory() as root:
            f = build_risk(root)
            self.assertTrue(f["engine"].approve(request(f)).passed)
            second = risk_like(root, audit_log=RiskAuditLog(root / "second-risk.jsonl"))
            self.assertFalse(
                admitted(lambda: second.approve(request(f))),
                "H1: a second risk log approved the same candidate from shared owners",
            )
            self.assertEqual(
                [row for row in RiskAuditLog(root / "second-risk.jsonl").log.records()
                 if row.get("record_type") == "risk_approval_created"],
                [],
            )

    def test_h1_each_exclusive_owner_alone_refuses_a_second_authority(self):
        for kind in ("bankroll", "qualification"):
            with self.subTest(owner=kind), scratch_directory() as root:
                shared = root / "shared"
                f = build_risk(shared)
                other = root / "other"
                shutil.copytree(shared, other)
                # The other deployment is a complete independent copy except
                # for the one shared owner, which still belongs to ``shared``.
                from genesis.risk import BankrollSnapshotStore
                from ._support import SyntheticQualificationRecordStore

                replacement = (
                    {"bankrolls": BankrollSnapshotStore(shared / "bankroll.jsonl")}
                    if kind == "bankroll" else
                    {"qualifications": SyntheticQualificationRecordStore(
                        shared / "qualifications.jsonl")}
                )
                # Remove the copy's forward owner manifest so the intruder binds
                # the shared owner on construction; only the shared owner's own
                # risk-authority claim can then refuse it.
                for manifest in other.glob("*.owners.jsonl*"):
                    manifest.unlink()
                intruder = risk_like(other, **replacement)
                self.assertFalse(
                    admitted(lambda: intruder.approve(request(f))),
                    f"H1: a {kind} owned by another risk authority admitted risk",
                )

    def test_h1_relocated_or_restarted_single_authority_still_approves(self):
        with scratch_directory() as root:
            original = root / "original"
            f = build_risk(original)
            moved = root / "moved"
            shutil.copytree(original, moved)
            self.assertTrue(risk_like(moved).approve(request(f)).passed)
            self.assertTrue(risk_like(original).approve(request(f)).passed)

    def test_h2_swapped_release_owner_cannot_release_or_mint_capacity(self):
        with scratch_directory() as root:
            f = build_execution(root)
            real = f["adapter"]
            bound(f)
            real.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z")
            real.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z")
            ledger = SettlementLedger(root / "ledger.jsonl")
            settle_on(real, ledger, f)
            engine = f["risk_fixture"]["engine"]
            owner = OfflinePaperReleaseProofStore(
                root / "proofs.jsonl", risk=engine, execution=real, ledger=ledger,
            )
            proof = owner.issue_full_settlement(f["intent"].order_id, occurred_at="2026-01-01T00:21:00Z")
            shadow = OfflinePaperReleaseProofStore(
                root / "shadow-proofs.jsonl", risk=engine, execution=real,
                ledger=SettlementLedger(root / "shadow-ledger.jsonl"),
            )
            engine.release_proofs = shadow
            self.assertTrue(refused(
                lambda: engine.release_with_proof(proof, occurred_at="2026-01-01T00:22:00Z")
            ), "H2: a swapped-in proof owner released a reservation")
            self.assertTrue(refused(engine.reserved_exposures))
            engine.release_proofs = None
            engine.attach_release_proofs(owner)
            engine.release_with_proof(proof, occurred_at="2026-01-01T00:22:00Z")
            self.assertEqual(engine.reserved_exposures(), ())

    def test_h2_swapped_order_log_cannot_create_bind_or_send(self):
        with scratch_directory() as root:
            f = build_execution(root)
            adapter = f["adapter"]
            adapter._audit = AppendOnlyJsonl(root / "swapped-orders.jsonl")
            self.assertTrue(refused(lambda: adapter.create_intent(f["intent"])))
            self.assertFalse((root / "swapped-orders.jsonl").exists())
            adapter._audit = AppendOnlyJsonl(root / "orders.jsonl")
            adapter.create_intent(f["intent"])
            # A copy that already holds the intent passes every order check;
            # only owner binding stands between it and consumption.
            shutil.copyfile(root / "orders.jsonl", root / "swapped-orders.jsonl")
            adapter._audit = AppendOnlyJsonl(root / "swapped-orders.jsonl")
            self.assertTrue(refused(
                lambda: adapter.bind_risk("key-a", bound_at="2026-01-01T00:13:00Z")
            ))
            self.assertEqual(
                [row for row in f["risk_fixture"]["engine"].audit_log.log.records()
                 if row.get("record_type") == "risk_approval_consumed"],
                [],
            )

    def test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not(self):
        with scratch_directory() as root:
            f = build_execution(root)
            bound(f)
            try:
                os.symlink(root, root.parent / f"{root.name}-dirlink", target_is_directory=True)
            except OSError:
                self.skipTest("this platform cannot create symlinks")
            alias = root.parent / f"{root.name}-dirlink"
            try:
                via_dir = PaperExecutionAdapter(
                    alias / "orders.jsonl", risk=f["risk_fixture"]["engine"],
                    markets=f["markets"], refreshes=f["refreshes"],
                    strategy_view=f["adapter"].strategy_view, modes=f["modes"],
                    action_clock=lambda at: at,
                )
                self.assertEqual(
                    via_dir.transition("key-a", PENDING, occurred_at="2026-01-01T00:14:00Z").state,
                    PENDING,
                )
                os.symlink(root / "orders.jsonl", root / "orders-link.jsonl")
                via_file = PaperExecutionAdapter(
                    root / "orders-link.jsonl", risk=f["risk_fixture"]["engine"],
                    markets=f["markets"], refreshes=f["refreshes"],
                    strategy_view=f["adapter"].strategy_view, modes=f["modes"],
                    action_clock=lambda at: at,
                )
                self.assertTrue(refused(
                    lambda: via_file.transition("key-a", SENT, occurred_at="2026-01-01T00:15:00Z")
                ), "H3: a file symlink with another lock was accepted as the bound owner")
            finally:
                os.unlink(alias)

    def test_h4_every_risk_append_is_replay_checked(self):
        with scratch_directory() as root:
            f = build_risk(root)
            engine = f["engine"]
            engine.record_exposure(
                Exposure("x" * 64, "e" * 64, "1", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:02:00Z",
            )
            before = engine.audit_log.log.verify()
            original = engine._exposures
            calls: list[int] = []

            def observed(rows, **kwargs):
                calls.append(len(rows))
                return original(rows, **kwargs)

            engine._exposures = observed
            decision = engine.approve(request(f))
            self.assertTrue(decision.passed)
            self.assertIn(before + 1, calls, "H4: approval append was not replay-checked")


class T5HostileApprovalTests(unittest.TestCase):
    def test_h6_prior_grant_in_a_foreign_approval_ledger_cannot_record_a_qualification(self):
        import genesis.decision_output as decision_output
        from . import test_remediation_r5_risk as r5
        from ._support import SyntheticRecordingQualificationStore

        original = decision_output.StrategyOutputRuleBindingStore.register_approved

        def register(store, body):
            foreign = decision_output.StrategyOutputApprovalStore(
                store.log.path.parent / "foreign-approvals-v2.jsonl"
            )
            reference = foreign.reserve(
                request_id="t5-foreign", reserved_by="synthetic-operator",
                reserved_at="2025-12-31T22:00:00Z",
            )
            binding_hash = original(store, dict(body, human_approval_reference=reference))
            foreign.grant(
                reference, binding_hash=binding_hash, approved_by="synthetic-operator",
                approved_at="2025-12-31T23:00:00Z",
            )
            return binding_hash

        saved = r5.QualificationRecordStore
        decision_output.StrategyOutputRuleBindingStore.register_approved = register
        # The production approval validator; only the V3 recording authority
        # is the fixture's (E1).
        r5.QualificationRecordStore = SyntheticRecordingQualificationStore
        try:
            with scratch_directory() as root:
                with self.assertRaises(
                    (RegistryConflict, ValueError),
                    msg="H6: a grant outside the store's own approval ledger admitted a qualification",
                ):
                    r5.build_risk(root)
        finally:
            decision_output.StrategyOutputRuleBindingStore.register_approved = original
            r5.QualificationRecordStore = saved


class T5HostilePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t4 = t4_package.AstraT4EvidencePackageTests()

    def forged(self, root: Path, archive: Path, name: str, change) -> Path:
        with zipfile.ZipFile(archive) as source:
            members = {info.filename: source.read(info.filename) for info in source.infolist()}
        change(members)
        output = root / name
        with zipfile.ZipFile(output, "x") as changed:
            for member, raw in members.items():
                changed.writestr(member, raw)
        Path(str(output) + ".sha256").write_text(
            f"{sha256(output.read_bytes())}  {output.name}\n", encoding="ascii",
        )
        return output

    @staticmethod
    def rewrite_manifest(members: dict, mutate, *, encode=None) -> None:
        manifest = json.loads(members[MANIFEST_NAME])
        mutate(manifest)
        members[MANIFEST_NAME] = (
            encode(manifest) if encode is not None
            else (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        )

    def test_h5_package_alternate_representations_and_omissions_fail_closed(self):
        with scratch_directory() as root:
            fixture = self.t4.fixture(root)
            archive = root / "package.zip"
            self.t4.build(fixture, archive)
            historical = sha256(fixture["historical"].read_bytes())

            def downgrade(members):
                self.rewrite_manifest(members, lambda m: (
                    m.update(schema_version="genesis-audit-evidence-package-v1"),
                    m.pop("raw_worktree_roots"),
                ))

            def noncanonical(members):
                self.rewrite_manifest(
                    members, lambda m: None,
                    encode=lambda m: (json.dumps(m, sort_keys=True, indent=4) + "\n").encode(),
                )

            def nan_number(members):
                raw = members[MANIFEST_NAME].decode()
                members[MANIFEST_NAME] = re.sub(
                    r'"bytes": \d+', '"bytes": NaN', raw, count=1,
                ).encode()

            def source_path_disagrees(members):
                def mutate(m):
                    for row in m["members"]:
                        if row["archive_path"] == "raw-worktree/evidence/raw.txt":
                            row["source_path"] = "source/program.py"
                self.rewrite_manifest(members, mutate)

            def root_undeclared(members):
                self.rewrite_manifest(members, lambda m: m.update(raw_worktree_roots=[]))

            def whole_root_dropped(members):
                def mutate(m):
                    m["raw_worktree_roots"] = []
                    m["members"] = [row for row in m["members"]
                                    if row["representation"] != "raw_worktree_bytes"]
                self.rewrite_manifest(members, mutate)
                members.pop("raw-worktree/evidence/raw.txt")

            def extra_historical(members):
                extra = b"unpinned historical bytes"
                def mutate(m):
                    m["members"].append({
                        "archive_path": "historical/zz-extra.bin", "bytes": len(extra),
                        "representation": "historical_raw_artifact_bytes",
                        "sha256": sha256(extra), "source_path": "zz-extra.bin",
                    })
                    m["members"].sort(key=lambda row: row["archive_path"])
                self.rewrite_manifest(members, mutate)
                members["historical/zz-extra.bin"] = extra

            pins = ("--require-raw-root", "evidence",
                    "--require-historical", f"original-s5.zip={historical}",
                    "--expect-commit", fixture["commit"])
            cases = {
                "downgrade": (downgrade, ()),
                "noncanonical": (noncanonical, ()),
                "nan": (nan_number, ()),
                "source-path": (source_path_disagrees, ()),
                "root-undeclared": (root_undeclared, ()),
                "root-dropped-pinned": (whole_root_dropped, pins),
                "extra-historical-pinned": (extra_historical, pins),
            }
            for label, (change, extra) in cases.items():
                with self.subTest(label):
                    forged = self.forged(root, archive, f"{label}.zip", change)
                    denied = self.t4.verify(forged, *extra)
                    self.assertNotEqual(denied.returncode, 0, f"H5 {label}: {denied.stdout}")
                    self.assertIn("audit package rejected", denied.stderr)
            # The documented limit: a self-consistent root removal passes
            # without pins or an out-of-band package hash (R-3), never with them.
            dropped = root / "root-dropped-pinned.zip"
            self.assertEqual(self.t4.verify(dropped).returncode, 0)
            accepted = self.t4.verify(archive, *pins)
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)


if __name__ == "__main__":
    unittest.main()
