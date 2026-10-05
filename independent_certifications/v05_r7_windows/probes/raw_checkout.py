"""Compare every tracked candidate file's raw bytes with its Git blob."""
import hashlib, subprocess, sys
from pathlib import Path
candidate = Path(sys.argv[1]).resolve()
head = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
rows = subprocess.check_output(["git", "-C", str(candidate), "ls-files", "--stage", "-z"]).split(b"\0")
pairs = [(row.split(b"\t", 1)[0].split()[1].decode(), row.split(b"\t", 1)[1].decode())
         for row in rows if row]
bad = []
for expected, relative in pairs:
    data = (candidate / relative).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != expected:
        bad.append(relative)
print("HEAD", head)
print("TRACKED", len(pairs), "RAW_BLOB_MISMATCHES", len(bad))
print("MISMATCHES", bad[:20])
print("CORE_AUTOCRLF", subprocess.check_output(
    ["git", "-C", str(candidate), "config", "--get", "core.autocrlf"], text=True).strip())
assert head == "be898d3865685ac0261cdb255008db902b030521"
assert not bad
