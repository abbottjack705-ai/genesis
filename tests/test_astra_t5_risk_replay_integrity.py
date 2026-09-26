"""T5 / N3: an accepted risk append never makes the risk authority unreplayable.

Invariant: every append to the risk log is validated against the replay of the
log *including* the new row before it is committed. A factual exposure and an
approval-derived reservation share one identity namespace, so a collision in
either order is refused instead of permanently bricking admission, consumption,
send recertification, release and further factual exposure recording.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from genesis.registry import RegistryConflict
from genesis.risk import Exposure, ExposureState

from ._support import scratch_directory
from .test_astra_t5_owner_binding import risk_like
from .test_remediation_r5_risk import build_risk, request


class T5RiskReplayIntegrityTests(unittest.TestCase):
    def assert_replay_intact(self, engine, root: Path) -> None:
        engine.reserved_exposures()
        engine.record_exposure(
            Exposure("t5-later-real-exposure", "e" * 64, "1", ExposureState.MATCHED),
            recorded_at="2026-01-01T00:30:00Z",
        )
        risk_like(root).reserved_exposures()

    def test_exposure_id_colliding_with_an_approval_is_refused_without_poisoning(self):
        with scratch_directory() as root:
            f = build_risk(root)
            engine = f["engine"]
            decision = engine.approve(request(f))
            self.assertTrue(decision.passed)
            before = engine.audit_log.log.verify()
            with self.assertRaises(RegistryConflict, msg="N3: colliding exposure was appended"):
                engine.record_exposure(
                    Exposure(decision.approval_id, "f" * 64, "1", ExposureState.MATCHED),
                    recorded_at="2026-01-01T00:20:00Z",
                )
            self.assertEqual(engine.audit_log.log.verify(), before)
            self.assert_replay_intact(engine, root)

    def test_approval_colliding_with_a_prior_exposure_is_refused_without_poisoning(self):
        with scratch_directory() as root:
            original = root / "original"
            f = build_risk(original)
            probe = root / "probe"
            shutil.copytree(original, probe)
            predicted = risk_like(probe).approve(request(f))
            self.assertTrue(predicted.passed)
            engine = f["engine"]
            engine.record_exposure(
                Exposure(predicted.approval_id, "f" * 64, "1", ExposureState.MATCHED),
                recorded_at="2026-01-01T00:05:00Z",
            )
            try:
                decision = engine.approve(request(f))
            except RegistryConflict:
                decision = None
            self.assertFalse(
                decision is not None and decision.passed,
                "N3: an approval colliding with a factual exposure was admitted",
            )
            self.assert_replay_intact(engine, original)

    def test_collision_cannot_brick_admission_of_other_candidates(self):
        with scratch_directory() as root:
            f = build_risk(root)
            engine = f["engine"]
            decision = engine.approve(request(f))
            try:
                engine.record_exposure(
                    Exposure(decision.approval_id, "f" * 64, "1", ExposureState.MATCHED),
                    recorded_at="2026-01-01T00:20:00Z",
                )
            except RegistryConflict:
                pass
            try:
                engine.record_exposure(
                    Exposure("independent", "d" * 64, "2", ExposureState.MATCHED),
                    recorded_at="2026-01-01T00:21:00Z",
                )
                reserved = engine.reserved_exposures()
            except RegistryConflict as exc:
                self.fail(f"N3: an earlier collision bricked the risk authority: {exc}")
            self.assertEqual(
                sorted(item.exposure_id for item in reserved),
                sorted([decision.approval_id, "independent"]),
            )


if __name__ == "__main__":
    unittest.main()
