"""R5 - operator times and security halts (parallel hostile audit ccr-c8695f69-sghhe5: P:HA-013, P:HA-014).

P:HA-013 (design 16.2, 16.4, 16.5; 13.1/13.2: history at earlier cutoffs never changes): a gate record's
    ``granted_at`` and a READY row's ``recorded_at`` are the trusted clock's readings at approval, never times chosen
    by the operator; a G2R run anchors the source's capability timeline with UNKNOWN. So a capture made before an
    approval is not usable at any cutoff before that approval - before / at / after the approval cutoff.
P:HA-014 (design 7.6, 14.3): an operator reset clears a SECRET_ECHO halt only after a G1 record for a rotated key
    granted after the halt, and an AUTH_REJECTED circuit only after a G1 record granted after it; other halts reset as
    before, and a CLOCK_SKEW suspension never (R3).

The CLI's trusted clock is the real ``SystemUtcClock`` with every check intact, reading a fixed wall time, so these
cases are deterministic and independent of the day they run.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from genesis.pit import OperationalStatus
from genesis.registry import RegistryConflict
from genesis.time import iso_utc, parse_utc

from genesis_adapters import cli
from genesis_adapters import clock as clock_mod
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import authority as auth
from genesis_adapters.oddspapi import capability
from genesis_adapters.oddspapi.reader import UsableBook
from genesis_adapters.secrets import Secret

from .pipeline_support import odds_item, odds_response, open_rt, pit_rows
from .support import CONFIG, SENTINEL_KEY, FixedClock, ok, read_jsonl, scratch_root, status
from .test_v05_authority import g1, g3

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
LIMITS = auth.load_gate_limits(CONFIG)
CAPTURE = "2026-10-01T12:00:00.000000Z"
APPROVAL = "2026-10-01T12:10:00.000000Z"


@contextlib.contextmanager
def trusted_clock_at(moment: str):
    """The CLI's ``SystemUtcClock`` - the real class, drift, monotonic and floor checks intact - reading ``moment``."""

    wall = (parse_utc(moment) - EPOCH) // timedelta(microseconds=1) * 1000
    real = clock_mod.SystemUtcClock

    def factory(**kwargs):
        return real(wall_ns=lambda: wall, mono_ns=lambda: 0, **kwargs)

    with mock.patch.object(clock_mod, "SystemUtcClock", factory):
        yield


class Quiet(unittest.TestCase):
    def setUp(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(self.out))
        stack.enter_context(contextlib.redirect_stderr(self.err))
        self.addCleanup(stack.close)


