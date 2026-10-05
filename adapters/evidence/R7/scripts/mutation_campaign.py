#!/usr/bin/env python3
"""Run the R7 focused mutation campaign serially and restore each source file byte-for-byte.

Each mutant is tied to a named R7 regression. A mutant is KILLED only when that test method ran and unittest reported
that exact method as FAIL or ERROR. Import failures, zero-test runs, timeouts, and other harness failures are reported
separately and never counted as kills.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "adapters" / "evidence" / "R7" / "MUTATION.txt"
R = "adapters/src/genesis_adapters/oddspapi/"
REJECTION = "adapter_tests.test_v05_r7_rejection_crash."
QUOTA = "adapter_tests.test_v05_r7_quota_divergence."
TLS = "adapter_tests.test_v05_r7_tls_context."
DNS = "adapter_tests.test_v05_r7_resolution_deadline."


def test(module: str, klass: str, method: str) -> str:
    return f"{module}{klass}.{method}"


OLDER_GAP = test(REJECTION, "EveryOlderVerdictIsSettledTests",
                 "test_older_unsettled_verdict_is_recovered_when_the_later_verdict_is_already_settled")

MUTANTS = [
    (
        "R01a only settle the latest verdict across all attempts",
        R + "acquisition.py",
        "        for aid, position in sorted(last.items(), key=lambda pair: pair[1]):",
        "        for aid, position in sorted(last.items(), key=lambda pair: pair[1])[-1:]:",
        [OLDER_GAP],
    ),
    (
        "R01b restore the historical newest-planned-only settlement algorithm",
        R + "acquisition.py",
        """        rows = self.ledger.rows()
        last: dict[str, int] = {}
        for index, row in enumerate(rows):
            aid = row.get("acquisition_id")
            if aid is not None and _is_verdict(row):
                last[aid] = index
        if not last:
            return
        attempts = _replay(rows)
        coverage = _CoverageIndex(self.coverage)
        for aid, position in sorted(last.items(), key=lambda pair: pair[1]):
            if self._settle_at(aid, rows, position, attempts[aid], coverage)[1]:
                rows = self.ledger.rows()                   # what was just written is part of what the next one is judged by""",
        """        last = None
        for row in self.ledger.rows():
            if row["record_type"] == "acq_planned":
                last = row["acquisition_id"]
        if last is not None:
            self.settle(last)""",
        [OLDER_GAP],
    ),
    (
        "R02 do not recognize derivation rejection as a verdict to settle",
        R + "acquisition.py",
        '_VERDICT_ROWS = ("acq_refused", "acq_completed", "acq_reconciled", "acq_derivation_rejected")',
        '_VERDICT_ROWS = ("acq_refused", "acq_completed", "acq_reconciled")',
        [OLDER_GAP],
    ),
    (
        "R03 do not report missing rejection coverage as pending work",
        "adapters/src/genesis_adapters/oddspapi/quiescence.py",
        "    if missing:\n        found.append(\"a derivation rejection's coverage entry is not recorded yet\")",
        "    if False and missing:\n        found.append(\"a derivation rejection's coverage entry is not recorded yet\")",
        [OLDER_GAP],
    ),
    (
        "R04 adopt contradictory coverage under a rejection's deterministic id",
        R + "acquisition.py",
        "                    if not all(_says_the_same(row, entry) for row in found):",
        "                    if False and not all(_says_the_same(row, entry) for row in found):",
        [test(REJECTION, "ConflictingEvidenceFailsClosedTests",
              "test_an_entry_with_the_intended_id_but_other_content_refuses_every_start")],
    ),
    (
        "R05 fail to persist quota divergence in the completed verdict",
        R + "acquisition.py",
        "        if failure is None and usage_diverges(usage):",
        "        if False and failure is None and usage_diverges(usage):",
        [test(QUOTA, "TheResponseIsUnusableInEveryRunOrderTests",
              "test_the_verdict_is_in_the_durable_row_itself_not_in_a_flag_a_process_remembers")],
    ),
    (
        "R06 treat usage equal to the debit as divergent",
        R + "acquisition.py",
        'usage["reported"] > usage["genesis_debited"]',
        'usage["reported"] >= usage["genesis_debited"]',
        [test(QUOTA, "TheResponseIsUnusableInEveryRunOrderTests", "test_a_usage_within_the_debit_is_never_a_divergence")],
    ),
    (
        "R07 allow an earlier usage-only divergence row to become usable",
        R + "derivation.py",
        'and not usage_diverges(completed["provider_reported_usage"]))',
        'and True)',
        [test(QUOTA, "AnEarlierCodeVersionsLedgerIsHonouredTests",
              "test_such_a_row_is_not_a_successful_capture_and_no_start_derives_it")],
    ),
    (
        "R08 omit the quota-divergence halt and coverage effects",
        R + "acquisition.py",
        '    elif failure == AdapterFailure.QUOTA_DIVERGENCE:         # the divergence IS this response\'s verdict (F-37: none; halt)\n        effects += [("halted", failure), _coverage_effect(failure)]',
        '    elif False and failure == AdapterFailure.QUOTA_DIVERGENCE:         # the divergence IS this response\'s verdict (F-37: none; halt)\n        effects += [("halted", failure), _coverage_effect(failure)]',
        [test(QUOTA, "TheResponseIsUnusableInEveryRunOrderTests", "test_the_coverage_entry_is_the_one_f37_names_and_exactly_one")],
    ),
    (
        "R09 trust the environment-selected CA file",
        R + "transport_http.py",
        "cafile = paths.openssl_cafile if paths.openssl_cafile and os.path.isfile(paths.openssl_cafile) else None",
        "cafile = paths.cafile if paths.cafile and os.path.isfile(paths.cafile) else None",
        [test(TLS, "TheEnvironmentIsNeitherWrittenNorReadTests",
              "test_no_environment_variable_changes_what_is_trusted_or_written")],
    ),
    (
        "R10 leave the TLS floor dependent on platform defaults",
        R + "transport_http.py",
        "context.minimum_version = ssl.TLSVersion.TLSv1_2",
        "context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED",
        [test(TLS, "PlatformTrustAndFloorTests", "test_the_floor_is_stated_not_inherited")],
    ),
    (
        "R11 let SSLKEYLOGFILE set process-global key logging",
        R + "transport_http.py",
        "context.keylog_filename = None",
        "context.keylog_filename = os.environ.get(\"SSLKEYLOGFILE\")",
        [test(TLS, "TheEnvironmentIsNeitherWrittenNorReadTests",
              "test_building_the_context_writes_nothing_and_never_looks_at_the_key_log_variable")],
    ),
    (
        "R12 omit Windows system trust stores",
        R + "transport_http.py",
        "    if sys.platform == \"win32\":\n        _load_windows_stores(context)",
        "    if False and sys.platform == \"win32\":\n        _load_windows_stores(context)",
        [test(TLS, "WindowsSystemStoresTests", "test_the_system_stores_are_loaded_and_the_environment_still_adds_nothing")],
    ),
    (
        "R13 wait for the resolver without the remaining deadline",
        R + "transport_http.py",
        "        worker.join(self._left())",
        "        worker.join()",
        [test(DNS, "ResolutionIsBoundedByTheDeadlineTests",
              "test_a_resolver_that_never_answers_costs_the_deadline_not_the_resolvers_patience")],
    ),
    (
        "R14 run the abandoned resolver as a non-daemon thread",
        R + "transport_http.py",
        'worker = threading.Thread(target=lookup, name="genesis-adapters-resolve", daemon=True)',
        'worker = threading.Thread(target=lookup, name="genesis-adapters-resolve", daemon=False)',
        [test(DNS, "ResolutionIsBoundedByTheDeadlineTests",
              "test_the_abandoned_lookup_is_a_daemon_that_was_given_only_the_host_and_the_port")],
    ),
    (
        "R15 start a resolver lookup after its deadline already passed",
        R + "transport_http.py",
        "        self._left()                                        # a deadline already gone starts nothing",
        "        pass                                                # mutation: skip the expired-deadline check",
        [test(DNS, "ResolutionIsBoundedByTheDeadlineTests",
              "test_a_deadline_that_has_already_passed_starts_no_lookup_at_all")],
    ),
]


