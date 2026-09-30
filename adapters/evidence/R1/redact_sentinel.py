"""Replace every occurrence of the known test-sentinel forms in an evidence transcript by <SENTINEL-FORM>, then prove
with the implementation's section-7.6 scanner that no line still carries any form. Prints the substitution count.

usage (repo root, PYTHONPATH=adapters, -B, fresh PYTHONPYCACHEPREFIX): python -B redact_sentinel.py FILE [FILE ...]
The sentinel is the fixed PUBLIC test constant of adapter_tests/support.py, never a credential; it is withheld only
so evidence stays clean under the auditor's secret sweep, as the S0-S7 evidence is.
"""

import sys
from pathlib import Path

import adapter_tests  # noqa: F401  (path setup and guard)
from adapter_tests import parser_support as ps
from adapter_tests.support import SENTINEL_KEY

from genesis_adapters.secrets import Secret, SecretScanner

TOKEN = "<SENTINEL-FORM>"
FORMS = sorted({
    "Err_" + SENTINEL_KEY.replace("-", "_"),                      # the identifier form (TX-01 / R-1)
    SENTINEL_KEY.replace("-", "_"),
    SENTINEL_KEY,
    SENTINEL_KEY.lower(),
    SENTINEL_KEY.encode().hex(),
    "".join(f"%{byte:02X}" for byte in SENTINEL_KEY.encode()),
    SENTINEL_KEY[-16:],                                           # the fragment form
}, key=len, reverse=True)
scanner = SecretScanner(Secret(SENTINEL_KEY), policy=ps.POLICY)

SHORTEST = 12                                    # also every run of >= 12 chars of a form (unittest truncates diffs)

for name in sys.argv[1:]:
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    count = 0
    for form in FORMS:
        for length in range(len(form), SHORTEST - 1, -1):
            for start in range(len(form) - length + 1):
                piece = form[start:start + length]
                if piece in text:
                    count += text.count(piece)
                    text = text.replace(piece, TOKEN)
    left = [number for number, line in enumerate(text.splitlines(), 1) if scanner.scan(line.encode()).hit]
    if left:
        raise SystemExit(f"{name}: lines still carrying a form after substitution: {left}")
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"{name}: {count} substitutions; scanner hits after substitution: 0")
