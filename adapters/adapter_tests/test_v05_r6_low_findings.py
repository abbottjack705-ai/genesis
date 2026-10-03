"""R6 secondary findings: the LOW items of the R5 hostile re-audit that could be closed narrowly, and the survivors of
the audit's independent mutation list (RA5-012). Each class names the finding it pins and the plausible one-line
weakenings it kills (the mutation transcripts are in ``evidence/R6/MUTATION.txt``).

* RA5-008 ``OperationalBookmakerCeilingTests``      the operational policy declares one to three bookmakers
* RA5-011 ``UnreadableUsageHeaderTests``            a present but unreadable usage header is uncertainty, not absence
* RA5-009 ``VerifyDerivationMetadataTests``         no observation field passes the derivation verifier by omission
* RA5-005 ``ClockFaultInsideAnAttemptTests``        a clock fault anywhere in an attempt is a durable CLOCK_FAULT halt
* RA5-006 ``TrailingNewlineGrammarTests``           every identifier grammar ends in ``\\Z`` (``$`` admits a final LF)
* RA5-007 ``CredentialGrammarTests``                the credential loader accepts printable ASCII without a space only
* RA5-012 survivors: ``GateWindowBoundaryTests`` (M35, M46), ``SecretFormTests`` (M26, M27, M28),
  ``CredentialModeTests`` (M30), ``ExactSizeBodyTests`` (M22), ``QuarantineMetadataScanTests`` (M40) and
  ``UnpinnedScopeTests`` (the R3 survivor that was labelled equivalent and is not)

RA5-013 (a test that patched the global ``os.lstat``) is repaired in ``test_v05_credential.py``; the audit's M03/M04
(transport branches rewritten by RA5-004) and M07/M08/M09 (runner deadline) are in ``test_v05_r6_deadline.py``; M37 is
``VerifyDerivationMetadataTests``.
"""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import os
import shutil
import sys
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from genesis.provenance import AvailabilityClass

from genesis_adapters import config as cfg
from genesis_adapters import errors as err
from genesis_adapters import ids, jsonstrict
from genesis_adapters import schema as sch
from genesis_adapters.clock import ClockFault
from genesis_adapters.credential import ENV_VAR, CredentialSource
from genesis_adapters.oddspapi import authority as auth
from genesis_adapters.oddspapi import derivation, emit
from genesis_adapters.oddspapi import endpoints as ep
from genesis_adapters.oddspapi import invalidation as inv
from genesis_adapters.oddspapi import maps as maps_mod
from genesis_adapters.oddspapi import normalize, parser
from genesis_adapters.oddspapi import scope as scope_mod
from genesis_adapters.oddspapi.derivation import DerivationError
from genesis_adapters.oddspapi.transport import TransportResult
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from .parser_support import policy_with
from .pipeline_support import (
    JSON, acquisition_rows, approve, coverage_rows, fixture_body, meta_item, odds_item, odds_response, open_rt,
    pit_rows, reopen,
)
from .support import CONFIG, REPO, SENTINEL_KEY, Crash, FixedClock, ok, read_jsonl, scratch_root
from .test_v05_authority import FINGERPRINT as G1_FINGERPRINT
from .test_v05_authority import LIMITS as GATE_LIMITS
from .test_v05_authority import g1, g2
from .test_v05_credential import restrict
from .test_v05_r2_transport_boundary import CaptureFixture
from .test_v05_r2_transport_boundary import request as capture_request

A = err.AdapterFailure
USAGE = "x-requests-used"

POLICY_NAME = cfg.POLICY_FILE
MAP_FILES = ("oddspapi_v4_identity_map.json", "oddspapi_v4_market_map.json")


def _clear_fixture_flags(node) -> None:
    if isinstance(node, dict):
        for key in list(node):
            if key == "fixture_only":
                node[key] = False
            else:
                _clear_fixture_flags(node[key])
    elif isinstance(node, list):
        for item in node:
            _clear_fixture_flags(item)


def operational_config(root: Path, **policy_changes) -> Path:
    """A copy of the committed configuration with no fixture-only entry, so that only the policy under test can make the
    operational loader refuse it."""

    dest = root / "config"
    shutil.copytree(CONFIG, dest)
    for name in MAP_FILES:
        path = dest / name
        document = json.loads(path.read_text(encoding="utf-8"))
        _clear_fixture_flags(document)
        path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    policy_path = dest / POLICY_NAME
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.update(policy_changes)
    policy_path.write_text(json.dumps(policy, indent=1), encoding="utf-8")
    return dest


class OperationalBookmakerCeilingTests(unittest.TestCase):
    """RA5-008 / design 8.4 / MKT-02: the operational policy declares one to three bookmakers, and a policy edit cannot
    widen that. Killed: removing the check; ``> 3`` read as ``> 4``; ``in (1, 2, 3)`` read as ``in (1, 2)`` or as
    ``in (1, 2, 3, 4)``; applying the check to one loader mode only."""

    def test_the_control_loads_in_both_modes(self):
        with scratch_root() as root:
            config = operational_config(root)
            self.assertEqual(cfg.load_adapter_config(config).policy.declared_bookmakers_max, 3)
            self.assertEqual(cfg.load_adapter_config(config, allow_fixture_only=True).policy.declared_bookmakers_max, 3)

    def test_a_policy_above_the_architecture_limit_is_refused_by_the_operational_loader(self):
        for value in (4, 5, 50, 10 ** 9):
            with self.subTest(declared_bookmakers_max=value), scratch_root() as root:
                config = operational_config(root, declared_bookmakers_max=value)
                with self.assertRaises(cfg.PolicyError):
                    cfg.load_adapter_config(config)

    def test_the_verification_mode_loader_refuses_it_too(self):
        # the audit's own reproduction loaded the widened policy with ``allow_fixture_only=True``
        for value in (4, 50):
            with self.subTest(declared_bookmakers_max=value), scratch_root() as root:
                config = operational_config(root, declared_bookmakers_max=value)
                with self.assertRaises(cfg.PolicyError):
                    cfg.load_adapter_config(config, allow_fixture_only=True)

    def test_the_committed_fixture_configuration_cannot_be_widened_either(self):
        with scratch_root() as root:
            config = root / "config"
            shutil.copytree(CONFIG, config)
            policy = json.loads((config / POLICY_NAME).read_text(encoding="utf-8"))
            policy["declared_bookmakers_max"] = 50
            (config / POLICY_NAME).write_text(json.dumps(policy, indent=1), encoding="utf-8")
            with self.assertRaises(cfg.PolicyError):
                cfg.load_adapter_config(config, allow_fixture_only=True)

    def test_every_count_the_architecture_permits_loads(self):
        for value in (1, 2, 3):
            with self.subTest(declared_bookmakers_max=value), scratch_root() as root:
                config = operational_config(root, declared_bookmakers_max=value)
                self.assertEqual(cfg.load_adapter_config(config).policy.declared_bookmakers_max, value)

    def test_the_refusal_names_no_provider_text_and_changes_nothing_on_disk(self):
        with scratch_root() as root:
            config = operational_config(root, declared_bookmakers_max=50)
            before = sorted(p.name for p in config.iterdir())
            with self.assertRaises(cfg.PolicyError) as caught:
                cfg.load_adapter_config(config)
            self.assertIn("declared_bookmakers_max", str(caught.exception))
            self.assertEqual(sorted(p.name for p in config.iterdir()), before)

    def test_a_test_only_policy_still_declares_more_than_the_operational_limit(self):
        # MKT-02: five bookmakers normalize under a test-only policy; the ceiling is a property of the loaded
        # configuration, not of the structural policy validator
        policy = policy_with(declared_bookmakers_max=5)
        self.assertEqual(policy.declared_bookmakers_max, 5)

    def test_the_ceiling_is_architecture_fixed_not_a_policy_field(self):
        # it must not be satisfiable by editing the digested policy: there is no policy field naming it
        names = {field for field in cfg.SlicePolicy.__dataclass_fields__}
        self.assertNotIn("operational_declared_bookmakers_max", names)
        self.assertEqual(tuple(cfg.OPERATIONAL_DECLARED_BOOKMAKERS), (1, 2, 3))

    def test_the_maps_loader_still_refuses_a_declared_exchange_at_any_ceiling(self):
        # the other half of "1-3 bookmakers, all fixed_odds_sportsbook": enforced where the maps are loaded, which the
        # runtime does before it sends anything
        identity = copy.deepcopy(json.loads((CONFIG / "oddspapi_v4_identity_map.json").read_text(encoding="utf-8")))
        for entry in identity["bookmakers"]:
            if entry["kind"] != maps_mod.KIND_SPORTSBOOK:
                entry["declared"] = True
        market = json.loads((CONFIG / "oddspapi_v4_market_map.json").read_text(encoding="utf-8"))
        status = json.loads((CONFIG / "oddspapi_v4_status_map.json").read_text(encoding="utf-8"))
        for ceiling in (3, 50):
            with self.subTest(ceiling=ceiling), self.assertRaises(maps_mod.MapError):
                maps_mod.load_maps(identity, market, status, declared_bookmakers_max=ceiling)


