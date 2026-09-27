from __future__ import annotations

import os
import shutil
import stat
import sys
import time
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


# Each active scratch root and the external directories attached to it (E10).
_SCRATCH_ROOTS: dict[Path, list[Path]] = {}


def remove_tree(path: str | Path, *, attempts: int = 20) -> None:
    """Remove ``path`` entirely, or raise (E10).

    Read-only entries, such as a nested Git repository's objects, are made
    writable and removed. A file still held open (Windows) is retried briefly
    while its owner exits. Anything that remains afterwards raises instead of
    being ignored, so a run that leaves residue is never reported as clean.
    """

    path = Path(path)

    def writable(function, target, _error) -> None:
        for item in (os.path.dirname(target), target):
            try:
                os.chmod(item, stat.S_IRWXU)
            except OSError:
                pass
        function(target)

    error: BaseException | None = None
    for attempt in range(attempts):
        if not os.path.lexists(path):
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=writable)
            else:
                shutil.rmtree(path, onerror=writable)
        except OSError as exc:
            error = exc
        if not os.path.lexists(path):
            return
        time.sleep(min(0.05 * (attempt + 1), 0.5))
    raise RuntimeError(f"test runtime residue could not be removed: {path}") from error


def attach_to_scratch(within: str | Path, path: str | Path) -> None:
    """Remove ``path``, a directory outside the repository, with the active
    scratch directory that ``within`` belongs to (E10)."""

    within = Path(within).resolve()
    for root, attached in _SCRATCH_ROOTS.items():
        if within == root or within.is_relative_to(root):
            attached.append(Path(path))
            return
    raise RuntimeError(f"no active scratch directory owns {within}")


@contextmanager
def scratch_directory():
    root = Path(__file__).resolve().parents[1] / "work" / "test_runtime" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    _SCRATCH_ROOTS[root] = []
    try:
        yield root
    finally:
        errors: list[BaseException] = []
        for path in (*reversed(_SCRATCH_ROOTS.pop(root, [])), root):
            try:
                remove_tree(path)
            except RuntimeError as exc:
                errors.append(exc)
        if errors:
            raise errors[0]
