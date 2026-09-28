"""Adapter test package bootstrap.

Puts the frozen ``src`` and the adapter ``adapters/src`` on ``sys.path`` (the same way
``tests/__init__.py`` does for ``src``), then runs the runtime module-provenance guard
(FRZ-09, design section 2.4) BEFORE any test module imports ``genesis``. A second,
suite-level check runs in ``test_v05_zz_final_provenance`` once every module is loaded.

The documented command isolates bytecode, which the guard requires:

    PYTHONPYCACHEPREFIX=<fresh temp dir> python -B -m unittest discover \
        -s adapters/adapter_tests -t adapters -v
"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _entry in (REPO / "adapters" / "src", REPO / "src"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from genesis_adapters import provenance_guard as _guard  # noqa: E402  (no genesis import)
from genesis_adapters.oddspapi import verify as _verify  # noqa: E402  (no genesis import at top)

GUARD_VERDICT = _guard.verify_loaded_genesis_modules(
    REPO,
    manifest_path=REPO / "adapters" / "config" / "frozen_genesis_modules.json",
    expected_manifest_sha256=_verify.FROZEN_MANIFEST_SHA256,
)

# --- network isolation for the whole adapter suite (design section 19, S7) ---------------
# No adapter test may contact anything but the loopback interface. The hook cannot be
# removed once installed; violations raise and are recorded.
NON_LOOPBACK_ATTEMPTS: list[tuple[str, str]] = []


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _audit(event: str, args: tuple) -> None:
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and address and not _is_loopback(address[0]):
            NON_LOOPBACK_ATTEMPTS.append((event, "<non-loopback address>"))
            raise RuntimeError("adapter tests may not contact a non-loopback address")
    elif event == "socket.getaddrinfo":
        if not _is_loopback(args[0]):
            NON_LOOPBACK_ATTEMPTS.append((event, "<non-loopback name>"))
            raise RuntimeError("adapter tests may not resolve a non-loopback name")


sys.addaudithook(_audit)