def usage_headers(*values, name: str = USAGE):
    return JSON + tuple((name, value) for value in values)


class UnreadableUsageHeaderTests(unittest.TestCase):
    """RA5-011 / design 14.2, 15 F-37, 21 A12: a usage header that is present but cannot be read is uncertainty about
    the budget, not absence, so it halts like a divergence does. Killed: ``reported is None`` dropped from the halt
    condition; presence judged from the kept headers only (a value too long to keep reads as absent); only the first of
    several occurrences judged; the header name compared case-sensitively."""

    UNREADABLE = {
        "scientific": "1e5", "thousands": "99,999", "negative": "-5", "plus": "+5", "fullwidth": "\uff19\uff19",
        "arabic_indic": "\u0663", "with_unit": "99999 units", "hex": "0x1869F", "decimal_point": "1.5",
        "empty": "", "blank": "   ", "underscore": "1_000", "word": "unlimited", "nul": "1\x00", "tab_inside": "1\t1",
        "superscript": "\u00b2", "over_the_kept_length": "9" * 300, "huge": "9" * 5000,
        # non-ASCII digits that ``int()`` itself would read as a figure within the debit (so only the ASCII rule rejects)
        "fullwidth_one": "\uff11", "arabic_indic_zero": "\u0660",
    }

    @contextlib.contextmanager
    def halted_by(self, headers):
        """The runtime after one acquisition that must halt, and the halt (the scratch root lives for the block)."""

        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=headers)])
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(odds_item("w1"))
            yield rt, caught.exception

    def test_every_unreadable_value_halts_as_a_quota_divergence(self):
        for label, value in self.UNREADABLE.items():
            with self.subTest(label), self.halted_by(usage_headers(value)) as (rt, halt):
                self.assertEqual(halt.code, A.QUOTA_DIVERGENCE)
                rows = acquisition_rows(rt)
                self.assertEqual([r["reason"] for r in rows if r["record_type"] == "acq_halted"],
                                 [A.QUOTA_DIVERGENCE.value])

    def test_the_completed_row_records_a_present_but_unreadable_header_apart_from_an_absent_one(self):
        with self.halted_by(usage_headers("not a number")) as (rt, _):
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual(completed[0]["provider_reported_usage"],
                             {"header": USAGE, "reported": None, "genesis_debited": 1, "window": "utc_month"})
            self.assertIsNone(completed[0]["failure"])                      # the response itself passed its checks

    def test_the_halt_is_one_coverage_entry_the_evidence_is_kept_and_nothing_is_lost_or_rewritten(self):
        with self.halted_by(usage_headers("1e5")) as (rt, _):
            notes = [(r["note"], r["status"], tuple(r["reason_codes"])) for r in coverage_rows(rt)
                     if r["note"] == "QUOTA_DIVERGENCE"]
            self.assertEqual(notes, [("QUOTA_DIVERGENCE", "not_attempted", ("configuration_mismatch",))])
            self.assertEqual(sum(1 for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"
                                 and r["raw_observation_id"] is not None), 1)  # raw evidence stays as published
            self.assertEqual(pit_rows(rt), [])                              # nothing was derived during the halt

    def test_the_halt_blocks_every_later_send_and_survives_a_restart(self):
        with self.halted_by(usage_headers("1e5")) as (rt, _):
            restarted = reopen(rt, script=[odds_response(headers=usage_headers("1"))])
            restarted.runner.reconcile_after_restart()
            halts = [r for r in acquisition_rows(restarted) if r["record_type"] == "acq_halted"]
            self.assertEqual([h["reason"] for h in halts], [A.QUOTA_DIVERGENCE.value])
            outcome = restarted.runner.acquire(odds_item("w2"))
            self.assertEqual((outcome.failure, outcome.detail), (A.CIRCUIT_OPEN, A.QUOTA_DIVERGENCE.value))
            self.assertEqual(restarted.runner.transport.calls, [])

    def test_a_crash_between_the_completed_row_and_the_halt_still_halts_after_restart(self):
        with scratch_root() as root:
            def crash_after_completed(step):
                if step == "after_completed":
                    raise Crash()
            rt = open_rt(root, script=[odds_response(headers=usage_headers("1e5"))],
                         runner_checkpoint=crash_after_completed)
            with self.assertRaises(Crash):
                rt.acquire(odds_item("w1"))
            self.assertEqual([r for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"], [])
            restarted = reopen(rt, script=[odds_response(headers=usage_headers("1"))])
            restarted.runner.settle_last()
            self.assertEqual([r["reason"] for r in acquisition_rows(restarted) if r["record_type"] == "acq_halted"],
                             [A.QUOTA_DIVERGENCE.value])
            restarted.runner.settle_last()                                    # idempotent
            self.assertEqual(sum(1 for r in acquisition_rows(restarted) if r["record_type"] == "acq_halted"), 1)

    def test_readable_figures_up_to_the_genesis_debit_are_accepted(self):
        for value in ("0", "1", " 1 ", "01", "\t1\t"):
            with self.subTest(value=value), scratch_root() as root:
                rt = open_rt(root, script=[odds_response(headers=usage_headers(value))])
                outcome = rt.acquire(odds_item("w1")).outcome
                self.assertIsNone(outcome.failure)
                self.assertEqual([r for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"], [])

    def test_a_readable_figure_above_the_debit_still_halts(self):
        for value in ("2", "99999", "9" * 200):
            with self.subTest(value=value[:12]), self.halted_by(usage_headers(value)) as (_, halt):
                self.assertEqual(halt.code, A.QUOTA_DIVERGENCE)

    def test_a_secret_echoed_in_the_usage_header_is_only_a_secret_echo(self):
        # the usage figure is read only from a capture that was stored clean: a quarantined one halts for the key
        # alone, records no usage, and leaves no trace of the value (design 7.6)
        from genesis_adapters.secrets import Secret
        from .support import SENTINEL_KEY

        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=usage_headers(SENTINEL_KEY))], secret=Secret(SENTINEL_KEY))
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.acquire(odds_item("w1"))
            self.assertEqual(caught.exception.code, A.SECRET_ECHO)
            rows = acquisition_rows(rt)
            self.assertEqual([r["reason"] for r in rows if r["record_type"] == "acq_halted"], [A.SECRET_ECHO.value])
            completed = [r for r in rows if r["record_type"] == "acq_completed"]
            self.assertEqual((completed[0]["failure"], completed[0]["provider_reported_usage"]),
                             (A.SECRET_ECHO.value, None))

    def test_an_absent_header_is_nothing_to_reconcile(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=JSON)])
            self.assertIsNone(rt.acquire(odds_item("w1")).outcome.failure)
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertIsNone(completed[0]["provider_reported_usage"])

    def test_every_occurrence_is_judged_not_only_the_first(self):
        for label, values in (("later_figure_above_debit", ("1", "99999")), ("later_unreadable", ("1", "oops")),
                              ("first_unreadable", ("oops", "1")), ("first_above_debit", ("99999", "1"))):
            with self.subTest(label), self.halted_by(usage_headers(*values)) as (_, halt):
                self.assertEqual(halt.code, A.QUOTA_DIVERGENCE)

    def test_repeated_readable_figures_within_the_debit_are_accepted(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=usage_headers("1", "1"))])
            self.assertIsNone(rt.acquire(odds_item("w1")).outcome.failure)
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual(completed[0]["provider_reported_usage"]["reported"], 1)

    def test_the_header_name_is_matched_without_regard_to_case(self):
        for name in ("X-Requests-Used", "X-REQUESTS-USED", "x-Requests-used"):
            with self.subTest(name), self.halted_by(usage_headers("oops", name=name)) as (_, halt):
                self.assertEqual(halt.code, A.QUOTA_DIVERGENCE)


