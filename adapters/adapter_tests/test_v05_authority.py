"""G-01 .. G-04 and CLK-02: gates are checked by code and satisfied only by (synthetic, throwaway) records;
READY is reachable only through the operator CLI after a G3 record. Every record here lives in a scratch
directory and names a ``synthetic-test-only`` reference."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from genesis.time import iso_utc

from genesis_adapters import cli
from genesis_adapters import errors as err
from genesis_adapters.clock import SystemUtcClock
from genesis_adapters.oddspapi import authority as auth
from genesis_adapters.oddspapi.acquisition import AcquisitionLedger, boundary_guard
from genesis_adapters.oddspapi.quota_gate import open_operational_ledger
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from . import static_scan as scan
from .pipeline_support import approve, odds_item, odds_response, open_rt
from .support import CONFIG, SENTINEL_KEY, FakeTransport, FixedClock, read_jsonl, scratch_root, status

LIMITS = auth.load_gate_limits(CONFIG)
FINGERPRINT = Secret(SENTINEL_KEY).fingerprint
SYNCED = {"synchronized": True, "method": "test", "source": "test"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def common(gate: str, granted: datetime) -> dict:
    return {"record_type": "gate_record", "schema_version": auth.SCHEMA_VERSION, "gate": gate,
            "approval_reference": f"adr:synthetic-test-only-{gate.lower()}", "approver": "synthetic-test-only",
            "granted_at": iso_utc(granted)}


def g1(granted: datetime, *, fingerprint: str = FINGERPRINT, days: int = 1) -> dict:
    return {**common("G1", granted), "terms_snapshot_sha256": "0" * 64,
            "licensing_note": "FIXTURE-ONLY-NO-PROVIDER-TERMS", "credential_fingerprint": fingerprint,
            "credential_path_policy": "outside-repo-and-root; owner-only",
            "valid_through": iso_utc(granted + timedelta(days=days))}


def g2(granted: datetime, hashes, *, hours: int = 12) -> dict:
    return {**common("G2", granted), "request_hashes": list(hashes), "max_calls": len(hashes),
            "valid_from": iso_utc(granted), "valid_through": iso_utc(granted + timedelta(hours=hours))}


def g2r(granted: datetime, *, derivation: str, policy: str, days: int = 30) -> dict:
    return {**common("G2R", granted), "derivation_version": derivation, "policy_digest": policy,
            "plan_digest": "1" * 64, "valid_from": iso_utc(granted), "valid_through": iso_utc(granted + timedelta(days=days))}


def g3(granted: datetime, *, derivation: str, source: str, contract: str) -> dict:
    return {**common("G3", granted), "derivation_version": derivation, "source_id": source, "contract_id": contract,
            "review_reference": "adr:synthetic-test-only-review",
            "acceptance_evidence": {f"AC-{n}": "2" * 64 for n in range(1, 10)},
            "unobserved_paths_accepted": [],
            "observation_window": {"from": iso_utc(granted - timedelta(days=15)), "to": iso_utc(granted)}}


class GateLimitPinTests(unittest.TestCase):
    """R-2 (hostile audit F-02; design 16.3/16.4, oracle FZ-12/GT-02): the gate bounds are architecture-fixed, so
    configuration can neither relax nor otherwise change them. The file's SHA-256 is pinned in code exactly like
    the frozen-module manifest's; any other bytes are refused when the limits are loaded."""

    SHIPPED = CONFIG / auth.GATE_LIMITS_FILE

    def edited(self, base: Path, text: str) -> Path:
        folder = base / "config"
        folder.mkdir(exist_ok=True)
        (folder / auth.GATE_LIMITS_FILE).write_bytes(text.encode("utf-8"))
        return folder

    def test_r2_the_shipped_file_holds_exactly_the_design_16_3_and_16_4_bounds(self):
        limits = auth.load_gate_limits(CONFIG)
        # design 16.3: a G2 record pins at most 5 requests inside a window of at most 72 hours;
        # design 16.4: a G2R record covers at most 35 days
        self.assertEqual((limits.g2_requests_cap, limits.g2_window_hours, limits.g2r_window_days), (5, 72, 35))

    def test_r2_the_pinned_digest_is_the_digest_of_the_shipped_file(self):
        self.assertEqual(hashlib.sha256(self.SHIPPED.read_bytes()).hexdigest(), auth.GATE_LIMITS_SHA256)

    def test_r2_a_relaxed_tightened_or_reformatted_file_is_refused_at_load(self):
        body = json.loads(self.SHIPPED.read_text(encoding="utf-8"))
        variants = {
            "one more request": {**body, "g2_requests_cap": 6},
            "far more requests": {**body, "g2_requests_cap": 10000},
            "longer G2 window": {**body, "g2_window_hours": 73},
            "far longer G2 window": {**body, "g2_window_hours": 87600},
            "longer G2R window": {**body, "g2r_window_days": 36},
            "far longer G2R window": {**body, "g2r_window_days": 3650},
            "tighter (still not the pinned file)": {**body, "g2_requests_cap": 4},
        }
        texts = {label: json.dumps(value, sort_keys=True, indent=2) + "\n" for label, value in variants.items()}
        texts["the same values, reformatted"] = json.dumps(body, indent=4)
        texts["the same values, trailing space"] = self.SHIPPED.read_text(encoding="utf-8") + " "
        for label, text in texts.items():
            with self.subTest(label), scratch_root() as base:
                with self.assertRaises(auth.AuthorityRecordInvalid):
                    auth.load_gate_limits(self.edited(base, text))

    def test_r2_the_operator_cli_cannot_be_pointed_at_relaxed_limits(self):
        from .pipeline_support import copy_config
        body = json.loads(self.SHIPPED.read_text(encoding="utf-8"))
        with scratch_root() as base:
            config_dir = copy_config(base)
            (config_dir / auth.GATE_LIMITS_FILE).write_text(json.dumps({**body, "g2_requests_cap": 50}),
                                                            encoding="utf-8")
            record_path = base / "g2.json"
            granted = now_utc()
            record_path.write_text(json.dumps(g2(granted, [f"{n:064x}" for n in range(50)])), encoding="utf-8")
            args = SimpleNamespace(config=str(config_dir), root=str(base / "runtime"), record=str(record_path))
            with self.assertRaises(auth.AuthorityRecordInvalid):
                cli.cmd_approve(args, prompt=lambda _: cli.CONFIRMATION_PHRASE)
            self.assertFalse((base / "runtime" / "authority.jsonl").exists())    # nothing was approved
            plan = base / "plan.json"
            plan.write_text("[]", encoding="utf-8")
            run_args = SimpleNamespace(config=str(config_dir), root=str(base / "runtime"), plan=str(plan), mode="G2")
            with self.assertRaises(auth.AuthorityRecordInvalid):
                cli.cmd_run(run_args)


