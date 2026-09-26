"""T6 F-3: no risk-log write path and no filesystem alias can break replay.

Invariant: no supported or externally reachable risk-log mutation path, and no
filesystem alias accepted as an independent authority, irreversibly mutates a
risk log unless the resulting durable log has first been shown to preserve
replay validity under the correct single-owner locking domain.

* F-3a: every public writer of the risk log (RiskEngine actions, the log
  storage's append and transaction, and RiskAuditLog.append if it exists)
  refuses a row after which the log would not replay. A refused row leaves the
  bytes unchanged, and the log then replays, accepts valid writes and restarts.
  The storage appends nothing without the engine composed over it.
* F-3b: one authority file has one name and one lock. While a hard-linked
  alias of the risk log, or of an owner a risk transaction reads, exists, no
  write reaches the shared bytes through any name, including when the alias
  appears inside an open critical section; a Windows short (8.3) name is
  refused like a file symlink. Removing the alias restores the authority. A
  directory junction or an equivalent path stays the same owner with the
  same lock.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path

from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.risk import Exposure, ExposureState, RiskAuditLog

from ._support import scratch_directory
from .test_astra_t5_owner_binding import admitted, risk_like
from .test_remediation_r5_risk import build_risk, request


MATCHED = ExposureState.MATCHED
SIDECARS = (
    ".owners.jsonl", ".risk-authority.jsonl",
    ".sqlite3", ".sqlite3-journal", ".sqlite3-wal", ".sqlite3-shm",
)


def exposure_row(exposure_id: str, candidate: str, *, schema: str = "risk-exposure-v2") -> dict:
    return {
        "record_type": "risk_exposure_recorded",
        "schema_version": schema,
        **Exposure(exposure_id, candidate, "1", MATCHED).to_dict(),
        "recorded_at": "2026-01-01T00:20:00Z",
    }


class _Disguised(str):
    """Serializes as its text, but hashes and compares as another ID in memory."""

    def __hash__(self):
        return hash("t6-disguised")

    def __eq__(self, other):
        return other is self

    def __ne__(self, other):
        return other is not self


def hard_link_tree(source: Path, target: Path, *, skip: tuple[str, ...] = ()) -> list[Path]:
    """Hard-link a deployment's authority files elsewhere, as the T5 review did."""

    linked = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_dir():
            (target / relative).mkdir(parents=True, exist_ok=True)
        elif not path.name.endswith(SIDECARS) and relative.as_posix() not in skip:
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target / relative)
            linked.append(target / relative)
    return linked


def short_name(path: Path) -> Path | None:
    """The Windows 8.3 alias of an existing file, or None where there is none."""

    if os.name != "nt":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):
        return None
    alias = path.parent / Path(buffer.value).name
    return None if alias.name.lower() == path.name.lower() else alias


def _t6_risk_writer(root: str, writer: str, attempts: int, ready, go, results) -> None:
    from genesis.registry import RegistryConflict
    from genesis.risk import Exposure, ExposureState
    from tests.test_astra_t5_owner_binding import risk_like

    appended: list[int] = []
    refused = 0
    error = None
    try:
        try:
            engine = risk_like(Path(root))
        finally:
            ready.put(writer)  # no alias exists while engines are composed
        go.wait(60)
        for index in range(attempts):
            try:
                engine.record_exposure(
                    Exposure(f"{writer}-{index}", "e" * 64, "1", ExposureState.MATCHED),
                    recorded_at="2026-01-01T00:30:00Z",
                )
                appended.append(index)
            except (RegistryConflict, OSError):
                refused += 1
    except BaseException as exc:  # reported to the test process
        error = repr(exc)
    results.put((writer, appended, refused, error))


def _t6_alias_toggler(real: str, alias: str, cycles: int, go, results) -> None:
    import time

    linked = 0
    error = None
    try:
        go.wait(60)
        for _ in range(cycles):
            try:
                os.link(real, alias)
                linked += 1
            except FileExistsError:
                pass  # a writer created a separate file at the alias name
            time.sleep(0.003)
            for _attempt in range(300):
                try:
                    os.unlink(alias)
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.002)
            time.sleep(0.003)
    except BaseException as exc:  # reported to the test process
        error = repr(exc)
    results.put(("toggler", [linked], 0, error))