class VerifyDerivationMetadataTests(unittest.TestCase):
    """RA5-009 / design 11.3, 11.5 (and the M37 survivor of RA5-012): an observation that carries the byte-identical
    normalized document but any altered metadata is not that derivation. Killed: dropping ``upstream_version`` or
    ``content_type`` (the two fields that passed by omission), or ``valid_to``, ``publisher_timestamp``, any one of the
    three times or the source URI, from the comparison. (``parser_version``, ``provider``, ``source_type`` and the
    licensing note are pinned by the source contract, which the evidence layer enforces at publish, so an altered one
    cannot be published at all: dropping ``parser_version`` from the comparison is an equivalent mutant.)"""

    def base(self, root):
        rt = open_rt(root, script=[odds_response()])
        rt.acquire(odds_item())
        approve(rt)
        row = pit_rows(rt)[0]
        data = rt.stores.evidence.get_bytes(row["payload_hash"])
        obs = next(o for o in rt.stores.evidence.get_observations(row["payload_hash"])
                   if o.contract_id == rt.stores.contract_id)
        return rt, data, obs

    @staticmethod
    def fields_of(obs) -> dict:
        return dict(contract_id=obs.contract_id, source_uri=obs.source_uri, provider=obs.provider,
                    source_type=obs.source_type, retrieved_at=obs.retrieved_at, first_seen_at=obs.first_seen_at,
                    publisher_timestamp=obs.publisher_timestamp, valid_from=obs.valid_from, valid_to=obs.valid_to,
                    upstream_version=obs.upstream_version, parser_version=obs.parser_version,
                    content_type=obs.content_type, licensing_note=obs.licensing_note,
                    availability_class=AvailabilityClass.DERIVED)

    def alterations(self, obs) -> dict:
        earlier = ps.iso_add(obs.retrieved_at, seconds=-3600)
        return {
            "upstream_version": dict(upstream_version="v5"),
            "content_type": dict(content_type="application/x-evil"),
            "valid_to_ten_days_later": dict(valid_to=ps.iso_add(obs.valid_to, seconds=864000)),
            "valid_to_removed": dict(valid_to=None),
            "publisher_timestamp": dict(publisher_timestamp="2026-10-01T11:00:00.000000Z"),
            "all_three_times_one_hour_earlier": dict(retrieved_at=earlier, first_seen_at=earlier, valid_from=earlier),
            # one time at a time (the evidence layer lets only these through: first_seen_at cannot follow retrieved_at)
            "retrieved_at_one_second_later": dict(retrieved_at=ps.iso_add(obs.retrieved_at, seconds=1)),
            "first_seen_at_one_hour_earlier": dict(first_seen_at=earlier),
            "valid_from_one_hour_earlier": dict(valid_from=earlier),
            "valid_from_one_hour_later": dict(valid_from=ps.iso_add(obs.valid_from, seconds=3600)),
            "source_uri": dict(source_uri=obs.source_uri + "x"),
        }

    def test_the_control_verifies(self):
        with scratch_root() as root:
            rt, _, obs = self.base(root)
            rt.verify_derivation(obs.observation_id)
            self.assertEqual(rt.verify_all(), len(pit_rows(rt)))     # every normalized document, none skipped

    def test_every_alteration_of_the_observation_metadata_is_rejected(self):
        with scratch_root() as root:
            rt, data, obs = self.base(root)
            for label, change in self.alterations(obs).items():
                with self.subTest(label):
                    altered = dict(self.fields_of(obs), **change)
                    published = rt.stores.evidence.publish(
                        data, parse_ready_at=ps.iso_add(obs.parse_ready_at, seconds=1), **altered)
                    self.assertNotEqual(published.observation_id, obs.observation_id)
                    with self.assertRaises(DerivationError):
                        rt.verify_derivation(published.observation_id)

    def test_verify_all_covers_an_altered_observation_that_has_no_pit_record(self):
        # G3 AC-1: every observation under the contract, including one nothing refers to
        with scratch_root() as root:
            rt, data, obs = self.base(root)
            altered = dict(self.fields_of(obs), upstream_version="v5")
            rt.stores.evidence.publish(data, parse_ready_at=ps.iso_add(obs.parse_ready_at, seconds=1), **altered)
            with self.assertRaises(DerivationError):
                rt.verify_all()


