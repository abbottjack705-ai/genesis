#!/usr/bin/env bash
# Complete the b22263e hostile re-audit on a host that holds the candidate (Git Bash on Windows, or Linux).
#   bash run_all.sh <repo-with-b22263e> <out-dir> [<prior-package-dir>]
# <prior-package-dir> = the 37b86fb package (audit/v05_slice1_hostile); extracted from git if omitted.
# Run ALONE on the host (no parallel audit or suite): the 37b86fb audit lost its adapter-suite and mutation
# runs to host memory exhaustion.
set -u
REPO="$(cd "${1:?repo}" && pwd)"; OUT="${2:?out dir}"; PRIOR="${3:-}"
CAND=b22263e; PRED=cfcff3dbb285eaa48a6cfc1eceedb91e27662c81
HERE="$(cd "$(dirname "$0")" && pwd)"; PY="${PYTHON:-python}"
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) FROZEN=493:1 ;; *) FROZEN=493:19 ;; esac
log() { echo "=== $*" | tee -a "$OUT/RUN_ALL.log"; }

log "0 pin"; git -C "$REPO" rev-parse --verify "$CAND^{commit}" | tee "$OUT/candidate.sha" || { echo "candidate absent"; exit 2; }
FULL="$(cat "$OUT/candidate.sha")"
if [ -z "$PRIOR" ]; then
  PRIOR="$OUT/prior"; mkdir -p "$PRIOR"
  git -C "$REPO" archive 37b86fbf825cf0e0a754f918afa184ce791cfa12 audit/v05_slice1_hostile | tar -x -C "$PRIOR" \
    && PRIOR="$PRIOR/audit/v05_slice1_hostile" || { echo "prior package not found; pass it as arg 3"; exit 2; }
fi
CLEAN="$OUT/cand"; rm -rf "$CLEAN"
git -c core.autocrlf=false clone -q --no-hardlinks --no-checkout "$REPO" "$CLEAN" && git -C "$CLEAN" config core.autocrlf false \
  && git -C "$CLEAN" checkout -q --detach "$FULL"
export PYTHONPYCACHEPREFIX="$(mktemp -d)"

log "1 candidate-independent driver (identity, FRZ-09, CRLF, static, secrets, export, test IDs, suites, no-network)"
"$PY" "$HERE/run_reaudit.py" --repo "$REPO" --candidate "$FULL" --predecessor "$PRED" --out "$OUT/driver" \
  --expect-frozen "$FROZEN" --expect-adapter 690:1 2>&1 | tee "$OUT/driver.txt"

log "2 prior independent oracle (37b86fb), unchanged"
(cd "$PRIOR/oracle" && bash run_oracle.sh "$CLEAN" "$FULL" "$OUT/oracle") 2>&1 | tee "$OUT/oracle.txt"

log "3 prior attacks (37b86fb a01-a15) re-run against the candidate"
CRLF="$OUT/cand_crlf"; rm -rf "$CRLF"
git -c core.autocrlf=true clone -q --no-hardlinks --no-checkout "$REPO" "$CRLF" && git -C "$CRLF" config core.autocrlf true \
  && git -C "$CRLF" checkout -q --detach "$FULL"
for a in a01_manifest_crlf a02_a03_crash_matrix a04_a05_reader_parity a06_secrets_pipeline a08_schema_status \
         a10_immutability a11_windows_credential a12_tls_ca a13_ready_backdate a14_gate_limits a15_mutation; do
  case "$a" in
    a01_manifest_crlf)     extra="--crlf-repo $CRLF" ;;
    a04_a05_reader_parity) extra="--expected $PRIOR/oracle/EXPECTED_PIT_HEADS.json" ;;
    a06_secrets_pipeline)  extra="--corpus $PRIOR/oracle/SECRET_CORPUS.json" ;;
    a12_tls_ca)            extra="--commit $FULL" ;;
    *)                     extra="" ;;
  esac
  "$PY" -B "$PRIOR/attacks/$a.py" --repo "$CLEAN" $extra --out "$OUT/$a.json" > "$OUT/$a.log" 2>&1
  echo "$a exit=$?" | tee -a "$OUT/RUN_ALL.log"
done
"$PY" -B "$PRIOR/attacks/a07_transport_time.py" --repo "$CLEAN" --edges "$PRIOR/oracle/EXPECTED_BOUNDARY_EDGES.json" \
  --out "$OUT/a07.json" > "$OUT/a07.log" 2>&1; echo "a07 exit=$?" | tee -a "$OUT/RUN_ALL.log"

log "4 re-audit probes p20-p25 (remediation-specific)"
for p in p20_deadline_stages p21_rejected_restart p22_invalidation_selfheal p23_f44_protective_halts \
         p24_tournament_omission p25_operator_authority; do
  "$PY" -B "$HERE/probes/$p.py" --repo "$CLEAN" --out "$OUT/$p.json" > "$OUT/$p.log" 2>&1
  echo "$p exit=$? (0 pass, 1 fail, 2 cannot-run)" | tee -a "$OUT/RUN_ALL.log"
done

log "5 diff-site mutation run cfcff3d..b22263e (alone on the host; hours)"
"$PY" "$HERE/mutate_sites.py" --repo "$CLEAN" --base "$PRED" --head "$FULL" --paths adapters/src \
  --test-cmd "$PY -B -m unittest discover -s adapters/adapter_tests -t adapters" --timeout 1800 \
  --out "$OUT/mutants.json" 2>&1 | tee "$OUT/mutants.txt"

log "6 real symlink (HA-004) - needs SeCreateSymbolicLinkPrivilege / Developer Mode"
"$PY" -B "$PRIOR/attacks/a11_windows_credential.py" --repo "$CLEAN" --out "$OUT/a11_privileged.json" \
  > "$OUT/a11_privileged.log" 2>&1; echo "a11 exit=$?"; grep -i symlink "$OUT/a11_privileged.log" | tee -a "$OUT/RUN_ALL.log"

(cd "$OUT" && find . -type f ! -name RESULTS_MANIFEST.sha256 ! -path './cand/*' ! -path './cand_crlf/*' ! -path './prior/*' -print0 \
  | sort -z | xargs -0 sha256sum) > "$OUT/RESULTS_MANIFEST.sha256"
log "done: $OUT (see RESULTS_MANIFEST.sha256)"
