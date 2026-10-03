#!/bin/bash
# Sequential suite runs against the pinned candidate worktree (read-only use).
S=${AUDIT_WORK:?set AUDIT_WORK to the audit scratch directory holding the worktrees cand/, r5audit/, probes/, ev/}
C=$S/cand
cd $C
for PY in python3.11 python3.12 python3.13; do
  echo "=== $PY adapter suite start $(date -u +%FT%TZ)" > $S/ev/adapter_suite_$PY.txt
  PYTHONPYCACHEPREFIX=$(mktemp -d) $PY -B -m unittest discover -s adapters/adapter_tests -t adapters -v >> $S/ev/adapter_suite_$PY.txt 2>&1
  echo "=== rc=$? end $(date -u +%FT%TZ)" >> $S/ev/adapter_suite_$PY.txt
done
echo "=== frozen suite python3.11 start $(date -u +%FT%TZ)" > $S/ev/frozen_suite_py311.txt
PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest discover -s tests -t . -v >> $S/ev/frozen_suite_py311.txt 2>&1
echo "=== rc=$? end $(date -u +%FT%TZ)" >> $S/ev/frozen_suite_py311.txt
git -C $C status --porcelain > $S/ev/worktree_status_after_suites.txt
for t in src tests config tools DECISIONS v04_pack adapters; do echo "$t $(git -C $C rev-parse HEAD:$t)"; done >> $S/ev/worktree_status_after_suites.txt
echo DONE > $S/ev/suites.done