class FaultingClock:
    """A settable clock that raises ``ClockFault`` on exactly one numbered read, counted from ``arm``."""

    def __init__(self):
        self.inner = FixedClock("2026-10-01T12:00:00.000000Z", step_micros=1000)
        self.fault_at: int | None = None
        self.reads = 0

    def arm(self, fault_at: int | None) -> None:
        self.fault_at, self.reads = fault_at, 0

    def now(self) -> str:
        self.reads += 1
        if self.reads == self.fault_at:
            raise ClockFault("simulated clock fault")
        return self.inner.now()

    def advance(self, **kw) -> None:
        self.inner.advance(**kw)

    def peek(self) -> str:
        return self.inner.peek()


class ClockFaultInsideAnAttemptTests(unittest.TestCase):
    """RA5-005 / design 6.4, 15 F-03: a clock fault anywhere inside an attempt ends in the durable CLOCK_FAULT halt, never
    in a raw exception that leaves a debit with no verdict and no halt row. Killed: either unguarded read (after the
    quota reservation, before the send) left unguarded, or the replay-broken halt stamped with a raw clock read.

    Every attempt here is the second one of its runtime: the first leaves a durable timestamp, which is what a halt row
    is stamped with when the clock itself cannot be read (an empty ledger has none, and then nothing can be recorded -
    the pre-existing, deliberate rule of ``_halt``)."""

    def run_attempt(self, fault_at):
        with scratch_root() as root:
            clock = FaultingClock()
            rt = open_rt(root, script=[odds_response(), odds_response()], clock=clock)
            rt.runner.acquire(odds_item("w0"))
            clock.advance(seconds=600)
            clock.arm(fault_at)
            halt = None
            try:
                rt.runner.acquire(odds_item("w1"))
            except err.AcquisitionHalt as caught:
                halt = caught
            reads = clock.reads
            rows = acquisition_rows(rt)
            sent = [r for r in rows if r["record_type"] == "acq_sent"]
            calls = rt.runner.transport.calls
            self.assertEqual(len(calls), len(sent), "a send without its durable sent row")
            if halt is not None:
                self.assertEqual(halt.code, A.CLOCK_FAULT)
                reasons = [r["reason"] for r in rows if r["record_type"] in ("acq_halted", "acq_refused")]
                self.assertIn(A.CLOCK_FAULT.value, reasons, "a halt that left no durable row")
                if len(sent) == 1:                                  # nothing but the first attempt was ever sent
                    self.assertEqual(len(calls), 1)
                restarted = reopen(rt, script=[odds_response()])
                restarted.runner.reconcile_after_restart()
                attempts = restarted.runner.ledger.attempts()
                self.assertEqual([a for a in attempts.values() if a.state in ("PLANNED", "DECIDED", "SENT")], [])
                again = restarted.runner.acquire(odds_item("w2"))
                self.assertEqual((again.failure, again.detail), (A.CIRCUIT_OPEN, A.CLOCK_FAULT.value))
                self.assertEqual(restarted.runner.transport.calls, [])
            return halt, reads, len(sent)

    def test_every_read_index_of_an_attempt(self):
        with scratch_root() as root:
            clock = FaultingClock()
            rt = open_rt(root, script=[odds_response(), odds_response()], clock=clock)
            rt.runner.acquire(odds_item("w0"))
            clock.advance(seconds=600)
            clock.arm(None)
            rt.runner.acquire(odds_item("w1"))
            total = clock.reads
        self.assertGreaterEqual(total, 6)                           # the sweep must cover the whole attempt
        halted = []
        for index in range(1, total + 1):
            with self.subTest(fault_at_read=index):
                halt, _, _ = self.run_attempt(index)
                if halt is not None:
                    halted.append(index)
        # only the stamp of the completed row (``_safe_stamp``) degrades to the durable floor instead of halting
        self.assertEqual(halted, list(range(1, total)))

    def test_a_clock_fault_while_halting_for_a_broken_quota_replay_keeps_that_halt(self):
        # the halt for an altered cache object is stamped from the clock too; a fault there must not replace it with a
        # raw exception (the more serious halt is the one that is recorded)
        with scratch_root() as root:
            clock = FaultingClock()
            body = fixture_body("tournaments.json")
            rt = open_rt(root, script=[ok(body, headers=JSON)], clock=clock)
            rt.runner.acquire(meta_item(window="m1"))
            self.assertEqual(rt.runner.acquire(meta_item(window="m2")).outcome, "CACHE_HIT")
            for path in (root / "quota" / "cache").rglob("*"):
                if path.is_file() and path.read_bytes() == body:
                    path.write_bytes(b"altered")
            clock.advance(seconds=600)
            clock.arm(2)                                            # Tq is read 1; the halt's stamp is read 2
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rt.runner.acquire(meta_item(window="m3"))
            self.assertEqual(caught.exception.code, A.QUOTA_REPLAY_BROKEN)
            self.assertEqual([r["reason"] for r in acquisition_rows(rt) if r["record_type"] == "acq_halted"],
                             [A.QUOTA_REPLAY_BROKEN.value])

    def test_a_fault_before_the_send_sends_nothing(self):
        for index in (1, 2, 3):                                     # Tq, the quota decision's stamp, T0
            with self.subTest(fault_at_read=index):
                halt, _, sent = self.run_attempt(index)
                self.assertIsNotNone(halt)
                self.assertEqual(sent, 1)                           # only w0 was ever sent


def load_json(name: str):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