class RecordTests(unittest.TestCase):
    def test_records_are_closed_and_bounded(self):
        start = now_utc()
        auth.validate_record(g1(start), LIMITS)
        capped = [f"{n:064x}" for n in range(LIMITS.g2_requests_cap)]
        at_the_bounds = (g2(start, capped, hours=LIMITS.g2_window_hours),
                         g2r(start, derivation="mb1-x", policy="b" * 64, days=LIMITS.g2r_window_days))
        for record in at_the_bounds:                                           # exactly at a bound is allowed
            auth.validate_record(record, LIMITS)
        bad = {
            "unknown gate": {**g1(start), "gate": "G9"},
            "extra key": {**g1(start), "surprise": 1},
            "G1 window empty": g1(start, days=0),
            "G2 too many requests": g2(start, [f"{n:064x}" for n in range(LIMITS.g2_requests_cap + 1)]),
            "G2 window too long": g2(start, ["a" * 64], hours=LIMITS.g2_window_hours + 1),
            "G2 calls differ": {**g2(start, ["a" * 64]), "max_calls": 2},
            "G2R window too long": g2r(start, derivation="mb1-x", policy="b" * 64, days=LIMITS.g2r_window_days + 1),
            "G3 missing evidence": {**g3(start, derivation="d", source="s", contract="c"), "acceptance_evidence": {}},
            "no approver": {**g1(start), "approver": " "},
        }
        for label, record in bad.items():
            with self.subTest(label), self.assertRaises(auth.AuthorityRecordInvalid):
                auth.validate_record(record, LIMITS)

    def test_only_the_operator_cli_can_reach_the_gate_ledger_or_write_ready(self):
        for rel, source in scan.package_files():
            if rel in (scan.CLI_MODULE, "oddspapi/authority.py"):
                continue
            self.assertNotIn("AdapterAuthorityLedger", source, rel)          # runtime code only gets a LiveGate
        self.assertEqual(scan.scan_all(scan.scan_frz08), [])                   # READY appears only in cli.py


