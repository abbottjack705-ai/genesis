#!/usr/bin/env bash
# Run the whole independent oracle against a candidate checkout.
#   ./run_oracle.sh <repo-path> <candidate-commit> [<out-dir>]
set -u
REPO="${1:?repo path}"; COMMIT="${2:?commit}"; OUT="${3:-oracle_out}"
HERE="$(cd "$(dirname "$0")" && pwd)"; mkdir -p "$OUT"
STAGES="63e06a1,1bc6001,78bedb9,b95465e,9de0790,ff7f4ba,9c35c5c,cfcff3d"
run() { name="$1"; shift; echo "=== $name"; "$@" > "$OUT/$name.txt" 2>&1; echo "exit=$?" | tee -a "$OUT/$name.txt"; }
run 01_frozen_identity  python3 "$HERE/oracle_frozen_identity.py" --repo "$REPO" --commit "$COMMIT" --stages "$STAGES" --json "$OUT/01_frozen_identity.json"
run 02_provenance_crlf  python3 "$HERE/oracle_provenance_crlf.py" --repo "$REPO" --json "$OUT/02_provenance_crlf.json"
run 04_pit_head_expected python3 "$HERE/oracle_pit_head_expected.py" --repo "$REPO" --out "$OUT/EXPECTED_PIT_HEADS.json"
run 09_quota_semantics  python3 "$HERE/oracle_quota_semantics.py" --repo "$REPO"
run 07_boundary_edges   python3 "$HERE/oracle_boundary_guard_edges.py" --out "$OUT/EXPECTED_BOUNDARY_EDGES.json"
run 06_secret_corpus    python3 "$HERE/oracle_secret_corpus.py" --repo "$REPO" --out "$OUT/SECRET_CORPUS.json"
run 12_tls_key          python3 "$HERE/oracle_tls_key_check.py" --repo "$REPO" --commit "$COMMIT"
run 13_static_scan      python3 "$HERE/oracle_static_scan.py" --repo "$REPO" --json "$OUT/13_static_scan.json"
echo "=== frozen suite at $COMMIT (must be 493 run / same skips as S0 baseline)"
( cd "$REPO" && python3 -m unittest discover -s tests -t . 2>&1 | tail -3 ) | tee "$OUT/frozen_suite_tail.txt"
echo "=== adapter suite"
( cd "$REPO" && PYTHONPYCACHEPREFIX="$(mktemp -d)" python3 -B -m unittest discover -s adapters/adapter_tests -t adapters 2>&1 | tail -3 ) | tee "$OUT/adapter_suite_tail.txt"
( cd "$REPO" && git status --porcelain -- src tests config tools DECISIONS v04_pack ) > "$OUT/frz03_porcelain.txt"; echo "FRZ-03 dirty lines: $(wc -l < "$OUT/frz03_porcelain.txt")"
( cd "$OUT" && sha256sum * ) > "$OUT/ORACLE_OUT_MANIFEST.sha256" 2>/dev/null || true
