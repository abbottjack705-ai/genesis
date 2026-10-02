"""Loaded automatically by every child Python process that has this directory on PYTHONPATH."""

import os

if os.environ.get("REAUDIT_NETLOG"):
    import reaudit_netblock_core

    reaudit_netblock_core.install()