def run_mutant(label: str, relative: str, old: str, new: str, tests: list[str]) -> tuple[str, str]:
    path = REPO / relative
    original = path.read_bytes()
    source = original.decode("utf-8")
    if source.count(old) != 1:
        return "BAD_SPEC", f"anchor occurs {source.count(old)} times: {label}"
    if old == new:
        return "BAD_SPEC", f"replacement is unchanged: {label}"

    try:
        path.write_bytes(source.replace(old, new).encode("utf-8"))
        test_results = []
        for target in tests:
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(str(REPO / item) for item in ("adapters", "adapters/src", "src"))
            env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="genesis-r7-mutant-pycache-")
            try:
                proc = subprocess.run([sys.executable, "-u", "-B", "-m", "unittest", target, "-v"],
                                      cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return "HARNESS_ERROR", f"test timed out: {label} / {target}"
            output = proc.stdout + proc.stderr
            ran = re.search(r"Ran (\d+) tests?", output)
            if ran is None or int(ran.group(1)) != 1:
                return "HARNESS_ERROR", f"expected one test; got {ran.group(1) if ran else 'no count'}: {label} / {target}\n{output[-1500:]}"
            if re.search(r"\.\.\. skipped", output):
                return "HARNESS_ERROR", f"target regression was skipped: {label} / {target}"
            method = target.rsplit(".", 1)[-1]
            failed = re.search(rf"^(?:FAIL|ERROR): {re.escape(method)}(?:\s|\()", output, re.MULTILINE)
            if proc.returncode != 0 and failed:
                test_results.append(f"KILLED by {method}")
            elif proc.returncode == 0:
                return "SURVIVED", f"target test passed: {label} / {target}"
            else:
                return "HARNESS_ERROR", f"failure did not name target test: {label} / {target}\n{output[-1500:]}"
        return "KILLED", "; ".join(test_results)
    finally:
        path.write_bytes(original)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for label, relative, old, new, _tests in MUTANTS:
        source = (REPO / relative).read_bytes().decode("utf-8")
        count = source.count(old)
        if count != 1 or old == new:
            raise SystemExit(f"BAD_SPEC before campaign: {label}; anchor_count={count}; replacement_changed={old != new}")
    results = [
        f"R7 focused mutation campaign; {sys.version.split()[0]} ({sys.executable})",
        "Each mutant ran serially against its named unittest regression; source bytes restored in finally.",
        "KILLED requires the target method to run and be reported by unittest as FAIL or ERROR.",
        "",
    ]
    bad = 0
    for label, relative, old, new, tests in MUTANTS:
        verdict, detail = run_mutant(label, relative, old, new, tests)
        results.append(f"{verdict}: {label} — {detail}")
        print(results[-1], flush=True)
        if verdict != "KILLED":
            bad += 1
    results.extend(("", f"Summary: {len(MUTANTS) - bad}/{len(MUTANTS)} killed; {bad} survivor or harness/spec issue."))
    OUT.write_text("\n".join(results) + "\n", encoding="utf-8", newline="\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
