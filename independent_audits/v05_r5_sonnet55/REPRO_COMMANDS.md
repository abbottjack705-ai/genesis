# Reproduction commands

All commands are read-only with respect to the candidate. They never contact the network, never use a credential and
never write inside the candidate tree except in disposable scratch worktrees. Run from a clone of the repository.
(Probe keys such as `AUD1T-Zq8vLm2XpR7tYk4WnB9cD3fHsJ` are synthetic; they are **not** credentials.)

## 0. Pin and verify (startup verification)

```bash
git fetch origin --prune --tags
git cat-file -t b22263e582386f04e5b7939e511757940ffdfbe0                     # commit
test "$(git rev-parse origin/v05-slice1-impl)"       = b22263e582386f04e5b7939e511757940ffdfbe0 && echo tip-ok
test "$(git rev-parse b22263e582386f04e5b7939e511757940ffdfbe0^)" = 9f846d8abcd7383d6acae78294f0aefaba08e630 && echo parent-ok
git merge-base --is-ancestor cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 b22263e582386f04e5b7939e511757940ffdfbe0 && echo cfcff3d-ancestor
git diff --name-status 9f846d8abcd7383d6acae78294f0aefaba08e630 b22263e582386f04e5b7939e511757940ffdfbe0 | grep -v ' adapters/evidence/FINAL/' | wc -l   # 0 => evidence-only
git diff --name-only c8dfafdff3be611fa6255a03ed361bc46d7ad8fe b22263e582386f04e5b7939e511757940ffdfbe0 | grep -v '^adapters/' | wc -l  # 0 => adapter scope
for t in src tests config tools DECISIONS v04_pack; do printf '%-10s %s %s\n' $t "$(git rev-parse 2278e2a68083f7ac58d796b1ed9c43d50020b6b0:$t)" "$(git rev-parse b22263e582386f04e5b7939e511757940ffdfbe0:$t)"; done
git show c8dfafdff3be611fa6255a03ed361bc46d7ad8fe:V05_ADAPTER_ARCHITECTURE.md > /tmp/ARCH_c8dfafd.md       # the authority, as it existed at c8dfafd
```

## 1. Scratch worktrees (never edit the audited checkout)

```bash
export AUDIT_SCRATCH=/tmp/v05_audit_scratch; mkdir -p $AUDIT_SCRATCH
git worktree add --detach $AUDIT_SCRATCH/cand b22263e582386f04e5b7939e511757940ffdfbe0   # pristine candidate (probes attack this)
git worktree add --detach $AUDIT_SCRATCH/mut  b22263e582386f04e5b7939e511757940ffdfbe0   # mutation worktree (mutate.py edits + restores)
git worktree add --detach $AUDIT_SCRATCH/mut2 b22263e582386f04e5b7939e511757940ffdfbe0   # single-mutation tree for p160
```

The candidate's runtime guard (FRZ-09) requires isolated bytecode: **always** `PYTHONPYCACHEPREFIX=$(mktemp -d) python -B …`.

## 2. Suites

```bash
cd $AUDIT_SCRATCH/cand
PYTHONPYCACHEPREFIX=$(mktemp -d) python -B -m unittest discover -s adapters/adapter_tests -t adapters -v      # Linux/3.11: Ran 690, FAILED (errors=1) = RA5-013
PYTHONPYCACHEPREFIX=$(mktemp -d) python -B -m unittest discover -s tests -t . -v                              # frozen suite (see TEST_RESULTS.md)
PYTHONPYCACHEPREFIX=$(mktemp -d) python -B -m compileall -q src tests adapters/src adapters/adapter_tests
git diff --check c8dfafdff3be611fa6255a03ed361bc46d7ad8fe b22263e582386f04e5b7939e511757940ffdfbe0 -- . ':!adapters/evidence'
```

Network-blocked / network-audited runs:

```bash
# independent audit hook registered BEFORE the suite's own hook; logs every connect/getaddrinfo/sendto
PYTHONPYCACHEPREFIX=$(mktemp -d) python -B independent_audits/v05_r5_sonnet55/probes/run_nonet.py $AUDIT_SCRATCH/cand
# whole suite in a network namespace with only loopback (needs unprivileged user namespaces)
unshare -rn python3 independent_audits/v05_r5_sonnet55/probes/netns_run.py $AUDIT_SCRATCH/cand
```

Expected: 2 non-loopback events, both from `adapter_tests/test_v05_transport_http.py:173-175` (deliberate guard self-test).

## 3. Probes (each prints its own PASS/FAIL data; transcripts in `evidence/`)

```bash
cd independent_audits/v05_r5_sonnet55/probes
CAND_DIR=$AUDIT_SCRATCH/cand ./run_all_probes.sh          # everything below, ~10 minutes
```