class LiveGateTests(unittest.TestCase):
    """G-01, G-02, CLK-02 through the real live runner path (fake transport, real clock and quota policy)."""

    def setUp(self):
        if not boundary_guard(iso_utc(now_utc()), ps.POLICY).permitted:
            self.skipTest("the real UTC clock is inside the day/month boundary guard zone")

    def live_runtime(self, root, records, *, mode=auth.MODE_VERIFICATION, attestation=SYNCED, transport=None,
                     clock=None, fingerprint=FINGERPRINT, quota=None):
        ledger = auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS)
        for record in records:
            ledger.append(record)
        quota_ledger, cache = quota or open_operational_ledger(root)
        rt = None

        def gate(config):
            return auth.LiveGate(ledger, mode=mode, credential_fingerprint=fingerprint,
                                 derivation_version=config.derivation_version, policy_digest=config.policy.digest,
                                 attestation=attestation,
                                 sent_count=auth.sent_counter(AcquisitionLedger(root / "acquisition.jsonl")))

        from genesis_adapters.config import load_adapter_config
        from genesis_adapters.oddspapi import normalize
        config = load_adapter_config(CONFIG, allow_fixture_only=True, code_version=normalize.CODE_VERSION)
        rt = open_rt(root, live=True, clock=clock or SystemUtcClock(drift_max_ms=1000), quota_ledger=quota_ledger,
                     cache=cache, authority=gate(config), secret=Secret(SENTINEL_KEY),
                     transport=transport or FakeTransport([odds_response()] * 4))
        return rt

    def refused(self, rt, item=None):
        outcome = rt.runner.acquire(item or odds_item())
        self.assertEqual((outcome.outcome, outcome.failure), ("REFUSED", err.AdapterFailure.GATE_MISSING))
        self.assertEqual(rt.runner.transport.calls, [])
        return [r for r in read_jsonl(rt.root / "acquisition.jsonl") if r["record_type"] == "acq_refused"][-1]

    def test_g01_without_every_gate_element_nothing_is_sent(self):
        start = now_utc() - timedelta(hours=1)
        pinned = odds_item().request.provider_request_hash
        cases = {
            "no records": ([], "G1"),
            "no G2": ([g1(start)], "G2"),
            "G1 for another key": ([g1(start, fingerprint="0" * 12), g2(start, [pinned])], "G1"),
            "expired G1": ([g1(start - timedelta(days=3), days=1), g2(start, [pinned])], "G1"),
        }
        for label, (records, missing) in cases.items():
            with self.subTest(label), scratch_root() as root:
                row = self.refused(self.live_runtime(root, records))
                self.assertEqual(row["detail"], missing)
        with scratch_root() as root:                                   # CLK-02: no time-sync attestation
            row = self.refused(self.live_runtime(root, [g1(start), g2(start, [pinned])], attestation=None))
            self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")
        with scratch_root() as root:
            row = self.refused(self.live_runtime(root, [g1(start), g2(start, [pinned])],
                                                 attestation={"synchronized": False}))
            self.assertEqual(row["detail"], "TIME_SYNC_ATTESTATION")

    def test_g02_only_pinned_requests_at_most_max_calls_inside_the_window(self):
        start = now_utc() - timedelta(hours=1)
        pinned = odds_item().request.provider_request_hash
        with scratch_root() as root:
            rt = self.live_runtime(root, [g1(start), g2(start, [pinned])])
            other = odds_item(tournaments=(17,))
            self.refused(rt, other)                                    # not pinned
            first = rt.runner.acquire(odds_item("w1"))
            self.assertIsNone(first.failure)
            self.assertEqual(len(rt.runner.transport.calls), 1)
            again = rt.runner.acquire(odds_item("w2"))                   # max_calls reached
            self.assertEqual((again.outcome, again.failure), ("REFUSED", err.AdapterFailure.GATE_MISSING))
            self.assertEqual(len(rt.runner.transport.calls), 1)
        with scratch_root() as root:                                   # outside the window
            late = now_utc() - timedelta(hours=20)
            self.refused(self.live_runtime(root, [g1(start), g2(late, [pinned], hours=12)]))
        soon = iso_utc(now_utc() + timedelta(hours=1))
        for label, record in (("window not yet open", {**g2(start, [pinned]), "valid_from": soon}),
                              ("granted in the future", {**g2(start, [pinned]), "granted_at": soon})):
            with self.subTest(label), scratch_root() as root:
                self.assertEqual(self.refused(self.live_runtime(root, [g1(start), record]))["detail"], "G2")

    def test_g2r_must_pin_the_running_derivation_and_policy(self):
        start = now_utc() - timedelta(hours=1)
        with scratch_root() as root:
            rt = self.live_runtime(root, [g1(start), g2r(start, derivation="mb1-0000000000000000", policy="c" * 64)],
                                   mode=auth.MODE_RECURRING)
            self.refused(rt)
        with scratch_root() as root:
            probe = open_rt(root / "probe")
            running = {"derivation": probe.config.derivation_version, "policy": probe.config.policy.digest}
            for label, pins in (("other derivation", {**running, "derivation": "mb1-0000000000000000"}),
                                ("other policy", {**running, "policy": "c" * 64})):
                with self.subTest(label):                              # each pin is checked on its own
                    self.refused(self.live_runtime(root / label.replace(" ", "-"), [g1(start), g2r(start, **pins)],
                                                   mode=auth.MODE_RECURRING))
            rt = self.live_runtime(root / "live", [g1(start), g2r(start, **running)], mode=auth.MODE_RECURRING)
            self.assertIsNone(rt.runner.acquire(odds_item()).failure)

    def test_sent_counter_counts_only_sends_of_the_given_requests_since_the_window_opened(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock("2026-09-01T12:00:00.000000Z", step_micros=1000))
            item = odds_item("w1")
            self.assertIsNone(rt.runner.acquire(item).failure)
            count = auth.sent_counter(AcquisitionLedger(root / "acquisition.jsonl"))
            pinned = item.request.provider_request_hash
            self.assertEqual(count([pinned], "2026-09-01T11:00:00.000000Z"), 1)
            self.assertEqual(count([pinned], "2026-09-01T12:00:01.000000Z"), 0)      # sent before this window
            self.assertEqual(count(["0" * 64], "2026-09-01T11:00:00.000000Z"), 0)    # another request

    def test_clk02_a_live_runner_refuses_a_test_clock_and_a_test_quota_policy(self):
        start = now_utc() - timedelta(hours=1)
        pinned = odds_item().request.provider_request_hash
        with scratch_root() as root:
            rt = self.live_runtime(root, [g1(start), g2(start, [pinned])], clock=FixedClock(iso_utc(now_utc())))
            self.assertEqual(rt.runner.acquire(odds_item()).failure, err.AdapterFailure.LIVE_CLOCK_REQUIRED)
        with scratch_root() as root:
            from genesis.quota import QuotaLedger, VerifiedCacheStore
            from .support import test_quota_policy
            cache = VerifiedCacheStore(root / "quota" / "cache")
            ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=test_quota_policy(), allow_test_policy=True,
                                 cache_store=cache)
            rt = self.live_runtime(root, [g1(start), g2(start, [pinned])], quota=(ledger, cache))
            self.assertEqual(rt.runner.acquire(odds_item()).failure, err.AdapterFailure.TEST_POLICY_IN_LIVE)