# ---------------------------------------------------------------------------------------------------------
class OperatorTimeTests(Quiet):
    def approve(self, root, record: dict) -> int:
        path = root / "record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return cli.cmd_approve(SimpleNamespace(config=None, root=str(root), record=str(path)),
                               prompt=lambda _: cli.CONFIRMATION_PHRASE)

    def test_p013_approve_stamps_granted_at_with_the_trusted_clock_and_refuses_a_chosen_one(self):
        with scratch_root() as root, trusted_clock_at(APPROVAL):
            backdated = g1(datetime(2000, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(self.approve(root, backdated), cli.EXIT_REFUSED)
            self.assertFalse((root / "authority.jsonl").exists())
            for label, stated in (("three minutes late", iso_utc(parse_utc(APPROVAL) + timedelta(minutes=3))),
                                  ("not a time", "yesterday")):
                with self.subTest(label):
                    record = dict(g1(parse_utc(APPROVAL)), granted_at=stated)
                    self.assertEqual(self.approve(root, record), cli.EXIT_REFUSED)
            self.assertEqual(self.approve(root, {k: v for k, v in g1(parse_utc(APPROVAL)).items()
                                                 if k != "granted_at"}), cli.EXIT_OK)
            self.assertEqual(self.approve(root, dict(g1(parse_utc(APPROVAL)),
                                                     granted_at=iso_utc(parse_utc(APPROVAL) - timedelta(seconds=30)))),
                             cli.EXIT_OK)                                  # within the skew bound: still restamped
            stored = auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).records("G1")
            self.assertEqual([row["granted_at"] for row in stored], [APPROVAL, APPROVAL])

    def test_p013_approve_refuses_while_the_trusted_clock_is_behind_the_authority_ledger(self):
        with scratch_root() as root:
            auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).append(
                g1(parse_utc(APPROVAL) + timedelta(hours=1)))             # granted later than the clock now reads
            before = read_jsonl(root / "authority.jsonl")
            with trusted_clock_at(APPROVAL):
                code = self.approve(root, {k: v for k, v in g1(parse_utc(APPROVAL)).items() if k != "granted_at"})
            self.assertEqual(code, cli.EXIT_REFUSED)
            self.assertEqual(read_jsonl(root / "authority.jsonl"), before)

    def test_p013_ready_needs_a_g3_granted_at_or_before_the_trusted_reading(self):
        for label, granted, expected in (
                ("G3 granted after the reading", parse_utc(APPROVAL) + timedelta(microseconds=1), cli.EXIT_REFUSED),
                ("G3 granted at the reading", parse_utc(APPROVAL), cli.EXIT_OK),
                ("G3 granted before the reading", parse_utc(APPROVAL) - timedelta(seconds=1), cli.EXIT_OK)):
            with self.subTest(label), scratch_root() as root:
                rt = open_rt(root, clock=FixedClock(CAPTURE, step_micros=1000))
                auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).append(
                    g3(granted, derivation=rt.config.derivation_version, source=rt.stores.source_id,
                       contract=rt.stores.contract_id))
                self.assertEqual(self.ready(root, rt, APPROVAL), expected)
                history = rt.stores.capabilities.history(rt.stores.source_id)
                if expected == cli.EXIT_OK:
                    self.assertEqual([(row.operational_status, iso_utc(row.recorded_at)) for row in history],
                                     [(OperationalStatus.READY, APPROVAL)])
                else:
                    self.assertEqual(list(history), [])                     # nothing was recorded

    def test_p013_approve_ready_takes_no_operator_time(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            cli._parser().parse_args(["approve-ready", "--root", "r", "--at", CAPTURE, "--derivation-version", "d",
                                      "--source-id", "s", "--contract-id", "c", "--cost-tier", "t"])

    def ready(self, root, rt, moment: str) -> int:
        # ``at`` is the operator-chosen time the old command recorded READY at (a back-dated capture time here); the
        # command no longer has that option, and the attribute must change nothing
        args = SimpleNamespace(config=None, root=str(root), derivation_version=rt.config.derivation_version,
                               source_id=rt.stores.source_id, contract_id=rt.stores.contract_id, cost_tier="fixture",
                               at=CAPTURE)
        with trusted_clock_at(moment):
            return cli.cmd_approve_ready(args, prompt=lambda _: cli.CONFIRMATION_PHRASE)

    def test_p013_a_capture_made_before_the_approval_is_not_usable_at_any_cutoff_before_it(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(CAPTURE, step_micros=1000), script=[odds_response()])
            rt.acquire(odds_item())
            ledger = auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS)
            ledger.append(g3(parse_utc(APPROVAL) - timedelta(minutes=1), derivation=rt.config.derivation_version,
                             source=rt.stores.source_id, contract=rt.stores.contract_id))
            self.assertEqual(self.ready(root, rt, APPROVAL), cli.EXIT_OK)
            head = rt.stores.capabilities.history(rt.stores.source_id)[-1]
            self.assertEqual((head.operational_status, iso_utc(head.recorded_at)), (OperationalStatus.READY, APPROVAL))
            row = pit_rows(rt)[0]
            reader = rt.reader()
            for label, cutoff, usable in (("before", iso_utc(parse_utc(row["ready_at"]) + timedelta(seconds=1)), False),
                                          ("just before", iso_utc(parse_utc(APPROVAL) - timedelta(microseconds=1)),
                                           False),
                                          ("at", APPROVAL, True),
                                          ("after", iso_utc(parse_utc(APPROVAL) + timedelta(seconds=1)), True)):
                with self.subTest(label):
                    verdict = reader.head(row["entity_id"], cutoff)
                    if usable:
                        self.assertIsInstance(verdict, UsableBook)
                    else:
                        self.assertEqual(verdict.code, err.AdapterFailure.DATA_CAPABILITY_NOT_READY)

    def test_p013_ready_is_never_recorded_before_the_sources_latest_capability_row(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(CAPTURE, step_micros=1000))
            capability.anchor_unknown(rt.stores.capabilities, rt.stores.source_id, at=APPROVAL, reason="G2R_START")
            auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).append(
                g3(parse_utc(CAPTURE), derivation=rt.config.derivation_version, source=rt.stores.source_id,
                   contract=rt.stores.contract_id))
            self.assertEqual(self.ready(root, rt, CAPTURE), cli.EXIT_REFUSED)   # the trusted clock is behind it
            self.assertEqual(rt.stores.capabilities.history(rt.stores.source_id)[-1].operational_status,
                             OperationalStatus.UNKNOWN)

    def test_p013_a_g2r_cli_start_anchors_the_running_source_unknown_once(self):
        import os

        from genesis_adapters import config as config_mod
        from genesis_adapters.oddspapi import transport_http as th

        from .test_v05_tx01 import prepare
        real_load = config_mod.load_adapter_config

        def fixture_config(config_dir, **kwargs):                       # test-side: the repository maps are fixtures
            return real_load(config_dir, **{**kwargs, "allow_fixture_only": True})

        class NoSend(th.HttpsTransport):
            def send(self, request, **kw):
                raise AssertionError("no send expected")

        synchronized = {"synchronized": True, "method": "test", "source": "test"}
        with scratch_root() as base:
            root, plan, env = prepare(base)
            plan.write_text("[]", encoding="utf-8")
            args = SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2R")
            with mock.patch.object(config_mod, "load_adapter_config", fixture_config), \
                    mock.patch.object(th, "HttpsTransport", NoSend), \
                    mock.patch.object(cli, "time_sync_attestation", lambda: synchronized), \
                    mock.patch.dict(os.environ, {"GENESIS_ODDSPAPI_CREDENTIAL_FILE":
                                                 env["GENESIS_ODDSPAPI_CREDENTIAL_FILE"]}):
                self.assertEqual(cli.cmd_run(args), cli.EXIT_OK)
                first = read_jsonl(root / "capabilities.jsonl")
                self.assertEqual(cli.cmd_run(args), cli.EXIT_OK)                  # a second start adds nothing
            self.assertEqual(read_jsonl(root / "capabilities.jsonl"), first)
            statuses = [json.dumps(row, sort_keys=True) for row in first]
            self.assertEqual(len(statuses), 1, statuses)
            self.assertIn(f'"{OperationalStatus.UNKNOWN.value}"', statuses[0])
            self.assertNotIn(f'"{OperationalStatus.READY.value}"', statuses[0])

    def test_p013_a_recurring_run_anchors_the_capability_timeline_unknown(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(CAPTURE, step_micros=1000))
            stores = rt.stores
            self.assertTrue(capability.anchor_unknown(stores.capabilities, stores.source_id, at=CAPTURE,
                                                      reason="G2R_START"))
            self.assertFalse(capability.anchor_unknown(stores.capabilities, stores.source_id, at=APPROVAL,
                                                       reason="G2R_START"))      # once: an existing row stays
            self.assertEqual([row.operational_status for row in stores.capabilities.history(stores.source_id)],
                             [OperationalStatus.UNKNOWN])
            from .emit_support import source_capability
            earlier = source_capability(stores, status=OperationalStatus.READY,
                                        at=iso_utc(parse_utc(CAPTURE) - timedelta(seconds=1)), suffix="backdated")
            with self.assertRaises(RegistryConflict):                     # nothing can be recorded before the anchor
                stores.capabilities.register(earlier)


