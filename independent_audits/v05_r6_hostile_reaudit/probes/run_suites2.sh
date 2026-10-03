#!/bin/bash
S=${AUDIT_WORK:?set AUDIT_WORK to the audit scratch directory holding the worktrees cand/, r5audit/, probes/, ev/}
C=$S/cand
cd $S/probes
# 1. independent audit hook over the whole adapter suite (R5 harness, unchanged)
PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B run_nonet.py $C > $S/ev/nonet_py311.json 2>$S/ev/nonet_py311.stderr
# 2. loopback-only network namespace
unshare -rn python3.11 netns_run.py $C > $S/ev/netns_suite_py311.txt 2>&1; echo "rc=$?" >> $S/ev/netns_suite_py311.txt
# 3. quiet frozen-suite rerun
cd $C; echo "=== frozen suite python3.11 quiet rerun start $(date -u +%FT%TZ)" > $S/ev/frozen_suite_py311_quiet.txt
PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest discover -s tests -t . -v >> $S/ev/frozen_suite_py311_quiet.txt 2>&1
echo "=== rc=$? end $(date -u +%FT%TZ)" >> $S/ev/frozen_suite_py311_quiet.txt
git -C $C status --porcelain > $S/ev/worktree_status_after_suites2.txt
echo DONE > $S/ev/suites2.done
