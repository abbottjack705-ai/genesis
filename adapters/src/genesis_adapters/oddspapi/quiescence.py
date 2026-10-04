"""The acquisition-quiescence rule (design 6.3, 13.2; hostile audit HA-05, HA-06).

"Acquisition and decision phases are serialized. The decision runner takes ``D`` only after it acquires the
acquisition-quiescence lock (the ``acquisition.jsonl`` coordinator plus an adapter run lock)." Two mechanisms, both
fail closed:

* :func:`run_lock` - an exclusive operating-system lock on ``<root>/run.lock``. Every adapter phase that writes
  durable state (acquisition, normalization, resume, invalidation) holds it, and so does a decision phase
  (:func:`decision_phase`) while it takes its cutoff and reads. A second holder is refused, never queued. The lock
  belongs to its process, so a crash never leaves it held; re-entry within one process is counted.
* :func:`pending_work` - the durable facts that say an adapter phase is unfinished: an attempt still open, a
  credential or authorization verdict whose halt/circuit is missing, a successful ODDS capture not yet normalized, a
  derivation rejection whose coverage entry is missing (or contradicted), an invalidation recorded but not applied. While any exists no decision is taken (the reader refuses), whether or not
  some process holds the lock: the durable state itself is the witness, and every start completes the work first
  (``resume``; ``emit.complete_pending_invalidations``). A completed invalidation then reads exactly as design 13.2
  says: unchanged for ``D < T3_inv`` (decisions inside ``[T_inv, T3_inv)`` were excluded by the lock its emission
  held), INVALIDATED from ``T3_inv`` on.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_NAME = "run.lock"
_HELD: dict[str, list] = {}                                 # lock path -> [open handle, depth]


class QuiescenceBusy(RuntimeError):
    """Another process holds the adapter run lock, or durable adapter work is unfinished."""


def _acquire(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def run_lock(root: Path) -> Iterator[None]:
    """Hold the adapter run lock of ``root`` (re-entrant within one process; refused if another process holds it)."""

    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    key = str((path / LOCK_NAME).resolve())
    entry = _HELD.get(key)
    if entry is not None:
        entry[1] += 1
    else:
        handle = open(key, "ab")                          # append-only: never truncated or rewritten
        try:
            _acquire(handle)
        except OSError:
            handle.close()
            raise QuiescenceBusy("another adapter phase holds the run lock") from None
        entry = _HELD[key] = [handle, 1]
    try:
        yield
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            del _HELD[key]
            try:
                _release(entry[0])
            finally:
                entry[0].close()


def pending_work(stores) -> tuple[str, ...]:
    """What durable adapter work is unfinished (empty when the stores are quiescent)."""

    from genesis_adapters.errors import AdapterFailure
    from genesis_adapters.oddspapi.acquisition import OPEN_STATES, unsettled_rejections
    from genesis_adapters.oddspapi.derivation import ROLE_ODDS, successful_capture

    found: list[str] = []
    rows = stores.acquisition.rows()
    attempts = stores.acquisition.attempts()
    by_attempt: dict[str, dict[str, dict]] = {}
    last = None
    for row in rows:
        aid = row.get("acquisition_id")
        if aid is not None:
            by_attempt.setdefault(aid, {})[row["record_type"]] = row
            if row["record_type"] == "acq_planned":
                last = aid
    for aid, item in attempts.items():
        if item.state in OPEN_STATES:
            found.append("an acquisition attempt is still open")
        elif item.state == "COMPLETED" and item.role == ROLE_ODDS and successful_capture(by_attempt[aid]):
            found.append("a successful ODDS capture is not normalized yet")
    if last is not None and attempts[last].state in ("COMPLETED", "QUARANTINED"):
        completed = by_attempt[last].get("acq_completed")
        marker = {AdapterFailure.SECRET_ECHO.value: "acq_halted",
                  AdapterFailure.AUTH_REJECTED.value: "acq_circuit_opened"}.get(completed["failure"])
        if marker is not None:
            position = rows.index(completed)
            if not any(row["record_type"] == marker and row.get("reason") == completed["failure"]
                       for row in rows[position + 1:]):
                found.append("a credential verdict's halt or circuit is not recorded yet")
    # a terminal derivation rejection is complete only with its REJECTED coverage entry (hostile audit RA6-001): a crash
    # between the two leaves the gap this reports, which every start closes and which no read may pass over
    missing, conflicting = unsettled_rejections(rows, stores.coverage.log.records)
    if missing:
        found.append("a derivation rejection's coverage entry is not recorded yet")
    if conflicting:
        found.append("a derivation rejection's coverage entry conflicts with its verdict")
    for entry in stores.invalidations.state().values():
        if entry["applied"] is None:
            found.append("an invalidation is recorded but not applied")
    return tuple(dict.fromkeys(found))


@contextmanager
def decision_phase(stores) -> Iterator[None]:
    """The decision runner's side of design 6.3: hold the run lock, and refuse while durable work is unfinished.
    Take the cutoff ``D`` and read the market books inside this block."""

    with run_lock(stores.root):
        unfinished = pending_work(stores)
        if unfinished:
            raise QuiescenceBusy("adapter work is unfinished: " + unfinished[0])
        yield
