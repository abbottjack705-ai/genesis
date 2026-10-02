"""Re-audit network block: a ``sys.addaudithook`` that refuses every non-loopback connect / resolve.

Installed in-process by ``netblock.py`` and in every child Python process through ``sitecustomize.py``
on ``PYTHONPATH`` (children started with ``-I``/``-E``/``-S`` are not covered; the log records the pid of
every process that did install it, so coverage is visible). Every attempt is appended to the JSON-lines
file named by ``REAUDIT_NETLOG`` (host, port, event, loopback flag). A refused attempt raises
``PermissionError`` - an ordinary ``OSError`` - at the call site.
"""

from __future__ import annotations

import json
import os
import socket
import sys

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_INSTALLED = "_reaudit_netblock_installed"


def _is_loopback(host) -> bool:
    if host is None:
        return True                                   # getaddrinfo(None, ...) = local wildcard
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host in LOOPBACK_NAMES or host == "::1" or host.startswith("127.") or host in {"", "0.0.0.0", "::"}:
        return True
    return host.startswith("::ffff:127.")


def _log(entry: dict) -> None:
    path = os.environ.get("REAUDIT_NETLOG")
    if not path:
        return
    entry["pid"] = os.getpid()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _hook(event: str, args: tuple) -> None:
    if event == "socket.connect" or event == "socket.sendto":
        sock, address = args[0], args[-1]
        family = getattr(sock, "family", None)
        if hasattr(socket, "AF_UNIX") and family == socket.AF_UNIX:
            return
        host, port = (address[0], address[1]) if isinstance(address, tuple) and len(address) >= 2 else (address, None)
    elif event == "socket.getaddrinfo":
        host, port = args[0], args[1]
    elif event in {"socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"}:
        host, port = args[0], None
    else:
        return
    loopback = _is_loopback(host)
    _log({"event": event, "host": str(host), "port": port, "loopback": loopback})
    if not loopback:
        raise PermissionError(f"re-audit netblock: {event} to a non-loopback host refused")


def install() -> None:
    if getattr(sys, _INSTALLED, False):
        return
    setattr(sys, _INSTALLED, True)
    sys.addaudithook(_hook)
    _log({"event": "netblock.installed", "host": "", "port": None, "loopback": True,
          "argv0": (sys.argv[0] if sys.argv else "")})
