"""Certification-only short-checkout and long runtime/evidence path probe."""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

candidate = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(candidate / "adapters" / "src"))

from genesis_adapters.oddspapi.quiescence import run_lock  # noqa: E402

head = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
print("REPOSITORY_ROOT", candidate)
print("REPOSITORY_ROOT_LENGTH", len(str(candidate)))
print("GIT_HEAD", head)
assert head == "be898d3865685ac0261cdb255008db902b030521"

with tempfile.TemporaryDirectory(prefix="genesis-r7-shortpath-") as temporary:
    deep = Path(temporary) / ("r" * 72) / ("s" * 72) / ("t" * 72)
    runtime = deep / "runtime"
    evidence = deep / "evidence" / "sample.sha256"
    evidence.parent.mkdir(parents=True)
    with run_lock(runtime):
        evidence.write_bytes(b"synthetic-evidence\n")
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with run_lock(runtime):
        lock_released = True
    print("RUNTIME_LENGTH", len(str(runtime)))
    print("EVIDENCE_LENGTH", len(str(evidence)))
    print("EVIDENCE_SHA256", digest)
    print("RUN_LOCK_REACQUIRED", lock_released)
    assert len(str(runtime)) > 260 and len(str(evidence)) > 260
    assert digest == hashlib.sha256(b"synthetic-evidence\n").hexdigest()

print("TEMPORARY_PATHS_REMOVED", not Path(temporary).exists())
