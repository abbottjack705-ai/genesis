"""Self-contained synthetic research programs for protected-process tests.

T5 executes only the hashed program module plus trusted runtime (the standard
library and the Genesis package) inside the label-free research worker. These
retained programs were moved verbatim out of ``test_astra_s5_process.py`` and
``test_remediation_r9_protected.py``, whose top-level imports of other test
modules would otherwise run unhashed code inside the worker. Their bodies,
names and observable results are unchanged.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from genesis.labels import DecisionFrame


# Set only by the trusted parent test process. A fresh research worker
# executes this module's bytes anew, so these remain empty there.
PARENT_LABEL_SENTINEL = None
PARENT_PROBE_PATH = None
FORBIDDEN_LABEL_ENV = "GENESIS_ASTRA_FORBIDDEN_LABEL_PATH"


def signal_program(frame: DecisionFrame) -> str:
    return "0.9" if frame.values()["signal"] else "0.1"


def half_program(_frame: DecisionFrame) -> str:
    return "0.5"


def exception_program(_frame: DecisionFrame) -> str:
    raise RuntimeError("TOP-SECRET research detail")


def failing_program(_frame: DecisionFrame) -> str:
    raise RuntimeError("secret detail")


def crash_program(_frame: DecisionFrame) -> str:
    os._exit(31)


def slow_program(_frame: DecisionFrame) -> str:
    time.sleep(11)
    return "0.5"


def hostile_parent_probe(frame: DecisionFrame) -> str:
    """Observe data reachable only when this callback runs in the trusted parent."""

    saw_parent_label = bool(PARENT_LABEL_SENTINEL)
    saw_label_file = False
    label_path = os.environ.get(FORBIDDEN_LABEL_ENV)
    if label_path:
        try:
            saw_label_file = "TOP-SECRET-LABEL" in Path(label_path).read_text(encoding="utf-8")
        except OSError:
            pass
    if PARENT_PROBE_PATH:
        Path(PARENT_PROBE_PATH).write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "saw_parent_label": saw_parent_label,
                    "saw_label_file": saw_label_file,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    if saw_parent_label or saw_label_file:
        return "0.77"
    return signal_program(frame)