| Probe | Area | What a *reproduced defect* looks like |
| --- | --- | --- |
| `p118_poison3.py` | **RA5-001** | three cases each print `acquire = RAISED <Overflow|UnicodeEncodeError|IdentityTypeError>`, `restart_resume = RAISED …`, `reader_after_later_healthy_capture = Unusable:DATA_CAPABILITY_NOT_READY` |
| `p124_deep.py` | RA5-001 (4th class) | `depth 600 ESCAPED RecursionError` |
| `p113_poison.py`, `p112_overflow_trace.py`, `p115_minimize.py` | RA5-001 | trace/minimal literals |
| `p114_fuzz_parser.py` / `p116_fuzz2.py 11 10000` / `p119_fuzz3.py 23 8000` | RA5-001 | `ESCAPE (...)` lines for Overflow / UnicodeEncodeError / IdentityTypeError |
| `p120_which_fields.py` | RA5-001 | `UnicodeEncodeError 212 [...]` of 1134 leaves |
| `p119b_no_remedy.py` | RA5-001 | `operator reset rc: 0`, `resume after reset: RAISED Overflow` |
| `p117_fuzz_fixtures.py`, `p121_fuzz_pipeline.py` | control | `none` (no escape) |
| `p122_headers.py`, `p123_date_overflow.py` | **RA5-002** | `OverflowError` for a huge-year `Date`; `acquire RAISED OverflowError`, rows stop at `acq_sent` |
| `p70_tls_env.py` | **RA5-003** | with `SSL_CERT_FILE=…/test-ca.pem`: `RESPONSE 200 | server saw keyed request line: True` (control without the variable: `NO_RESPONSE`) |
| `p11_slowdrip.py` | **RA5-004** | `send_returned_after_s` ≈ 40 for a 3 s deadline, `outcome: RESPONSE`, `T1_after_deadline: true` |
| `p12_runner_deadline.py` | B + **RA5-005** | section 3 reads 3 and 4: `RAW ClockFault escaped` |
| `p110_regex_nl.py` | RA5-006 | `native_id 'abc\n' ACCEPTED` |
| `p53_nonascii.py` | RA5-007 | `body Latin-1 echo … stored forms: {'latin1': True}` |
| `p60_operator.py` (L5) | RA5-008 | `declared_bookmakers_max 50 loads` |
| `p90_derivation.py` | RA5-009 | `VERIFIER PASSED` for `upstream_version_changed`, `content_type_changed` |
| `p30_completeness.py` | RA5-010 | `V4 … ABSENT: 6` |
| `p150_usage.py` | RA5-011 | `reported: None` accepted for `1e5`, `99,999`, … |
| `mutate.py mutants.json` | RA5-012 | survivors M03, M04, M07, M08, M09 |
| `p160_equiv_mutant.py` | RA5-012 | pristine tree: `REJECTED`; with the one-line mutation (below): `ACCEPTED` |
| `p100_static_evasion.py` | RA5-014 | `not flagged` rows |
| `p95_f44.py` | RA5-017 / F-44 | `OSError`, rows stop at `acq_sent`, orphan after restart |

Extra transcripts in `evidence/`: `p70_tls_env_control.txt` (same probe without the trust-store override, `AUDIT_P70_CONTROL=1`),
`p160_equiv_mutant_MUTATED.txt`, `p55_secret_form_only_MUTANT_M26.txt`, `p90_derivation_MUTANT_M37.txt`,
`p12_runner_deadline_MUTANT_M08.txt` (each is a probe run against a single-line mutant, proving the survivor is a missing test and
not an equivalent mutant), and `implementer_repro17_linux.txt` (the implementer's 17-probe script, run unmodified on Linux).

Held-attack probes (a *pass* means the attack failed): `p10_deadline.py`, `p20_quota_replay.py`, `p40_emit_crash.py`,
`p41_pit_head.py`, `p42_stale.py`, `p43_invalidation_crash.py`, `p50_secret_echo.py`, `p51_secret_echo2.py`, `p52_transport_exc.py`, `p60_operator.py`,
`p61_reset.py`, `p80_provenance.py`, `p130_replay.py` (determinism), `p131_guard_oracle.py` (boundary oracle),
`p140_rejected_restart.py`, `p170_dev7.py`.

## 4. The "equivalent mutant" check (`RA5-012`)

```bash
# pristine
CAND_DIR=$AUDIT_SCRATCH/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python -B probes/p160_equiv_mutant.py          # => REJECTED
# apply the single R3 "equivalent" mutation in mut2 only
python3 - <<'PY'
import os
p=os.environ["AUDIT_SCRATCH"]+"/mut2/adapters/src/genesis_adapters/oddspapi/derivation.py"
s=open(p).read(); old='    if scope_hash is None or rows.get("acq_sent", {}).get("expected_scope_hash") != scope_hash:'
assert s.count(old)==1; open(p,"w").write(s.replace(old,'    if scope_hash is None:'))
PY
CAND_DIR=$AUDIT_SCRATCH/mut2 PYTHONPYCACHEPREFIX=$(mktemp -d) python -B probes/p160_equiv_mutant.py          # => ACCEPTED (mutant is killable)
git -C $AUDIT_SCRATCH/mut2 checkout -- .
```

## 5. Independent mutation campaign

```bash
cd independent_audits/v05_r5_sonnet55/probes
AUDIT_SCRATCH=$AUDIT_SCRATCH python3 mutate.py mutants.json $AUDIT_SCRATCH/out/mutation_results.jsonl   # ~40-60 min, sequential
```

`M00` is a no-op control and must SURVIVE. The harness deselects only the platform-baseline error
`test_f04_a_link_reported_by_lstat_is_refused_on_every_platform` (finding `RA5-013`) so a fail-fast run is not killed by it.

## 6. Secret sweep

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"independent_audits/v05_r5_sonnet55/probes")
from indep_scan import forms, hits
KEY="GENESIS-SENTINEL-KEY-0123456789abcdef"            # the repository's PUBLIC test sentinel
# expect: no hits in adapters/evidence, adapters/config, README; only hex-alphabet false positives in two src files
PY
grep -rIl "BEGIN [A-Z ]*PRIVATE KEY" . | grep -v '^./.git/'      # expect only adapters/adapter_tests/fixtures/tls/server.key (RA5-003)
```
