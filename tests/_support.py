from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from genesis.selection import QualificationRecordStore


class SyntheticQualificationRecordStore(QualificationRecordStore):
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
