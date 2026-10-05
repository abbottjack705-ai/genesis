"""Audit probe bootstrap.

Imports the audited candidate tree READ-ONLY (never modified) and its test-support harness.
  CAND_DIR       tree to attack (default: the repository root that contains independent_audits/)
  AUDIT_SCRATCH  scratch/output directory (default: /tmp/v05_audit_scratch)
Run every probe with:  PYTHONPYCACHEPREFIX=$(mktemp -d) python -B <probe>.py   (the candidate's FRZ-09 guard requires it)
"""
import os, sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent
CAND = os.environ.get("CAND_DIR") or str(HERE.parents[2])
SP = os.environ.get("AUDIT_SCRATCH", "/tmp/v05_audit_scratch")
os.makedirs(SP + "/out", exist_ok=True)
sys.path.insert(0, str(HERE))                  # indep_scan
os.chdir(CAND)
sys.path.insert(0, CAND + "/adapters")
import adapter_tests               # sets sys.path for src + adapters/src, runs the provenance guard, installs the network hook
from adapter_tests.support import *            # noqa
from adapter_tests.pipeline_support import *   # noqa
from adapter_tests import pipeline_support as PS, parser_support as parp, emit_support as ES
from genesis_adapters.errors import AdapterFailure as F
from genesis_adapters.oddspapi.reader import admissible_head, UsableBook
