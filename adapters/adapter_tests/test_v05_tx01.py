"""TX-01 (design 7.7): the transport exception boundary, end to end, in a SUBPROCESS started through a thin
harness that calls the operator CLI's real ``main()`` for a gated G2 verification run.

A fault-injecting connection fires at every send stage (connect, write, read headers, read body, header
decode). Ordinary exceptions carry the credential-bearing URL in their message, args, filename, ``url``
attribute, notes and chained cause/context, and a warning carries it too: the run must record only a
sanitized class/errno and end normally. Injected ``KeyboardInterrupt`` / ``SystemExit`` must keep their
meaning (platform SIGINT status; exit code 37; 1 for a text code whose text is never printed; 0 for None)
and reach the harness as FRESH instances: no cause, no context, no notes, args ``()``/``(int,)`` and no
traceback-frame local whose repr holds any section-7.6 form of the key. stdout, stderr, the harness result
file and every file under the runtime root must be clean of the key in every form.

The gate records here are synthetic, written by the test into a throwaway directory; nothing in this
test contacts anything but the in-process fault injector (the harness installs the loopback audit hook).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from genesis.time import iso_utc, parse_utc

from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import verify
from genesis_adapters.oddspapi.acquisition import boundary_guard
from genesis_adapters.oddspapi.authority import AdapterAuthorityLedger, load_gate_limits
from genesis_adapters.secrets import Secret, SecretScanner

from . import parser_support as ps
from .loopback_support import TEST_CA, LoopbackHttps, Reply
from .pipeline_support import SPECS
from .support import CONFIG, REPO, SENTINEL_KEY, read_jsonl, scratch_root
from genesis_adapters.oddspapi import endpoints as ep

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
STATUS_CONTROL_C_EXIT = 0xC000013A
PARAMS = {"bookmaker": ["pinnacle"], "tournamentIds": [17, 8], "oddsFormat": "decimal"}

HARNESS = textwrap.dedent('''
    import json, sys, warnings, ipaddress

    RESULT, STAGE, KIND, SENTINEL = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    CLI_ARGS = json.loads(sys.argv[5])
    KEYED = "https://api.oddspapi.io/v4/odds-by-tournaments?apiKey=" + SENTINEL

    def _audit(event, args):
        if event == "socket.connect" and isinstance(args[1], tuple) and args[1]:
            if not ipaddress.ip_address(str(args[1][0]).split("%")[0]).is_loopback:
                raise RuntimeError("non-loopback contact")
        if event == "socket.getaddrinfo" and args[0] not in ("localhost", "127.0.0.1", "::1", None):
            raise RuntimeError("non-loopback name")
    sys.addaudithook(_audit)

    from genesis_adapters import cli
    from genesis_adapters.oddspapi import transport_http
    from genesis_adapters.config import load_policy
    from genesis_adapters.secrets import Secret, SecretScanner

    def boom():
        if KIND == "NAMED":                      # R-1 / CR-08: the class NAME itself carries the key
            raise type("Err_" + SENTINEL.replace("-", "_"), (OSError,), {})()
        if KIND == "EXC":
            warnings.warn(KEYED)
            exc = OSError(104, KEYED, KEYED)
            exc.url = KEYED
            exc.add_note(KEYED)
            exc.__cause__ = ValueError(KEYED)
            try:
                raise LookupError(KEYED)
            except LookupError:
                raise exc
        if KIND == "KBI":
            exc = KeyboardInterrupt(KEYED)
            exc.add_note(KEYED)
            exc.__cause__ = ValueError(KEYED)
            raise exc
        if KIND == "EXIT37":
            raise SystemExit(37)
        if KIND == "EXITSTR":
            raise SystemExit(KEYED)
        raise SystemExit(None)

    class Explosive:
        def __str__(self):
            boom()

    class FaultyConnection:
        def __init__(self, host, port, context, address):
            pass
        def open(self, timeout):
            if STAGE == "connect":
                boom()
        def settimeout(self, timeout):
            pass
        def write(self, method, target, headers):
            if STAGE == "write":
                boom()
        def read_head(self):
            if STAGE == "read_headers":
                boom()
            if STAGE == "decode":
                return 200, [(Explosive(), "x")]
            return 200, [("Content-Type", "application/json")]
        def read_chunk(self, size):
            if STAGE == "read_body":
                boom()
            return b""
        def finished(self):
            return False
        def close(self):
            if STAGE == "close":                 # HA-02: a fault while the connection is being closed
                boom()

    if STAGE == "loopback":                      # the real connection, to the test's loopback server; the test CA
        import os, ssl                           # and address are injected HERE, never through the production CLI
        _Real = transport_http.HttpsTransport
        class LoopbackTransport(_Real):
            def __init__(self, secret, **kw):
                context = ssl.create_default_context(cafile=os.environ["GENESIS_TEST_LOOPBACK_CA"])
                address = ("127.0.0.1", int(os.environ["GENESIS_TEST_LOOPBACK_PORT"]))
                super().__init__(secret, ssl_context=context, connect_address=address, **kw)
        transport_http.HttpsTransport = LoopbackTransport
    else:
        transport_http._Connection = FaultyConnection
    cli.time_sync_attestation = lambda: {"synchronized": True, "method": "harness", "source": "harness"}

    def record(exc):
        scanner = SecretScanner(Secret(SENTINEL), policy=load_policy(cli._config_dir(None) / "oddspapi_slice1_policy.json"))
        frames_clean = True
        tb = exc.__traceback__ if exc is not None else None
        while tb is not None:
            for value in tb.tb_frame.f_locals.values():
                try:
                    text = repr(value)
                except Exception:
                    text = ""
                if scanner.scan(text.encode("utf-8", "replace")).hit:
                    frames_clean = False
            tb = tb.tb_next
        body = {"class": type(exc).__name__ if exc is not None else None,
                "code": exc.code if isinstance(exc, SystemExit) and type(exc.code) is int else None,
                "cause_is_none": exc is None or exc.__cause__ is None,
                "context_is_none": exc is None or exc.__context__ is None,
                "has_notes": exc is not None and hasattr(exc, "__notes__"),
                "args_ok": exc is None or exc.args == () or (len(exc.args) == 1 and type(exc.args[0]) is int),
                "frames_clean": frames_clean}
        with open(RESULT, "w", encoding="utf-8") as handle:
            json.dump(body, handle)

    def run():
        try:
            code = cli.main(CLI_ARGS)
        except BaseException as exc:
            record(exc)
            raise
        record(None)
        return code

    sys.exit(run())
''')


def restrict_to_current_user(path: Path) -> None:
    if sys.platform == "win32":
        user = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True, check=True)
    else:
        os.chmod(path, 0o600)


def in_guard_zone() -> bool:
    return not boundary_guard(iso_utc(datetime.now(timezone.utc)), POLICY).permitted


def prepare(base: Path) -> tuple[Path, Path, dict]:
    """A scratch runtime root with synthetic G1/G2 records, the sentinel key file and a one-item plan."""

    root, keys = base / "runtime", base / "keys"
    root.mkdir()
    keys.mkdir()
    credential = keys / "oddspapi.key"
    credential.write_bytes(SENTINEL_KEY.encode("ascii") + b"\n")        # one LF-terminated line
    restrict_to_current_user(credential)
    now = datetime.now(timezone.utc)
    request = ep.build_request(SPECS["ODDS"], **PARAMS)
    ledger = AdapterAuthorityLedger(root / "authority.jsonl", limits=load_gate_limits(CONFIG))
    common = {"record_type": "gate_record", "schema_version": "adapter-authority-v1",
              "approver": "synthetic-test-only", "granted_at": iso_utc(now - timedelta(hours=1))}
    ledger.append({**common, "gate": "G1", "approval_reference": "adr:synthetic-test-only-g1",
                   "terms_snapshot_sha256": "0" * 64, "licensing_note": "FIXTURE-ONLY-NO-PROVIDER-TERMS",
                   "credential_fingerprint": Secret(SENTINEL_KEY).fingerprint,
                   "credential_path_policy": "outside-repo-and-root; owner-only",
                   "valid_through": iso_utc(now + timedelta(days=1))})
    ledger.append({**common, "gate": "G2", "approval_reference": "adr:synthetic-test-only-g2",
                   "request_hashes": [request.provider_request_hash], "max_calls": 1,
                   "valid_from": iso_utc(now - timedelta(hours=1)), "valid_through": iso_utc(now + timedelta(hours=12))})
    plan = base / "plan.json"
    plan.write_text(json.dumps([{"role": "ODDS", "params": PARAMS, "window": "tx01"}]), encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONPYCACHEPREFIX"}}
    env.update({"GENESIS_ODDSPAPI_CREDENTIAL_FILE": str(credential),
                "PYTHONPATH": os.pathsep.join([str(REPO / "adapters" / "src"), str(REPO / "src")]),
                "PYTHONPYCACHEPREFIX": str(base / "pycache")})
    return root, plan, env


class Tx01Tests(unittest.TestCase):
    def run_case(self, stage: str, kind: str):
        with scratch_root() as base:
            root, plan, env = prepare(base)
            harness, result = base / "harness.py", base / "result.json"
            harness.write_text(HARNESS, encoding="utf-8")
            args = ["run", "--root", str(root), "--plan", str(plan), "--mode", "G2"]
            proc = subprocess.run([sys.executable, "-B", str(harness), str(result), stage, kind, SENTINEL_KEY,
                                   json.dumps(args)], env=env, cwd=str(REPO), capture_output=True, timeout=180)
            scanner = SecretScanner(Secret(SENTINEL_KEY), policy=POLICY)
            outcome = json.loads(result.read_text(encoding="utf-8"))
            self.assertFalse(scanner.scan(proc.stdout).hit, "stdout")
            self.assertFalse(scanner.scan(proc.stderr).hit, "stderr")
            self.assertFalse(scanner.scan(result.read_bytes()).hit, "harness result")
            self.assertEqual(verify.scan_runtime_for_secret(root, Secret(SENTINEL_KEY)), ())
            completed = [r for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_completed"]
            return proc, outcome, completed

    def setUp(self):
        if in_guard_zone():
            self.skipTest("the real UTC clock is inside the day/month boundary guard zone; no send is possible")

    def test_tx01_ordinary_failures_at_every_stage_become_sanitized_results(self):
        expected = {"connect": "NO_RESPONSE", "write": "NO_RESPONSE", "read_headers": "NO_RESPONSE",
                    "read_body": "TRUNCATED", "decode": "NO_RESPONSE"}
        for stage, outcome_name in expected.items():
            with self.subTest(stage):
                proc, outcome, completed = self.run_case(stage, "EXC")
                self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
                self.assertIsNone(outcome["class"])                           # nothing reached the top level
                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0]["outcome"], outcome_name)
                error = completed[0]["sanitized_error"]
                if outcome_name == "NO_RESPONSE":
                    self.assertEqual(set(error), {"class", "errno"})
                    self.assertIn(error["class"], {"OSError", "ConnectionResetError"})
                    self.assertIn(error["errno"], (104, None))

    def test_tx01_r1_a_key_named_exception_class_is_scanned_and_redacted_before_it_is_persisted(self):
        # design 7.6 item 3: the sanitized record is itself scanned; run_case also sweeps stdout, stderr, the
        # harness result and every runtime file for every section-7.6 form of the key
        for stage in ("connect", "write", "read_headers", "decode"):
            with self.subTest(stage):
                proc, outcome, completed = self.run_case(stage, "NAMED")
                self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
                self.assertIsNone(outcome["class"])                           # nothing reached the top level
                self.assertEqual(len(completed), 1)                           # the attempt is still recorded
                self.assertEqual(completed[0]["outcome"], "NO_RESPONSE")
                stored = completed[0]["sanitized_error"]                      # never printed: it may carry the key
                self.assertTrue(stored == {"class": "REDACTED_EXCEPTION_CLASS", "errno": None},
                                "the stored sanitized record is not the redaction placeholder")

    def test_tx01_r2_process_control_raised_by_close_arrives_fresh(self):
        # HA-02: close() runs after the exchange; its KeyboardInterrupt / SystemExit must leave exactly like one
        # raised during the send (fresh, status kept, no text, cause, context, notes or keyed frame local)
        wanted = {"KBI": (STATUS_CONTROL_C_EXIT if sys.platform == "win32" else -2, "KeyboardInterrupt", None),
                  "EXIT37": (37, "SystemExit", 37), "EXITSTR": (1, "SystemExit", 1), "EXITNONE": (0, "SystemExit", None)}
        for kind, (code, cls, recorded) in wanted.items():
            with self.subTest(kind):
                proc, outcome, _ = self.run_case("close", kind)
                self.assertEqual(proc.returncode, code)
                self.assertEqual(outcome, {"class": cls, "code": recorded, "cause_is_none": True,
                                           "context_is_none": True, "has_notes": False, "args_ok": True,
                                           "frames_clean": True})
                self.assertNotIn(b"apiKey", proc.stderr)

    def test_tx01_r2_an_ordinary_or_key_named_error_in_close_is_contained(self):
        for kind in ("EXC", "NAMED"):
            with self.subTest(kind):
                proc, outcome, completed = self.run_case("close", kind)
                self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
                self.assertIsNone(outcome["class"])                           # nothing reached the top level
                self.assertEqual(len(completed), 1)

    def test_tx01_keyboard_interrupt_keeps_its_meaning_and_arrives_fresh(self):
        wanted = STATUS_CONTROL_C_EXIT if sys.platform == "win32" else -2
        for stage in ("connect", "write", "read_headers", "read_body", "decode"):
            with self.subTest(stage):
                proc, outcome, _ = self.run_case(stage, "KBI")
                self.assertEqual(proc.returncode, wanted)
                self.assertEqual(outcome, {"class": "KeyboardInterrupt", "code": None, "cause_is_none": True,
                                           "context_is_none": True, "has_notes": False, "args_ok": True,
                                           "frames_clean": True})

    def test_tx01_system_exit_keeps_its_status_and_never_prints_text(self):
        for kind, code, recorded in (("EXIT37", 37, 37), ("EXITSTR", 1, 1), ("EXITNONE", 0, None)):
            with self.subTest(kind):
                proc, outcome, _ = self.run_case("write", kind)
                self.assertEqual(proc.returncode, code)
                self.assertEqual(outcome, {"class": "SystemExit", "code": recorded, "cause_is_none": True,
                                           "context_is_none": True, "has_notes": False, "args_ok": True,
                                           "frames_clean": True})
                self.assertNotIn(b"apiKey", proc.stderr)


class LoopbackRunTests(unittest.TestCase):
    """The operator CLI's ``run`` end to end through the REAL HTTPS transport to the in-process loopback server
    (the test CA and the loopback address injected by the harness, never through the production CLI, which has no
    such option). The gate records are synthetic and
    live in a scratch directory; the pinned production host is never contacted. A loopback test, not the G2 smoke."""

    def setUp(self):
        if in_guard_zone():
            self.skipTest("the real UTC clock is inside the day/month boundary guard zone; no send is possible")
        self.server = LoopbackHttps()
        self.addCleanup(self.server.close)

    def test_cli_run_sends_one_keyed_request_and_keeps_only_scanned_raw_evidence(self):
        self.server.replies.append(Reply(body=ps.dump(ps.odds_payload()),
                                         headers=(("Content-Type", "application/json"),
                                                  ("Date", formatdate(usegmt=True)), ("X-Requests-Used", "1"))))
        with scratch_root() as base:
            root, plan, env = prepare(base)
            harness, result = base / "harness.py", base / "result.json"
            harness.write_text(HARNESS, encoding="utf-8")
            args = ["run", "--root", str(root), "--plan", str(plan), "--mode", "G2"]
            env.update({"GENESIS_TEST_LOOPBACK_CA": str(TEST_CA), "GENESIS_TEST_LOOPBACK_PORT": str(self.server.port)})
            proc = subprocess.run([sys.executable, "-B", str(harness), str(result), "loopback", "NONE", SENTINEL_KEY,
                                   json.dumps(args)], env=env, cwd=str(REPO), capture_output=True, timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertEqual(proc.stdout.decode("ascii").split(), ["tx01:", "RESPONSE"])
            rows = read_jsonl(root / "acquisition.jsonl")
            sent = [r for r in rows if r["record_type"] == "acq_sent"]
            completed = [r for r in rows if r["record_type"] == "acq_completed"]
            self.assertEqual((len(sent), len(completed)), (1, 1))
            done = completed[0]
            self.assertEqual((done["outcome"], done["http_status"], done["failure"]), ("RESPONSE", 200, None))
            self.assertIsNotNone(done["raw_observation_id"])
            self.assertEqual(done["provider_reported_usage"]["reported"], 1)
            self.assertLess(parse_utc(sent[0]["T0"]), parse_utc(done["T1"]))    # design 6.3, on the real clock
            self.assertEqual(len(self.server.seen), 1)                           # G2 max_calls = 1
            _, target, _ = self.server.seen[0].request_line.split(" ")
            self.assertTrue(dict(parse_qsl(urlsplit(target).query))["apiKey"] == SENTINEL_KEY,   # on the wire only
                            "the key on the wire is not the configured key")
            self.assertEqual({k.lower(): v for k, v in self.server.seen[0].headers}["host"], "api.oddspapi.io")
            pit = [r for r in read_jsonl(root / "pit.jsonl") if r.get("record_type") == "pit_record"]
            self.assertEqual(pit, [])                                            # G2: raw capture only
            scanner = SecretScanner(Secret(SENTINEL_KEY), policy=POLICY)
            self.assertFalse(scanner.scan(proc.stdout + proc.stderr).hit)
            self.assertEqual(verify.scan_runtime_for_secret(root, Secret(SENTINEL_KEY)), ())


if __name__ == "__main__":
    unittest.main()