class CapabilityGateTests(unittest.TestCase):
    def setUp(self):
        self.out, self.err = io.StringIO(), io.StringIO()          # the operator CLI's messages, asserted below
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(self.out))
        stack.enter_context(contextlib.redirect_stderr(self.err))
        self.addCleanup(stack.close)

    def test_g04_auth_rejection_blocks_every_market_book_source(self):
        from .emit_support import approve_source, with_version
        with scratch_root() as root:
            rt = open_rt(root, script=[status(403, b"forbidden")])
            approve(rt)
            other = with_version(rt.stores, "mb1-" + "4" * 16)
            approve_source(other, at="2026-09-30T00:00:01.000000Z")
            self.assertEqual(rt.acquire(odds_item()).outcome.failure, err.AdapterFailure.AUTH_REJECTED)
            for source in (rt.stores.source_id, other.source_id):
                self.assertFalse(rt.stores.capabilities.history(source)[-1].is_ready(), source)
            self.assertEqual(rt.acquire(odds_item("w2")).outcome.failure, err.AdapterFailure.CIRCUIT_OPEN)

    def ready_args(self, root, rt):
        # no time argument: READY is recorded at the trusted clock's reading (design 16.5, hostile audit P:HA-013)
        return SimpleNamespace(config=None, root=str(root), derivation_version=rt.config.derivation_version,
                               source_id=rt.stores.source_id, contract_id=rt.stores.contract_id, cost_tier="fixture")

    def test_g03_ready_only_through_the_operator_cli_after_a_g3_record(self):
        with scratch_root() as root:
            rt = open_rt(root)
            args = self.ready_args(root, rt)
            self.assertEqual(cli.cmd_approve_ready(args, prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_REFUSED)
            ledger = auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS)
            ledger.append(g3(now_utc() - timedelta(minutes=1), derivation=rt.config.derivation_version,
                             source=rt.stores.source_id, contract=rt.stores.contract_id))
            self.assertEqual(cli.cmd_approve_ready(args, prompt=lambda _: "yes"), cli.EXIT_REFUSED)   # wrong phrase
            self.assertEqual(cli.cmd_approve_ready(args), cli.EXIT_REFUSED)                          # no terminal
            self.assertEqual(rt.stores.capabilities.history(rt.stores.source_id), ())
            self.assertEqual(cli.cmd_approve_ready(args, prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_OK)
            head = rt.stores.capabilities.history(rt.stores.source_id)[-1]
            self.assertTrue(head.is_ready())
            self.assertEqual(head.version, rt.config.derivation_version + "-ready-1")
            self.assertEqual(self.out.getvalue(), "ready\n")
            self.assertEqual(self.err.getvalue().count("refused: "), 3)

    def test_only_an_interactive_operator_reset_clears_a_durable_circuit(self):
        with scratch_root() as root:
            rt = open_rt(root, clock=FixedClock("2026-09-01T12:00:00.000000Z", step_micros=1000),
                         script=[status(401, b"no")])
            self.assertEqual(rt.runner.acquire(odds_item("w1")).failure, err.AdapterFailure.AUTH_REJECTED)
            args = SimpleNamespace(config=None, root=str(root), approval_reference="adr:synthetic-test-only-reset",
                                   reason="key rotated; new G1 recorded")
            self.assertEqual(cli.cmd_reset(args), cli.EXIT_REFUSED)                                   # no terminal
            self.assertEqual(cli.cmd_reset(SimpleNamespace(**{**vars(args), "approval_reference": "because"}),
                                           prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_REFUSED)
            rt.clock.set("2026-09-01T13:00:00.000000Z")
            self.assertEqual(rt.runner.acquire(odds_item("w2")).failure, err.AdapterFailure.CIRCUIT_OPEN)
            # an AUTH_REJECTED circuit is cleared only after a human re-approves: a G1 record granted after it
            # (design 14.3, hostile audit P:HA-014)
            auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).append(g1(now_utc()))
            self.assertEqual(cli.cmd_reset(args, prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_OK)
            rt.clock.set(iso_utc(now_utc() + timedelta(hours=1)))
            self.assertNotEqual(rt.runner.acquire(odds_item("w3")).failure, err.AdapterFailure.CIRCUIT_OPEN)
            resets = [r for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_operator_reset"]
            self.assertEqual([r["approval_reference"] for r in resets], ["adr:synthetic-test-only-reset"])
            self.assertEqual(self.out.getvalue(), "reset\n")
            self.assertEqual(self.err.getvalue().count("refused: "), 2)

    def test_approve_refuses_without_a_terminal_a_phrase_or_an_out_of_band_reference(self):
        with scratch_root() as root:
            record_path = root / "g1.json"
            record = g1(now_utc())
            record_path.write_text(json.dumps(record), encoding="utf-8")
            args = SimpleNamespace(config=None, root=str(root), record=str(record_path))
            self.assertEqual(cli.cmd_approve(args), cli.EXIT_REFUSED)                                 # no TTY
            self.assertEqual(cli.cmd_approve(args, prompt=lambda _: "ok"), cli.EXIT_REFUSED)
            record_path.write_text(json.dumps({**record, "approval_reference": "trust me"}), encoding="utf-8")
            self.assertEqual(cli.cmd_approve(args, prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_REFUSED)
            self.assertFalse((root / "authority.jsonl").exists())
            record_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(cli.cmd_approve(args, prompt=lambda _: cli.CONFIRMATION_PHRASE), cli.EXIT_OK)
            self.assertEqual(len(auth.AdapterAuthorityLedger(root / "authority.jsonl", limits=LIMITS).records()), 1)
            self.assertEqual(self.out.getvalue(), "approved\n")
            self.assertEqual(self.err.getvalue().count("refused: "), 3)


if __name__ == "__main__":
    unittest.main()
