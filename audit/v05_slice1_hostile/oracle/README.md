# Independent oracle — how to run

Windows (target checkout C:\Users\abbot\fz\g at cfcff3d):

    powershell -ExecutionPolicy Bypass -File run_oracle.ps1 -Repo C:\Users\abbot\fz\g -Commit cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 -Out C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_run

Linux/macOS:  ./run_oracle.sh <repo> cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 <out-dir>

Scripts (each self-contained, stdlib only, no implementer helper imported):
  oracle_frozen_identity.py     area 1  tree SHAs, diff scope, no-touch list, CRLF blobs, nested .gitattributes, S0-S7 chain
  oracle_provenance_crlf.py     area 1  manifest parity from git tree 51cb635, working-tree bytes, CRLF fail-closed subprocess attack
  oracle_pit_head_expected.py   area 4/5 expected head table from the FROZEN PIT store (compare against reader.admissible_head)
  oracle_quota_semantics.py     area 2/9 frozen QuotaLedger facts (identical-fingerprint replay, regression, ceilings)
  oracle_boundary_guard_edges.py area 7  W1-W4 exact-edge expected table (BND-01/02)
  oracle_secret_corpus.py       area 6  40-case §7.6 corpus with expected verdicts; --repo runs the candidate scanner
  oracle_tls_key_check.py       area 12 committed private keys, runtime references, shipping
  oracle_static_scan.py         area 1/6/7/10/15 independent AST scan (X-01..X-15)
Pre-generated outputs from the frozen code: EXPECTED_PIT_HEADS.json, EXPECTED_BOUNDARY_EDGES.json,
SECRET_CORPUS.json, QUOTA_SEMANTICS_OUTPUT.json.