class TrailingNewlineGrammarTests(unittest.TestCase):
    """RA5-006 / design 8.1, 7.3: ``$`` also matches just before a final line feed, so a value such as ``abc\n`` used to
    pass every ``^...$`` grammar (and a provider ``fixtureId`` of ``id1\n`` became an event apart from ``id1``). Every
    grammar now ends in ``\\Z``. Killed: any one of them reverted to ``$``."""

    NEWLINE = "\n"

    def test_native_ids_and_identity_kinds(self):
        self.assertEqual(ids.native_id("abc", declared_type="str"), {"native_type": "str", "value": "abc"})
        with self.assertRaises(ids.IdentityTypeError):
            ids.native_id("abc" + self.NEWLINE, declared_type="str")
        self.assertTrue(ids.gid("book", part=1).startswith("book:"))
        with self.assertRaises(ids.IdentityError):
            ids.gid("book" + self.NEWLINE, part=1)

    def test_request_values(self):
        spec = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json",
                                 cfg.load_policy(CONFIG / cfg.POLICY_FILE))["ODDS"]
        ep.build_request(spec, bookmaker=["pinnacle"], tournamentIds=[17], oddsFormat="decimal")
        for params in ({"bookmaker": ["pinnacle" + self.NEWLINE], "tournamentIds": [17], "oddsFormat": "decimal"},
                       {"bookmaker": ["pinnacle"], "tournamentIds": [17], "oddsFormat": "decimal" + self.NEWLINE}):
            with self.subTest(params=params), self.assertRaises(ep.RequestError):
                ep.build_request(spec, **params)

    def test_request_dates(self):
        spec = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json",
                                 cfg.load_policy(CONFIG / cfg.POLICY_FILE))["FIXTURES"]
        base = {"from": "2026-10-01", "to": "2026-10-08", "sportId": 10, "tournamentIds": [17]}
        ep.build_request(spec, **base)
        with self.assertRaises(ep.RequestError):
            ep.build_request(spec, **dict(base, to="2026-10-08" + self.NEWLINE))

    def test_endpoint_specifications(self):
        policy = cfg.load_policy(CONFIG / cfg.POLICY_FILE)
        body = load_json("oddspapi_v4_endpoints.json")
        ep.parse_endpoints(copy.deepcopy(body), policy)
        host = copy.deepcopy(body)
        host["endpoints"][0]["host"] += self.NEWLINE
        param = copy.deepcopy(body)
        next(e for e in param["endpoints"] if e["params"])["params"][0]["name"] += self.NEWLINE
        for label, document in (("host", host), ("param name", param)):
            with self.subTest(label), self.assertRaises(ep.SpecError):
                ep.parse_endpoints(document, policy)

    def maps_documents(self):
        return (copy.deepcopy(load_json("oddspapi_v4_identity_map.json")),
                copy.deepcopy(load_json("oddspapi_v4_market_map.json")),
                copy.deepcopy(load_json("oddspapi_v4_status_map.json")))

    def test_the_maps(self):
        identity, market, status = self.maps_documents()
        maps_mod.load_maps(identity, market, status, declared_bookmakers_max=3)
        tampers = {
            "provider bookmaker key": lambda i, m: i["bookmakers"][0].update(
                provider_bookmaker_key=i["bookmakers"][0]["provider_bookmaker_key"] + self.NEWLINE),
            "genesis bookmaker id": lambda i, m: i["bookmakers"][0].update(
                genesis_bookmaker_id=i["bookmakers"][0]["genesis_bookmaker_id"] + self.NEWLINE),
            "genesis competition id": lambda i, m: i["competitions"][0].update(
                genesis_competition_id=i["competitions"][0]["genesis_competition_id"] + self.NEWLINE),
            # a line read from an outcome field: with ``$`` this exact tamper was a valid, loadable market
            "line source": lambda i, m: m["markets"][1].update(line_source=m["markets"][1]["line_source"] + self.NEWLINE),
            "outcome id": lambda i, m: m["markets"][0].update(
                outcomes={key + self.NEWLINE: value for key, value in m["markets"][0]["outcomes"].items()}),
            "declared str native id": lambda i, m: i.update(provider_sport={
                "native_type": "str", "provider_sport_id": "10" + self.NEWLINE, "sport": "soccer"}),
        }
        for label, tamper in tampers.items():
            with self.subTest(label):
                identity, market, status = self.maps_documents()
                tamper(identity, market)
                with self.assertRaises(maps_mod.MapError):
                    maps_mod.load_maps(identity, market, status, declared_bookmakers_max=3)

    def test_response_schema_map_keys(self):
        schema = sch.load_closed_schema("tiny", {
            "root": {"type": "array", "ref": "event"},
            "objects": {"event": {"scope": "EVENT", "keys": {
                "books": {"type": "object_map", "ref": "book", "required": True}}},
                        "book": {"scope": "EVENT_BOOKMAKER", "keys": {"active": {"type": "bool", "required": True}}}}})
        self.assertEqual(sch.validate_closed([{"books": {"b1": {"active": True}}}], schema), ())
        findings = sch.validate_closed([{"books": {"b1" + self.NEWLINE: {"active": True}}}], schema)
        self.assertEqual([finding.kind for finding in findings], ["UNKNOWN_KEY"])

    def test_policy_schedule_strings(self):
        body = load_json(cfg.POLICY_FILE)
        cfg.parse_policy(copy.deepcopy(body))
        inventory = copy.deepcopy(body)
        inventory["schedule_inventory_utc"] += self.NEWLINE
        days = copy.deepcopy(body)
        days["schedule_fixtures_days_utc"] = [days["schedule_fixtures_days_utc"][0] + self.NEWLINE]
        for label, document in (("inventory time", inventory), ("fixtures day", days)):
            with self.subTest(label), self.assertRaises(cfg.PolicyError):
                cfg.parse_policy(document)

    def test_invalidation_digests(self):
        def row(artifact):
            return inv.recorded_row(
                invalidated_observation_id="a" * 64, invalidated_artifact_hash=artifact,
                invalidated_pit_record_id="pit:" + "c" * 64, entity_id="book:" + "d" * 64, source_id="s",
                invalidation_class="OPERATOR", reason="OPERATOR_INVALIDATION", recorded_at="2026-10-01T12:00:00.000000Z",
                actor="OPERATOR", evidence_refs=["x"])
        inv.replay([row("b" * 64)])
        with self.assertRaises(inv.InvalidationLedgerInvalid):
            inv.replay([row("b" * 64 + self.NEWLINE)])

    def test_a_response_header_name_with_a_line_feed_is_never_kept(self):
        # the allowlist is a grammar on names too: ``x-requests-used\n`` is not ``x-requests-used``
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=JSON + (("x-requests-used" + self.NEWLINE, "1"),
                                                                     ("x-ratelimit-remaining" + self.NEWLINE, "9")))])
            self.assertIsNone(rt.acquire(odds_item("w1")).outcome.failure)
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual([name for name, _ in completed[0]["headers"]], ["content-type"])
            self.assertIsNone(completed[0]["provider_reported_usage"])

    def test_a_header_name_with_a_line_feed_is_not_listed_in_a_quarantine_record(self):
        from genesis_adapters.secrets import Secret

        with scratch_root() as root:
            headers = JSON + (("x-ok", "1"), ("x-bad" + self.NEWLINE, "1"))
            rt = open_rt(root, script=[ok(SENTINEL_KEY.encode(), headers=headers)], secret=Secret(SENTINEL_KEY))
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item("w1"))
            self.assertEqual([row["header_names"] for row in read_jsonl(root / "quarantine.jsonl")],
                             [["content-type", "x-ok"]])


