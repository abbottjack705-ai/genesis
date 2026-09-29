"""The operator CLI: FRZ-09 at runner startup, sanitizing flow-neutral hooks, BILL-04 wording, and the
plan / verify / report commands."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from genesis_adapters import cli
from genesis_adapters.secrets import Secret, SecretScanner

from . import parser_support as ps
from . import static_scan as scan
from .pipeline_support import JSON, odds_item, odds_response, open_rt
from .support import CONFIG, REPO, SENTINEL_KEY, scratch_root

KEYED = "https://api.oddspapi.io/v4/odds?apiKey=" + SENTINEL_KEY
STATUS_CONTROL_C_EXIT = 0xC000013A
FORBIDDEN = re.compile(r"provider[\s_-]*billed|billed[\s_-]*by[\s_-]*the[\s_-]*provider", re.IGNORECASE)


def child_env(pycache: Path | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE"}}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "adapters" / "src"), str(REPO / "src")])
    if pycache is not None:
        env["PYTHONPYCACHEPREFIX"] = str(pycache)
    return env


def run(args, *, base: Path, isolated: bool = True, code: str | None = None):
    """``isolated=False`` drops ``-B`` but keeps a throwaway pycache prefix, so the refused run can never write
    bytecode next to the (frozen) sources."""

    command = [sys.executable] + (["-B"] if isolated else []) + (["-c", code] if code else ["-m", "genesis_adapters.cli", *args])
    prefix = base / ("pycache" if isolated else "pycache-unisolated")
    return subprocess.run(command, env=child_env(prefix), cwd=str(REPO), capture_output=True, timeout=180)


class StartupTests(unittest.TestCase):
    def plan_args(self, base: Path):
        fixtures = base / "fixtures.json"
        fixtures.write_text(json.dumps([{"fixture_id": "f1", "start": "2026-10-10T15:00:00.000000Z"}]), encoding="utf-8")
        return ["plan", "--fixtures", str(fixtures), "--month", "2026-10", "--as-of", "2026-10-01T00:00:00.000000Z",
                "--used", "0"]

    def test_frz09_the_runner_refuses_to_start_without_isolated_bytecode(self):
        with scratch_root() as base:
            refused = run(self.plan_args(base), base=base, isolated=False)
            self.assertEqual(refused.returncode, cli.EXIT_REFUSED, refused.stderr)
            self.assertIn(b"MODULE_PROVENANCE", refused.stderr)
            self.assertEqual(refused.stdout, b"")
            accepted = run(self.plan_args(base), base=base)
            self.assertEqual(accepted.returncode, cli.EXIT_OK, accepted.stderr)
            body = json.loads(accepted.stdout)
            self.assertEqual(len(body["digest"]), 64)
            self.assertTrue(body["windows"])

    def test_the_hooks_print_only_a_class_name_and_never_change_the_exit_status(self):
        with scratch_root() as base:
            prologue = "from genesis_adapters import cli; cli.install_hooks(); "
            ordinary = run([], base=base, code=prologue + f"raise ValueError({KEYED!r})")
            self.assertEqual((ordinary.returncode, ordinary.stderr.strip()), (1, b"error: ValueError"))
            interrupted = run([], base=base, code=prologue + f"raise KeyboardInterrupt({KEYED!r})")
            self.assertEqual(interrupted.returncode, STATUS_CONTROL_C_EXIT if sys.platform == "win32" else -2)
            self.assertEqual(interrupted.stderr.strip(), b"error: KeyboardInterrupt")
            thread = run([], base=base, code=prologue + "import threading; t = threading.Thread(target=lambda: "
                                                        f"(_ for _ in ()).throw(RuntimeError({KEYED!r}))); t.start(); t.join()")
            self.assertEqual((thread.returncode, thread.stderr.strip()), (0, b"error: RuntimeError"))
            exited = run([], base=base, code=prologue + "raise SystemExit(37)")
            self.assertEqual((exited.returncode, exited.stderr), (37, b""))
            scanner = SecretScanner(Secret(SENTINEL_KEY), policy=ps.POLICY)
            for proc in (ordinary, interrupted, thread, exited):
                self.assertFalse(scanner.scan(proc.stdout + proc.stderr).hit)

    def test_frz11_the_cli_has_no_process_control_handler(self):
        self.assertEqual(scan.scan_all(scan.scan_frz11), [])
        source = (REPO / "adapters" / "src" / "genesis_adapters" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("except BaseException", source)
        self.assertNotIn("faulthandler", source)


class CommandTests(unittest.TestCase):
    def test_bill04_reports_label_the_genesis_debit_and_provider_reported_usage_separately(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=JSON + (("x-requests-used", "1"),))])
            rt.acquire(odds_item())
            report = cli.usage_report(root)
            self.assertIn("Genesis debit (internal budget units): 1", report)
            self.assertIn("provider-reported usage (last header value): 1", report)
            self.assertIsNone(FORBIDDEN.search(report))
        for rel, source in scan.package_files():
            self.assertIsNone(FORBIDDEN.search(source), rel)
        for path in (REPO / "adapters" / "README.md",):
            self.assertIsNone(FORBIDDEN.search(path.read_text(encoding="utf-8")), path.name)

    def test_verify_rederives_every_document_of_a_runtime_root(self):
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response()])
            rt.acquire(odds_item())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.cmd_verify(SimpleNamespace(config=None, root=str(root),
                                                      licensing_note="FIXTURE-ONLY-NO-PROVIDER-TERMS"))
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(json.loads(out.getvalue()), {"derivations_verified": 12, "evidence_observations": 13})

    def test_run_refuses_without_gate_records_and_never_touches_a_network(self):
        with scratch_root() as root:
            plan = root / "plan.json"
            plan.write_text("[]", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2",
                                                   connect=None, ca_file=None))
            self.assertEqual(code, cli.EXIT_REFUSED)
            self.assertIn("no G1 record", err.getvalue())

    def test_run_refuses_a_test_ca_without_a_loopback_address(self):
        from .loopback_support import TEST_CA
        from .test_v05_tx01 import prepare
        with scratch_root() as base:
            root, plan, env = prepare(base)                   # synthetic G1/G2 records and the sentinel key file
            plan.write_text("[]", encoding="utf-8")           # nothing is ever planned, so nothing could be sent
            err = io.StringIO()
            credential = {"GENESIS_ODDSPAPI_CREDENTIAL_FILE": env["GENESIS_ODDSPAPI_CREDENTIAL_FILE"]}
            with mock.patch.dict(os.environ, credential), contextlib.redirect_stderr(err):
                code = cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2",
                                                   connect=None, ca_file=str(TEST_CA)))
            self.assertEqual(code, cli.EXIT_REFUSED)
            self.assertIn("a test CA is only accepted together with a loopback address", err.getvalue())

    def test_the_connect_override_accepts_loopback_addresses_only(self):
        self.assertEqual(cli._loopback("127.0.0.1:8443"), ("127.0.0.1", 8443))
        self.assertIsNone(cli._loopback(None))
        for value in ("192.0.2.1:443", "10.0.0.1:443"):
            with self.assertRaises(ValueError):
                cli._loopback(value)


if __name__ == "__main__":
    unittest.main()