# ---------------------------------------------------------------------------------------------------------
class SecurityResetTests(Quiet):
    HALT = "2026-09-01T12:00:00.000000Z"                                 # the run, before the operator's day

    def reset(self, root, moment="2026-09-01T15:00:00.000000Z") -> int:
        args = SimpleNamespace(config=None, root=str(root), approval_reference="adr:synthetic-test-only-reset",
                               reason="the cause was fixed")
        with trusted_clock_at(moment):
            return cli.cmd_reset(args, prompt=lambda _: cli.CONFIRMATION_PHRASE)

    def grant(self, root, at: str, fingerprint: str) -> None:
        auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).append(
            g1(parse_utc(at), fingerprint=fingerprint))

    def resets(self, root) -> int:
        return len([r for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_operator_reset"])

    def test_p014_a_secret_echo_halt_is_cleared_only_after_a_g1_for_a_rotated_key(self):
        echo = b'[{"note": "' + SENTINEL_KEY.encode("ascii") + b'"}]'
        old, new = Secret(SENTINEL_KEY).fingerprint, Secret("ROTATED-" + SENTINEL_KEY).fingerprint
        with scratch_root() as root:
            self.grant(root, "2026-09-01T11:00:00.000000Z", old)                  # the key in force at the halt
            rt = open_rt(root, clock=FixedClock(self.HALT, step_micros=1000),
                         script=[ok(echo, headers=(("content-type", "application/json"),))], secret=Secret(SENTINEL_KEY))
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            self.assertEqual(self.reset(root), cli.EXIT_REFUSED)                 # no new G1 at all
            self.grant(root, "2026-09-01T13:00:00.000000Z", old)                  # re-approved, same (echoed) key
            self.assertEqual(self.reset(root), cli.EXIT_REFUSED)
            self.assertEqual(self.resets(root), 0)
            self.grant(root, "2026-09-01T14:00:00.000000Z", new)                  # a rotated key, approved after
            self.assertEqual(self.reset(root), cli.EXIT_OK)
            self.assertEqual(self.resets(root), 1)

    def test_p014_no_key_approved_before_the_halt_counts_as_rotated(self):
        # two keys were approved before the halt and no send records which one echoed: re-approving either is not a
        # rotation, whichever was approved last (the latest G1 need not be the key that echoed)
        echo = b'[{"note": "' + SENTINEL_KEY.encode("ascii") + b'"}]'
        echoed, spare = Secret(SENTINEL_KEY).fingerprint, Secret("SPARE-" + SENTINEL_KEY).fingerprint
        new = Secret("ROTATED-" + SENTINEL_KEY).fingerprint
        with scratch_root() as root:
            self.grant(root, "2026-09-01T10:00:00.000000Z", echoed)
            self.grant(root, "2026-09-01T11:00:00.000000Z", spare)
            rt = open_rt(root, clock=FixedClock(self.HALT, step_micros=1000),
                         script=[ok(echo, headers=(("content-type", "application/json"),))], secret=Secret(SENTINEL_KEY))
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            for moment, fingerprint in (("2026-09-01T13:00:00.000000Z", echoed), ("2026-09-01T13:30:00.000000Z", spare)):
                self.grant(root, moment, fingerprint)
                self.assertEqual(self.reset(root), cli.EXIT_REFUSED)
            self.assertEqual(self.resets(root), 0)
            self.grant(root, "2026-09-01T14:00:00.000000Z", new)
            self.assertEqual(self.reset(root), cli.EXIT_OK)

    def test_p014_an_auth_rejection_is_cleared_only_after_a_new_g1(self):
        fingerprint = Secret(SENTINEL_KEY).fingerprint
        with scratch_root() as root:
            self.grant(root, "2026-09-01T11:00:00.000000Z", fingerprint)
            rt = open_rt(root, clock=FixedClock(self.HALT, step_micros=1000), script=[status(401, b"no")])
            self.assertEqual(rt.runner.acquire(odds_item("w1")).failure, err.AdapterFailure.AUTH_REJECTED)
            self.assertEqual(self.reset(root), cli.EXIT_REFUSED)
            self.grant(root, "2026-09-01T13:00:00.000000Z", fingerprint)          # a human re-approves (G1 re-check)
            self.assertEqual(self.reset(root), cli.EXIT_OK)

    def test_p014_other_halts_reset_as_before(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock(self.HALT, step_micros=1000), script=[status(503)])
            rt.runner.acquire(odds_item("w1"))
            from genesis_adapters.oddspapi.acquisition import AcquisitionLedger
            AcquisitionLedger(root / "acquisition.jsonl").append("acq_halted", recorded_at="2026-09-01T12:30:00.000000Z",
                                                                 reason=err.AdapterFailure.QUOTA_DIVERGENCE.value)
            self.assertEqual(self.reset(root), cli.EXIT_OK)                       # no G1 needed for this one


if __name__ == "__main__":
    unittest.main()
