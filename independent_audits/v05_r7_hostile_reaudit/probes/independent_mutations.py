from __future__ import annotations
import os, re, subprocess, sys, tempfile
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
assert repo.name == "r7-mutant" and repo.joinpath(".git").exists(), repo
pin = "b2eabac1da9ed3989de966583a51d97b3834aa9c"
assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip() == pin
prefix = "adapter_tests."
specs = [
 ("A01 settle only first historical verdict", "acquisition.py",
  "for aid, position in sorted(last.items(), key=lambda pair: pair[1]):",
  "for aid, position in sorted(last.items(), key=lambda pair: pair[1])[:1]:",
  prefix + "test_v05_r7_rejection_crash.EveryOlderVerdictIsSettledTests.test_older_unsettled_verdict_is_recovered_when_the_later_verdict_is_already_settled"),
 ("A02 lose divergence on an independently malformed response", "acquisition.py",
  'if failure != AdapterFailure.QUOTA_DIVERGENCE and usage_diverges(verdict["provider_reported_usage"]):',
  'if failure is None and usage_diverges(verdict["provider_reported_usage"]):',
  prefix + "test_v05_r7_quota_divergence.TheResponseIsUnusableInEveryRunOrderTests.test_a_response_that_failed_for_another_reason_keeps_that_reason_and_still_halts"),
 ("A03 allow mismatched hostname", "transport_http.py",
  "context.check_hostname = True",
  "context.check_hostname = False",
  prefix + "test_v05_r6_tls_boundary.ProductionContextConstructionTests.test_verification_and_host_name_checking_are_still_required"),
 ("A04 grant resolver extra 100ms past absolute deadline", "transport_http.py",
  "worker.join(self._left())",
  "worker.join(self._left() + 0.1)",
  prefix + "test_v05_r7_resolution_deadline.ResolutionIsBoundedByTheDeadlineTests.test_the_lookup_is_joined_with_exactly_the_time_that_is_left_no_spare_second"),
 ("A05 hide conflicting rejection coverage from quiescence", "acquisition.py",
  "elif not all(_says_the_same(entry, wanted) for entry in found):",
  "elif False and not all(_says_the_same(entry, wanted) for entry in found):",
  prefix + "test_v05_r7_rejection_crash.ConflictingEvidenceFailsClosedTests.test_an_entry_with_the_intended_id_but_other_content_refuses_every_start"),
]
def run(target):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "adapters"), str(repo / "adapters" / "src"), str(repo / "src")])
    env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="genesis-r7-mut-pycache-")
    result = subprocess.run([sys.executable, "-B", "-m", "unittest", target, "-v"], cwd=repo, env=env,
                            capture_output=True, text=True, timeout=180, errors="replace")
    output = result.stdout + result.stderr
    ran = re.search(r"Ran (\d+) tests?", output)
    if not ran or int(ran.group(1)) != 1:
        return "HARNESS_ERROR", output[-500:]
    method = target.rsplit(".", 1)[-1]
    failed = re.search(rf"^(FAIL|ERROR): {re.escape(method)}(?:\s|\()", output, re.MULTILINE)
    if result.returncode == 0:
        return "SURVIVED", "one test passed"
    if failed:
        return "KILLED", f"named target {method} failed"
    return "HARNESS_ERROR", output[-500:]

print("pin", pin)
for label, _module, _old, _new, target in specs:
    status, detail = run(target)
    print("NOOP", label, status, detail, flush=True)
    if status != "SURVIVED":
        raise SystemExit("no-op control failed")
bad = 0
for label, module, old, new, target in specs:
    path = repo / "adapters" / "src" / "genesis_adapters" / "oddspapi" / module
    original = path.read_bytes()
    source = original.decode("utf-8")
    assert source.count(old) == 1, (label, source.count(old))
    try:
        path.write_bytes(source.replace(old, new).encode("utf-8"))
        status, detail = run(target)
    finally:
        path.write_bytes(original)
    print(status, label, detail, flush=True)
    bad += status != "KILLED"
print(f"summary {len(specs)-bad}/{len(specs)} killed; {bad} survivors/harness issues")
raise SystemExit(1 if bad else 0)
