#!/usr/bin/env python3
"""Run ``python -m <module> ...`` with the re-audit network block installed (see netblock_site/).

    REAUDIT_NETLOG=net.jsonl python -B netblock.py -m unittest discover -s tests -t .

The block is also inherited by child Python processes when ``PYTHONPATH`` contains ``netblock_site``
(``run_reaudit.py`` sets both). Exit status is the wrapped module's.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent / "netblock_site"


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "-m":
        raise SystemExit("usage: netblock.py -m <module> [args...]")
    if str(SITE) not in sys.path:
        sys.path.append(str(SITE))                    # appended: never shadows the code under test
    import reaudit_netblock_core

    reaudit_netblock_core.install()
    module = sys.argv[2]
    sys.argv = [module, *sys.argv[3:]]
    sys.path[0] = os.getcwd()                         # exactly what `python -m` puts first (not this script's dir)
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
