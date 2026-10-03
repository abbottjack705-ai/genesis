#!/bin/bash
S=${AUDIT_WORK:?set AUDIT_WORK to the audit scratch directory holding the worktrees cand/, r5audit/, probes/, ev/}
cd $S/probes
CAND_DIR=$S/cand AUDIT_SCRATCH=$S/ascratch_r5p PROBE_OUT=$S/ev/r5probes_on_R6 ./run_r5_probes_on_R6.sh > $S/ev/r5probes_on_R6/_runner.log 2>&1
# implementer's 17-probe controlling-audit script: unadapted (FINAL variant) and R6-adapted, against R6
cd $S/cand
for v in FINAL:repro_controlling_final.py.txt R6:repro_controlling_final_r6.py.txt; do
  tag=${v%%:*}; f=${v#*:}
  src=adapters/evidence/$tag/scripts/$f
  cp $src $S/ascratch/repro_$tag.py
  PYTHONPATH=adapters PYTHONPYCACHEPREFIX=$(mktemp -d) timeout 1800 python3.11 -B $S/ascratch/repro_$tag.py > $S/ev/repro17_${tag}_variant_on_R6.txt 2>&1
done
echo DONE > $S/ev/crosscheck.done