class CredentialGrammarTests(unittest.TestCase):
    """RA5-007 / design 7.5 ("one line with the key; anything else is refused"), 7.6: the credential loader accepts only
    printable ASCII without a space. The body scan has no Latin-1/mojibake views for a non-ASCII key (the header path
    does), so such a key is refused where it enters, before it can be sent or echoed. Killed: the check removed; the
    space or DEL boundary moved; the non-ASCII half dropped."""

    def load(self, content: bytes) -> Secret:
        with scratch_root() as base:
            folder = base / "keys"
            folder.mkdir()
            path = folder / "oddspapi.key"
            path.write_bytes(content)
            restrict(path)
            try:
                fingerprint = Secret(content[:-1] if content.endswith(b"\n") else content).fingerprint
            except (ValueError, TypeError):
                fingerprint = "0" * 12
            source = CredentialSource(repo=REPO, runtime_root=base / "runtime", expected_fingerprint=fingerprint,
                                      environ={ENV_VAR: str(path)})
            return source.load()

    def refused(self, content: bytes) -> str:
        with self.assertRaises(err.CredentialProblem) as caught:
            self.load(content)
        self.assertNotIn(content.decode("latin-1").strip(), str(caught.exception) + repr(caught.exception.args))
        return caught.exception.code

    def test_printable_ascii_without_a_space_loads(self):
        import string

        for key in (SENTINEL_KEY, "!", "~", "a" * 200, string.digits + string.ascii_letters + string.punctuation):
            with self.subTest(key=key[:12]):
                self.assertEqual(self.load(key.encode("ascii") + b"\n").fingerprint, Secret(key).fingerprint)
                self.assertEqual(self.load(key.encode("ascii")).fingerprint, Secret(key).fingerprint)

    def test_every_other_octet_is_refused_as_not_a_key(self):
        cases = {
            "latin1_letter_as_utf8": "caf\u00e9".encode("utf-8"),
            "latin1_octet": b"key\xe9value",
            "cyrillic": "\u043a\u043b\u044e\u0447".encode("utf-8"),
            "fullwidth": "\uff21\uff22\uff23".encode("utf-8"),
            "no_break_space": "ab\u00a0cd".encode("utf-8"),
            "zero_width_space": "ab\u200bcd".encode("utf-8"),
            "emoji": "ab\U0001f511cd".encode("utf-8"),
            "inner_space": b"ab cd",
            "inner_tab": b"ab\tcd",
            "nul": b"ab\x00cd",
            "del": b"ab\x7fcd",
            "escape": b"ab\x1bcd",
            "leading_space": b" abcd",
            "trailing_space": b"abcd ",
        }
        for label, content in cases.items():
            with self.subTest(label):
                self.assertEqual(self.refused(content), A.CREDENTIAL_MISSING.value)


class GateWindowBoundaryTests(unittest.TestCase):
    """RA5-012 (the audit's M35 and M46 survivors) / design 16.2, 16.3: a gate record is valid from ``valid_from`` (or its
    grant) up to and INCLUDING ``valid_through``, and a G2 record pins distinct request hashes. Killed: the end made
    exclusive, the start or the grant made exclusive or ignored, and duplicate request hashes allowed."""

    GRANTED = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    HASHES = [hashlib.sha256(str(index).encode()).hexdigest() for index in range(6)]

    def ledger(self, base: Path, *records):
        ledger = auth.AdapterAuthorityLedger(base / "authority.jsonl", limits=GATE_LIMITS)
        for record in records:
            ledger.append(record)
        return ledger

    def valid_at(self, ledger, gate: str, moment: datetime, **pins) -> bool:
        try:
            ledger.require_gate(gate, at=moment.isoformat(timespec="microseconds").replace("+00:00", "Z"), **pins)
        except err.GateMissing:
            return False
        return True

    def test_a_g1_record_is_valid_through_its_last_instant_inclusive(self):
        record = g1(self.GRANTED, days=1)
        end = self.GRANTED + timedelta(days=1)
        micro = timedelta(microseconds=1)
        with scratch_root() as base:
            ledger = self.ledger(base, record)
            pins = {"credential_fingerprint": G1_FINGERPRINT}
            observed = {
                "one tick before the grant": self.valid_at(ledger, "G1", self.GRANTED - micro, **pins),
                "at the grant": self.valid_at(ledger, "G1", self.GRANTED, **pins),
                "inside": self.valid_at(ledger, "G1", self.GRANTED + timedelta(hours=1), **pins),
                "one tick before the end": self.valid_at(ledger, "G1", end - micro, **pins),
                "at valid_through": self.valid_at(ledger, "G1", end, **pins),
                "one tick after valid_through": self.valid_at(ledger, "G1", end + micro, **pins),
            }
        self.assertEqual(observed, {"one tick before the grant": False, "at the grant": True, "inside": True,
                                    "one tick before the end": True, "at valid_through": True,
                                    "one tick after valid_through": False})

    def test_a_g2_record_is_valid_over_its_closed_window(self):
        record = g2(self.GRANTED, self.HASHES[:2], hours=12)
        start, end = self.GRANTED, self.GRANTED + timedelta(hours=12)
        micro = timedelta(microseconds=1)
        with scratch_root() as base:
            ledger = self.ledger(base, record)
            pins = {"request_hash": self.HASHES[0]}
            observed = {
                "before the window": self.valid_at(ledger, "G2", start - micro, **pins),
                "window opens": self.valid_at(ledger, "G2", start, **pins),
                "window closes": self.valid_at(ledger, "G2", end, **pins),
                "after the window": self.valid_at(ledger, "G2", end + micro, **pins),
                "an unpinned request": self.valid_at(ledger, "G2", start, request_hash=self.HASHES[5]),
            }
        self.assertEqual(observed, {"before the window": False, "window opens": True, "window closes": True,
                                    "after the window": False, "an unpinned request": False})

    def test_the_window_start_and_the_grant_are_independent_bounds(self):
        # valid_from later than the grant: the window, not the grant, decides the start
        later = self.GRANTED + timedelta(hours=2)
        record = {**g2(self.GRANTED, self.HASHES[:1], hours=12), "valid_from": later.isoformat(
            timespec="microseconds").replace("+00:00", "Z")}
        micro = timedelta(microseconds=1)
        with scratch_root() as base:
            ledger = self.ledger(base, record)
            pins = {"request_hash": self.HASHES[0]}
            self.assertFalse(self.valid_at(ledger, "G2", self.GRANTED, **pins))          # granted, window not open
            self.assertFalse(self.valid_at(ledger, "G2", later - micro, **pins))
            self.assertTrue(self.valid_at(ledger, "G2", later, **pins))
        # granted later than the window opens: the grant decides the start
        granted_late = {**g2(self.GRANTED + timedelta(hours=3), self.HASHES[:1], hours=12),
                        "valid_from": self.GRANTED.isoformat(timespec="microseconds").replace("+00:00", "Z")}
        with scratch_root() as base:
            ledger = self.ledger(base, granted_late)
            granted = self.GRANTED + timedelta(hours=3)
            self.assertFalse(self.valid_at(ledger, "G2", granted - micro, **pins))
            self.assertTrue(self.valid_at(ledger, "G2", granted, **pins))

    def test_a_g2_record_pins_distinct_request_hashes(self):
        with scratch_root() as base:
            ledger = self.ledger(base)
            for label, hashes in (("a repeated hash", [self.HASHES[0], self.HASHES[0]]),
                                  ("a hash repeated among others", [self.HASHES[0], self.HASHES[1], self.HASHES[0]])):
                with self.subTest(label), self.assertRaises(auth.AuthorityRecordInvalid):
                    ledger.append(g2(self.GRANTED, hashes))
            ledger.append(g2(self.GRANTED, self.HASHES[:2]))                          # the control
            self.assertEqual(len(ledger.records("G2")), 1)

    def test_a_g2_record_pins_at_most_the_architecture_cap_and_at_least_one(self):
        with scratch_root() as base:
            ledger = self.ledger(base)
            with self.assertRaises(auth.AuthorityRecordInvalid):
                ledger.append(g2(self.GRANTED, self.HASHES[:GATE_LIMITS.g2_requests_cap + 1]))
            with self.assertRaises(auth.AuthorityRecordInvalid):
                ledger.append(g2(self.GRANTED, []))
            ledger.append(g2(self.GRANTED, self.HASHES[:GATE_LIMITS.g2_requests_cap]))


