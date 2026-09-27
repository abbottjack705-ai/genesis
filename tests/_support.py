from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from genesis.selection import QualificationRecord, QualificationRecordStore


# The fixture's stand-in for ``QualificationAuthority.evaluate``; identity only.
FIXTURE_RECORDING_AUTHORITY = object()


class SyntheticRecordingQualificationStore(QualificationRecordStore):
    """Fixture-only V3 recording authority; absent from production source.

    Production records a V3 qualification only through
    ``QualificationAuthority.evaluate`` (E1). Risk and execution fixtures
    record a synthetic one through that same recording path instead, so the
    F-2 prior-grant witness and every storage check still apply unchanged.
    """

    def _require_recording_authority(self, authority: object) -> None:
        if authority is not FIXTURE_RECORDING_AUTHORITY:
            super()._require_recording_authority(authority)

    def record_fixture_qualification(self, record: QualificationRecord) -> QualificationRecord:
        return self._record_evaluated(
            FIXTURE_RECORDING_AUTHORITY, record, verify=None, read_locks=(),
        )


class SyntheticQualificationRecordStore(SyntheticRecordingQualificationStore):
    """Fixture-only approval boundary; absent from production source."""

    def _require_separate_approval(
        self, reference: str, *, binding_hash: str, decision_at: str,
    ) -> None:
        if not reference.startswith("synthetic-test-only-"):
            raise ValueError("fixture does not recognize output approval")


@contextmanager
def scratch_directory():
    root = Path(__file__).resolve().parents[1] / "work" / "test_runtime" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