class T6RiskLogWriterTests(unittest.TestCase):
    def assert_replay_and_restart_intact(self, engine, root: Path, later_id: str) -> None:
        engine.reserved_exposures()
        engine.record_exposure(
            Exposure(later_id, "c" * 64, "1", MATCHED), recorded_at="2026-01-01T00:30:00Z",
        )
        restarted = risk_like(root)
        self.assertIn(later_id, {item.exposure_id for item in restarted.reserved_exposures()})

    def test_t6_every_public_risk_log_writer_refuses_an_unreplayable_row(self):
        with scratch_directory() as root:
            f = build_risk(root)
            engine = f["engine"]
            decision = engine.approve(request(f))
            self.assertTrue(decision.passed, decision.reason)
            engine.record_exposure(
                Exposure("t6-factual", "e" * 64, "1", MATCHED),
                recorded_at="2026-01-01T00:11:00Z",
            )
            storage = engine.audit_log.log
            before = storage.path.read_bytes()
            rows = {
                # The T5 review's F-3a row: a factual exposure reusing an approval ID.
                "exposure-reuses-approval-id": exposure_row(decision.approval_id, "f" * 64),
                "exposure-reuses-exposure-id": exposure_row("t6-factual", "d" * 64),
                "unsupported-active-schema": exposure_row(
                    "t6-other", "d" * 64, schema="risk-exposure-v9",
                ),
            }
            writers = {
                "audit_log.log.append": storage.append,
                "audit_log.log.transaction": lambda row: storage.transaction(lambda _rows: row),
            }
            generic = getattr(engine.audit_log, "append", None)
            if generic is not None:
                writers["RiskAuditLog.append"] = lambda row: generic(
                    row["record_type"],
                    {key: value for key, value in row.items() if key != "record_type"},
                )
            for writer, write in writers.items():
                for label, row in rows.items():
                    with self.subTest(writer=writer, row=label):
                        with self.assertRaises(
                            RegistryConflict, msg=f"F-3a: {writer} appended {label}",
                        ):
                            write(dict(row))
                        self.assertEqual(storage.path.read_bytes(), before)
            with self.assertRaises(RegistryConflict):
                engine.record_exposure(
                    Exposure(decision.approval_id, "f" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:20:00Z",
                )
            self.assertEqual(storage.path.read_bytes(), before)
            self.assert_replay_and_restart_intact(engine, root, "t6-after-refusal")

    def test_t6_replay_check_covers_the_exact_bytes_every_reader_verifies(self):
        # The replay check must certify the line the append writes, parsed and
        # verified as every later reader reads it, not the in-memory row. An
        # int-keyed mapping hashes in numeric key order but re-reads in text
        # order ('registry record was tampered'); a record's own "sequence"
        # overrides the chain's ('registry sequence is not monotonic'); an ID
        # distinct only in memory re-reads as a duplicate ('duplicate risk
        # exposure identity'), as does a row whose builder edited the history
        # it was handed. Each, once appended, fails every later replay.
        int_keyed = {10: "t6", 9: "t6"}

        def hides_the_seed(rows):
            for row in rows:
                if row.get("exposure_id") == "t6-seed":
                    row["exposure_id"] = "t6-hidden"
            return exposure_row("t6-seed", "d" * 64)

        writes = {
            "record_exposure ID duplicate once read back": (
                lambda f, engine, storage: engine.record_exposure(
                    Exposure(_Disguised("t6-seed"), "d" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:02:00Z",
                )
            ),
            "approve affected_scope": lambda f, engine, storage: engine.approve(
                replace(request(f), affected_scope=int_keyed),
            ),
            "record_exposure affected_scope": lambda f, engine, storage: engine.record_exposure(
                Exposure("t6-x", "d" * 64, "1", MATCHED, affected_scope=int_keyed),
                recorded_at="2026-01-01T00:02:00Z",
            ),
            "record_exposure dependency_group": lambda f, engine, storage: engine.record_exposure(
                Exposure("t6-x", "d" * 64, "1", MATCHED, dependency_group=int_keyed),
                recorded_at="2026-01-01T00:02:00Z",
            ),
            "audit_log.log.append int-keyed field": lambda f, engine, storage: storage.append(
                {**exposure_row("t6-x", "d" * 64), "affected_scope": int_keyed},
            ),
            "audit_log.log.append sequence override": lambda f, engine, storage: storage.append(
                {**exposure_row("t6-x", "d" * 64), "sequence": 99},
            ),
            "audit_log.log.transaction sequence override": (
                lambda f, engine, storage: storage.transaction(
                    lambda _rows: {**exposure_row("t6-x", "d" * 64), "sequence": 99},
                )
            ),
            "audit_log.log.transaction builder edits its history": (
                lambda f, engine, storage: storage.transaction(hides_the_seed)
            ),
        }
        for label, write in writes.items():
            with self.subTest(label), scratch_directory() as root:
                f = build_risk(root)
                engine = f["engine"]
                engine.record_exposure(
                    Exposure("t6-seed", "e" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:01:00Z",
                )
                storage = engine.audit_log.log
                before = storage.path.read_bytes()
                with self.assertRaises(
                    RegistryConflict, msg=f"F-3a: {label} appended a row that fails replay",
                ):
                    write(f, engine, storage)
                self.assertEqual(storage.path.read_bytes(), before)
                self.assertEqual(storage.verify(), 1)
                decision = engine.approve(request(f))
                self.assertTrue(decision.passed, decision.reason)
                self.assert_replay_and_restart_intact(engine, root, "t6-after-refusal")

    def test_t6_risk_log_storage_without_its_engine_appends_nothing(self):
        with scratch_directory() as root:
            fresh = RiskAuditLog(root / "fresh" / "risk.jsonl")
            row = exposure_row("t6-orphan", "e" * 64)
            for write in (
                fresh.log.append,
                lambda value: fresh.log.transaction(lambda _rows: value),
            ):
                with self.assertRaises(RegistryConflict, msg="F-3a: engineless risk log appended"):
                    write(dict(row))
            self.assertFalse(fresh.log.path.exists())

            f = build_risk(root / "bound")
            f["engine"].record_exposure(
                Exposure("t6-seed", "e" * 64, "1", MATCHED), recorded_at="2026-01-01T00:01:00Z",
            )
            second_object = RiskAuditLog(root / "bound" / "risk.jsonl")
            before = second_object.log.path.read_bytes()
            with self.assertRaises(RegistryConflict, msg="F-3a: engineless risk log appended"):
                second_object.log.append(exposure_row("t6-other", "d" * 64))
            self.assertEqual(second_object.log.path.read_bytes(), before)
            self.assertEqual(second_object.verify(), 1)

    def test_t6_valid_engine_writes_commit_and_replay_after_restart(self):
        with scratch_directory() as root:
            f = build_risk(root)
            engine = f["engine"]
            engine.record_exposure(
                Exposure("t6-valid", "e" * 64, "1", MATCHED), recorded_at="2026-01-01T00:05:00Z",
            )
            decision = engine.approve(request(f))
            self.assertTrue(decision.passed, decision.reason)
            consumed = engine.consume_for_order(
                decision.approval_id, order_id="t6-order", consumed_at="2026-01-01T00:11:00Z",
            )
            self.assertEqual(consumed.status, "CONSUMED")
            engine.transition_reservation(
                decision.approval_id, ExposureState.UNKNOWN, occurred_at="2026-01-01T00:12:00Z",
            )
            self.assertEqual(engine.audit_log.verify(), 4)
            restarted = risk_like(root)
            self.assertEqual(
                {item.exposure_id: item.state for item in restarted.reserved_exposures()},
                {"t6-valid": MATCHED, decision.approval_id: ExposureState.UNKNOWN},
            )


class T6HardLinkAliasTests(unittest.TestCase):
    def test_t6_hard_linked_risk_log_alias_mutates_nothing_until_removed(self):
        with scratch_directory() as root:
            real = root / "real"
            f = build_risk(real)
            engine = f["engine"]
            engine.record_exposure(
                Exposure("t6-seed", "e" * 64, "1", MATCHED), recorded_at="2026-01-01T00:01:00Z",
            )
            before = (real / "risk.jsonl").read_bytes()
            linked = hard_link_tree(real, root / "mirror")
            alias = risk_like(root / "mirror")  # opening an alias for reading is allowed
            self.assertFalse(
                admitted(lambda: alias.approve(request(f))),
                "F-3b: a hard-linked alias admitted risk on the shared log",
            )
            for label, write in (
                ("alias record_exposure", lambda: alias.record_exposure(
                    Exposure("t6-alias", "d" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:02:00Z",
                )),
                ("alias storage append", lambda: alias.audit_log.log.append(
                    exposure_row("t6-alias", "d" * 64),
                )),
                ("raw append through the alias name", lambda: AppendOnlyJsonl(
                    root / "mirror" / "risk.jsonl",
                ).append({"record_type": "t6_probe_marker"})),
            ):
                with self.subTest(label):
                    with self.assertRaises(RegistryConflict, msg=f"F-3b: {label} appended"):
                        write()
            # One file, one name: the original name is refused too while the alias exists.
            self.assertFalse(admitted(lambda: engine.approve(request(f))))
            with self.assertRaises(RegistryConflict):
                engine.record_exposure(
                    Exposure("t6-real", "c" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:03:00Z",
                )
            self.assertEqual((real / "risk.jsonl").read_bytes(), before)
            for path in linked:
                path.unlink()
            decision = engine.approve(request(f))
            self.assertTrue(decision.passed, decision.reason)
            restarted = risk_like(real)
            self.assertEqual(
                sorted(item.exposure_id for item in restarted.reserved_exposures()),
                sorted(["t6-seed", decision.approval_id]),
            )

    def test_t6_hard_linked_owners_cannot_serve_a_second_risk_log(self):
        with scratch_directory() as root:
            real = root / "real"
            f = build_risk(real)
            # No risk append yet, so the mirror gets hard-linked bankroll,
            # qualification and output owners and a risk log of its own.
            linked = hard_link_tree(real, root / "mirror")
            self.assertFalse((root / "mirror" / "risk.jsonl").exists())
            second = risk_like(root / "mirror")
            self.assertFalse(
                admitted(lambda: second.approve(request(f))),
                "F-3b: hard-linked exclusive owners served a second risk log",
            )
            self.assertFalse((root / "mirror" / "risk.jsonl").exists())
            for path in linked:
                path.unlink()
            self.assertTrue(f["engine"].approve(request(f)).passed)

    def seeded(self, root: Path):
        f = build_risk(root / "real")
        f["engine"].record_exposure(
            Exposure("t6-seed", "e" * 64, "1", MATCHED), recorded_at="2026-01-01T00:01:00Z",
        )
        return f, root / "real" / "risk.jsonl", root / "alias-risk.jsonl"

    def assert_unchanged(self, risk: Path, before: bytes) -> None:
        self.assertEqual(risk.read_bytes(), before, "F-3b: the shared risk log was mutated")
        self.assertEqual(AppendOnlyJsonl(risk).verify(), 1)

    def test_t6_alias_append_inside_the_real_critical_section_is_refused(self):
        # The T5 review's F-3b shape, through raw storage writers on both names.
        with scratch_directory() as root:
            _f, risk, alias = self.seeded(root)
            before = risk.read_bytes()
            os.link(risk, alias)
            nested: dict[str, str] = {}

            def inside_real(_rows):
                try:
                    AppendOnlyJsonl(alias).append({"record_type": "t6_probe_marker"})
                    nested["alias"] = "appended"
                except RegistryConflict:
                    nested["alias"] = "refused"
                return {"record_type": "t6_probe_marker"}

            with self.assertRaises(RegistryConflict):
                AppendOnlyJsonl(risk).transaction(inside_real)
            self.assertEqual(nested, {"alias": "refused"})
            self.assert_unchanged(risk, before)

    def test_t6_alias_appearing_inside_an_open_engine_transaction_is_refused(self):
        with scratch_directory() as root:
            f, risk, alias = self.seeded(root)
            engine = f["engine"]
            before = risk.read_bytes()
            original = engine._exposures
            nested: dict[str, str] = {}

            def exposures(rows, **kwargs):
                if not alias.exists():
                    os.link(risk, alias)
                    try:
                        AppendOnlyJsonl(alias).append({"record_type": "t6_probe_marker"})
                        nested["alias"] = "appended"
                    except RegistryConflict:
                        nested["alias"] = "refused"
                return original(rows, **kwargs)

            engine._exposures = exposures
            try:
                with self.assertRaises(RegistryConflict):
                    engine.record_exposure(
                        Exposure("t6-real", "c" * 64, "1", MATCHED),
                        recorded_at="2026-01-01T00:02:00Z",
                    )
            finally:
                del engine._exposures
            self.assertEqual(nested, {"alias": "refused"})
            self.assert_unchanged(risk, before)
            alias.unlink()
            engine.record_exposure(
                Exposure("t6-real", "c" * 64, "1", MATCHED), recorded_at="2026-01-01T00:02:00Z",
            )
            self.assertEqual(AppendOnlyJsonl(risk).verify(), 2)

    def test_t6_alias_appearing_inside_its_own_writers_transaction_is_refused(self):
        # The alias name is absent when its writer starts and appears inside
        # that writer's critical section, after the writer read no history.
        with scratch_directory() as root:
            _f, risk, alias = self.seeded(root)
            before = risk.read_bytes()

            def appear(_rows):
                os.link(risk, alias)
                return {"record_type": "t6_probe_marker"}

            with self.assertRaises(RegistryConflict):
                AppendOnlyJsonl(alias).transaction(appear)
            self.assert_unchanged(risk, before)

    def test_t6_hard_linked_owner_of_a_risk_transaction_is_refused(self):
        with scratch_directory() as root:
            f, risk, _alias = self.seeded(root)
            engine = f["engine"]
            before = risk.read_bytes()
            bankroll_alias = root / "bankroll-alias.jsonl"
            os.link(root / "real" / "bankroll.jsonl", bankroll_alias)
            self.assertFalse(
                admitted(lambda: engine.approve(request(f))),
                "F-3b: risk was admitted over a bankroll with a second name",
            )
            self.assert_unchanged(risk, before)
            bankroll_alias.unlink()
            self.assertTrue(engine.approve(request(f)).passed)
            self.assertEqual(AppendOnlyJsonl(risk).verify(), 2)

    def test_t6_short_name_alias_of_the_risk_log_is_refused(self):
        # A Windows 8.3 name is a second name for one file without a second
        # hard link; the lock and owner identity follow the name it is opened by.
        with scratch_directory() as root:
            f, risk, _alias = self.seeded(root)
            engine = f["engine"]
            short = short_name(risk)
            if short is None:
                self.skipTest("no 8.3 short names on this platform or volume")
            before = risk.read_bytes()
            with self.assertRaises(RegistryConflict, msg="F-3b: a short-name writer appended"):
                AppendOnlyJsonl(short).append({"record_type": "t6_probe_marker"})
            aliased = risk_like(root / "real", audit_log=RiskAuditLog(short))
            self.assertFalse(
                admitted(lambda: aliased.approve(request(f))),
                "F-3b: an engine over the short name admitted risk on the shared log",
            )
            with self.assertRaises(RegistryConflict):
                aliased.record_exposure(
                    Exposure("t6-short", "d" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:02:00Z",
                )
            self.assert_unchanged(risk, before)
            original = engine._exposures
            nested: dict[str, str] = {}

            def exposures(rows, **kwargs):
                if not nested:
                    try:
                        AppendOnlyJsonl(short).append({"record_type": "t6_probe_marker"})
                        nested["short"] = "appended"
                    except RegistryConflict:
                        nested["short"] = "refused"
                return original(rows, **kwargs)

            engine._exposures = exposures
            try:
                engine.record_exposure(
                    Exposure("t6-real", "c" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:03:00Z",
                )
            finally:
                del engine._exposures
            self.assertEqual(nested, {"short": "refused"})
            self.assertEqual(
                [row.get("exposure_id") for row in AppendOnlyJsonl(risk).records()],
                ["t6-seed", "t6-real"],
            )

    def test_t6_directory_junction_and_equivalent_path_stay_one_owner_and_one_lock(self):
        with scratch_directory() as root:
            real = root / "real"
            f = build_risk(real)
            equivalent = risk_like(real / ".." / "real")
            self.assertEqual(equivalent.owner_mismatches(), ())
            self.assertTrue(equivalent.approve(request(f)).passed)
            junction = root / "junction"
            if os.name == "nt":
                made = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junction), str(real)],
                    capture_output=True, text=True,
                ).returncode == 0
            else:
                try:
                    os.symlink(real, junction, target_is_directory=True)
                    made = True
                except OSError:
                    made = False
            if not made:
                self.skipTest("this platform cannot create a directory alias")
            try:
                via = risk_like(junction)
                self.assertEqual(via.owner_mismatches(), ())
                self.assertEqual(
                    AppendOnlyJsonl(junction / "risk.jsonl").coordinator_path.resolve(),
                    AppendOnlyJsonl(real / "risk.jsonl").coordinator_path.resolve(),
                )
                via.record_exposure(
                    Exposure("t6-junction", "e" * 64, "1", MATCHED),
                    recorded_at="2026-01-01T00:12:00Z",
                )
                self.assertEqual(AppendOnlyJsonl(real / "risk.jsonl").verify(), 2)
            finally:
                if os.name == "nt":
                    os.rmdir(junction)
                else:
                    os.unlink(junction)

    def test_t6_concurrent_writers_through_a_toggled_hard_link_keep_one_valid_chain(self):
        with scratch_directory() as root:
            real = root / "real"
            f = build_risk(real)
            f["engine"].record_exposure(
                Exposure("t6-seed", "e" * 64, "1", MATCHED), recorded_at="2026-01-01T00:01:00Z",
            )
            mirror = root / "mirror"
            linked = hard_link_tree(real, mirror, skip=("risk.jsonl",))
            alias = mirror / "risk.jsonl"
            context = multiprocessing.get_context("spawn")
            ready, go, results = context.Queue(), context.Event(), context.Queue()
            workers = [
                context.Process(
                    target=_t6_risk_writer, args=(str(where), name, 20, ready, go, results),
                    name=name,
                )
                for where, name in (
                    (real, "real-0"), (real, "real-1"), (mirror, "alias-0"), (mirror, "alias-1"),
                )
            ]
            workers.append(context.Process(
                target=_t6_alias_toggler,
                args=(str(real / "risk.jsonl"), str(alias), 80, go, results),
                name="toggler",
            ))
            outcomes: dict[str, tuple[list[int], int, str | None]] = {}
            for worker in workers:
                worker.start()
            try:
                for _ in workers[:-1]:
                    ready.get(timeout=180)
                go.set()
                for _ in workers:
                    writer, appended, refused, error = results.get(timeout=180)
                    outcomes[writer] = (appended, refused, error)
            finally:
                for worker in workers:
                    worker.join(30)
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(5)
            self.assertEqual(
                {name: outcome[2] for name, outcome in outcomes.items() if outcome[2]}, {},
            )
            self.assertGreater(outcomes["toggler"][0][0], 0, "the alias was never linked")
            if os.path.lexists(alias):
                alias.unlink()
            for path in linked:
                path.unlink()
            expected = {"t6-seed"} | {
                f"{name}-{index}"
                for name, (appended, _refused, _error) in outcomes.items()
                if name.startswith("real-")
                for index in appended
            }
            restarted = risk_like(real)
            self.assertEqual(
                {item.exposure_id for item in restarted.reserved_exposures()}, expected,
                "F-3b: the real risk log holds a row that was not written through its own name",
            )


if __name__ == "__main__":
    unittest.main()