class SecretFormTests(unittest.TestCase):
    """RA5-012 (the audit's M26, M27 and M28 survivors) / design 7.6: a credential made ONLY of percent-encodable
    characters cannot be rescued by the fragment detector, so each encoded form needs its own detector. Killed: fewer
    percent-decoding passes than three; the JSON ``\\/`` and ``\\u`` unescaping dropped; the base64 core of exactly the
    minimum length ignored."""

    POLICY = ps.POLICY
    KEY = "/+=&/+=&/+=&/+=&/+=&/+=&/+=&/+="                       # every character changes under percent-encoding

    def scanner(self, key: str):
        from genesis_adapters.secrets import SecretScanner

        return SecretScanner(Secret(key), policy=self.POLICY)

    def quote(self, text: str, times: int) -> str:
        for _ in range(times):
            text = urllib.parse.quote(text, safe="")
        return text

    def test_the_key_echoed_percent_encoded_once_twice_and_three_times_is_detected(self):
        scanner = self.scanner(self.KEY)
        for times in (1, 2, 3):
            with self.subTest(times=times):
                result = scanner.scan(("echo-" + self.quote(self.KEY, times) + "-echo").encode("ascii"))
                self.assertTrue(result.hit)
                self.assertIn("PERCENT", result.detection_classes)

    def test_the_key_echoed_with_json_escapes_is_detected(self):
        scanner = self.scanner(self.KEY)
        forms = {
            "escaped slash": self.KEY.replace("/", "\\/"),
            "unicode escapes": "".join("\\u%04x" % ord(char) for char in self.KEY),
            "unicode escapes, upper case": "".join("\\u%04X" % ord(char) for char in self.KEY),
        }
        for label, form in forms.items():
            with self.subTest(label):
                self.assertTrue(scanner.scan(("echo-" + form + "-echo").encode("ascii")).hit)

    def test_the_control_text_is_not_a_hit(self):
        scanner = self.scanner(self.KEY)
        for text in ("plain text", self.quote("unrelated/+=&", 2), "\\/+=&"):
            self.assertFalse(scanner.scan(text.encode("ascii")).hit, text)

    def test_the_key_echoed_through_the_pipeline_halts_and_leaves_nothing_durable(self):
        key = Secret(self.KEY)
        for label, form in (("double percent-encoded", self.quote(self.KEY, 2)),
                            ("escaped slash", self.KEY.replace("/", "\\/"))):
            with self.subTest(label), scratch_root() as root:
                payload = ps.odds_payload()
                payload[0]["tournamentName"] = "@E@"
                body = json.dumps(payload, sort_keys=True).replace('"@E@"', '"echo-' + form + '-echo"').encode("ascii")
                rt = open_rt(root, secret=key, script=[ok(body, headers=JSON)])
                with self.assertRaises(err.AcquisitionHalt) as caught:
                    rt.acquire(odds_item("w1"))
                self.assertEqual(caught.exception.code, A.SECRET_ECHO)
                self.assertFalse((root / "evidence").exists() and any((root / "evidence").rglob("*")))

    def test_a_base64_core_of_exactly_the_minimum_length_is_detected(self):
        # a six-byte key has one base64 core, eight characters long: exactly ``secret_fragment_min_chars_floor``
        floor = self.POLICY.secret_fragment_min_chars_floor
        key = "!@#$%^"
        self.assertEqual((len(key) * 8) // 6, floor)
        scanner = self.scanner(key)
        raw = key.encode("ascii")
        forms = {"standard": base64.b64encode(raw), "url-safe": base64.urlsafe_b64encode(raw)}
        for label, form in forms.items():
            with self.subTest(label):
                self.assertEqual(len(form.rstrip(b"=")), floor)
                result = scanner.scan(b"echo-" + form + b"-echo")
                self.assertTrue(result.hit)
                self.assertIn("BASE64", result.detection_classes)

    def test_base64_echoes_of_a_longer_key_are_detected_at_every_alignment(self):
        key = "!@#$%^&*("                                               # nine bytes: cores of 12, 11 and 11 characters
        scanner = self.scanner(key)
        raw = key.encode("ascii")
        for prefix in (b"", b"A", b"AB"):
            for encoder in (base64.b64encode, base64.urlsafe_b64encode):
                with self.subTest(prefix=prefix, encoder=encoder.__name__):
                    self.assertTrue(scanner.scan(b"echo-" + encoder(prefix + raw) + b"-echo").hit)


class CredentialModeTests(unittest.TestCase):
    """RA5-012 (the audit's M30 survivor) / design 7.5: on POSIX the key file's mode must be exactly ``0600``. A file that
    only the owner can read (``0400``) is still not the file the architecture describes. Killed: the mode test relaxed
    to "no group or other bits"."""

    @unittest.skipIf(sys.platform == "win32", "POSIX modes: on Windows the ACL, not a mode, decides (WINDOWS_GAPS.md)")
    def test_only_mode_0600_is_accepted(self):
        with scratch_root() as base:
            folder = base / "keys"
            folder.mkdir()
            path = folder / "oddspapi.key"
            path.write_bytes(SENTINEL_KEY.encode() + b"\n")
            fingerprint = Secret(SENTINEL_KEY).fingerprint

            def attempt(mode: int):
                os.chmod(path, mode)
                source = CredentialSource(repo=REPO, runtime_root=base / "runtime", expected_fingerprint=fingerprint,
                                          environ={ENV_VAR: str(path)})
                try:
                    return source.load().fingerprint
                except err.CredentialProblem as problem:
                    return problem.code

            observed = {oct(mode): attempt(mode) for mode in (0o600, 0o400, 0o500, 0o700, 0o200, 0o000, 0o640, 0o604)}
        self.assertEqual(observed, {"0o600": fingerprint} | {oct(mode): A.CREDENTIAL_PERMISSIONS.value for mode in (
            0o400, 0o500, 0o700, 0o200, 0o000, 0o640, 0o604)})


class ExactSizeBodyTests(unittest.TestCase):
    """RA5-012 (the audit's M22 survivor) / design 14.6, 15 F-06: ``max_response_bytes`` is a cap on what is received, so
    a body of exactly that many bytes is within it and one byte more is not - at the capture and at the strict
    decoder. Killed: ``>`` read as ``>=`` at either."""

    LIMIT = 1000

    def body(self, length: int) -> bytes:
        return b"[" + b" " * (length - 2) + b"]"

    def test_the_capture_accepts_a_body_of_exactly_the_cap_and_flags_one_byte_more(self):
        policy = policy_with(max_response_bytes=self.LIMIT)
        for length, expected in ((self.LIMIT - 1, None), (self.LIMIT, None), (self.LIMIT + 1, A.OVERSIZE_BODY)):
            with self.subTest(length=length), scratch_root() as root:
                captured = CaptureFixture(root, secret=SENTINEL_KEY, policy=policy).store(self.body(length))
                self.assertEqual((captured.kind, captured.failure), ("STORED", expected))

    def test_the_strict_decoder_accepts_exactly_the_cap_and_refuses_one_byte_more(self):
        policy = policy_with(max_response_bytes=self.LIMIT)

        def loads(data: bytes):
            return jsonstrict.loads_strict(data, max_bytes=policy.max_response_bytes, max_depth=policy.json_max_depth,
                                           max_exponent=policy.json_max_number_exponent)

        self.assertEqual(loads(self.body(self.LIMIT)), [])
        with self.assertRaises(jsonstrict.StrictJsonError) as caught:
            loads(self.body(self.LIMIT + 1))
        self.assertEqual(caught.exception.code, "OVERSIZE")

    def test_through_the_runtime_an_exact_size_body_is_a_response_and_one_byte_more_is_oversize(self):
        for length, expected in ((self.LIMIT, None), (self.LIMIT + 1, A.OVERSIZE_BODY)):
            with self.subTest(length=length), scratch_root() as root:
                rt = open_rt(root, script=[ok(self.body(length), headers=JSON)],
                             config_dir=self.small_cap_config(root))
                outcome = rt.runner.acquire(odds_item("w1"))
                self.assertEqual(outcome.failure, expected)                  # ``[]``: an ODDS response with no events

    def small_cap_config(self, root: Path) -> Path:
        dest = root / "config"
        shutil.copytree(CONFIG, dest)
        policy = json.loads((dest / cfg.POLICY_FILE).read_text(encoding="utf-8"))
        policy["max_response_bytes"] = self.LIMIT
        (dest / cfg.POLICY_FILE).write_text(json.dumps(policy, indent=1), encoding="utf-8")
        return dest


class QuarantineMetadataScanTests(unittest.TestCase):
    """RA5-012 (the audit's M40 survivor; it is NOT an equivalent mutant) / design 7.6: the quarantine record is scanned as
    a whole before it is written. A key can span fields of the canonical record - clean field by field, a hit as one
    text - and then nothing optional survives. Killed: the whole-record scan removed."""

    def written(self, key: str, headers) -> dict:
        with scratch_root() as root:
            fixture = CaptureFixture(root, secret=key)
            result = TransportResult("RESPONSE", 200, tuple(headers), b"[]", None, "2026-10-01T12:00:00.000000Z",
                                     "2026-10-01T12:00:01.000000Z")
            fixture.capture.write_quarantine("d" * 64, capture_request(), result, "2026-10-01T12:00:01.000000Z",
                                             A.UNINSPECTABLE_BODY.value, set(), 2)
            rows = read_jsonl(root / "quarantine.jsonl")
            self.assertEqual(len(rows), 1)
            return rows[0]

    def test_the_control_keeps_the_optional_metadata(self):
        row = self.written(SENTINEL_KEY, JSON)
        self.assertEqual((row["content_type"], row["header_names"]), ("application/json", ["content-type"]))

    def test_a_key_spanning_fields_of_the_record_leaves_no_optional_metadata(self):
        key = 'json","detection_classes":[],"header_names'
        row = self.written(key, JSON)
        self.assertEqual((row["content_type"], row["header_names"]), (None, []))
        self.assertNotIn(key, json.dumps(row))


class UnpinnedScopeTests(unittest.TestCase):
    """RA5-012 (the audit's reclassification of the R3 "equivalent" survivor) / design 12.4, 11.5: a document derived under
    an expected scope that is not the one pinned on the ``sent`` row is not that attempt's derivation, even when it is
    reproducible from its own pinned scope. Killed: the comparison with the pinned hash removed."""

    def test_a_document_derived_under_another_scope_is_not_accepted(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item("w1"))
            approve(rt)
            aid = next(r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned")["acquisition_id"]
            rows = derivation.acquisition_rows(rt.stores.acquisition, aid)
            pinned = rows["acq_sent"]["expected_scope_hash"]
            real = scope_mod.load_scope(root, pinned)
            first = json.loads(rt.stores.evidence.get_bytes(pit_rows(rt)[0]["payload_hash"]))
            invented = scope_mod.ExpectedBook(
                entity_id="book:" + "ab" * 32, event_id=first["event_id"], competition_id=first["competition_id"],
                provider_fixture_id=first["provider_fixture_id"], home_participant_id=first["home_participant_id"],
                away_participant_id=first["away_participant_id"],
                scheduled_start_as_known=first["scheduled_start_as_known"], bookmaker_id=first["bookmaker_id"],
                provider_bookmaker_key=first["provider_bookmaker_key"], market_id=first["market_id"],
                market_family=first["market_family"], line=first["line"], period=first["period"])
            other = dict(real)
            other[invented.entity_id] = invented
            other_hash = scope_mod.publish_scope(root, other.values(), as_of=rows["acq_sent"]["T0"])
            self.assertNotEqual(other_hash, pinned)
            prefix = rt.stores.identity.prefix(rows["acq_normalized"]["identity_registry_head"]["sequence"])
            inputs = derivation.odds_inputs(rt.stores, rt.config, rt.maps, aid, identity_prefix=prefix,
                                            expected_scope=other, expected_scope_hash=other_hash, fixture_join=None,
                                            request_root=root)
            built = {item.entity_id: item
                     for item in normalize.build_documents(parser.parse_odds_response(inputs.raw, inputs.ctx),
                                                           inputs.ctx)}
            document = built[invented.entity_id]
            self.assertEqual(json.loads(document.data)["expected_scope_hash"], other_hash)
            uri = emit.response_source_uri(rt.stores.derivation_version, document.entity_id,
                                           inputs.ctx.raw_observation_id)
            received = inputs.ctx.response_received_at
            published = rt.stores.evidence.publish(
                document.data, contract_id=rt.stores.contract_id, source_uri=uri, provider="oddspapi",
                source_type="oddspapi_v4_market_book", retrieved_at=received, parse_ready_at=ps.iso_add(received, seconds=1),
                first_seen_at=received, publisher_timestamp=document.publisher_timestamp, valid_from=received,
                valid_to=document.valid_to, upstream_version="v4", parser_version=rt.stores.derivation_version,
                content_type="application/json", licensing_note=rt.stores.licensing_note,
                availability_class=AvailabilityClass.DERIVED)
            with self.assertRaisesRegex(DerivationError, "pinned before the send"):
                rt.verify_derivation(published.observation_id)


if __name__ == "__main__":
    unittest.main()
