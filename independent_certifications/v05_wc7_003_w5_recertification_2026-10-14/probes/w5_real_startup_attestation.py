import json, os, sys

clean_src = r"C:\Users\abbot\fz\w5rc\adapters\src"
sys.path.insert(0, clean_src)
from genesis_adapters import cli  # imported from the clean checkout, not mocked

out = sys.argv[1]
assert sys.platform == "win32", sys.platform
result = cli.time_sync_attestation()  # real production Windows path: real subprocess.run for w32tm
record = {"genesis_module_file": cli.__file__, "time_sync_attestation": result}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(record, fh, indent=1, sort_keys=True)
print(json.dumps(record, indent=1, sort_keys=True))
