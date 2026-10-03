# Reproduction commands (R6 re-audit)

Everything below runs on Linux with CPython 3.11+ (3.12/3.13 where stated), `git`, `openssl`, `unshare`. **No provider
contact, no credential, loopback only** (and an isolated network namespace where stated). Probes never modify the
candidate tree; they import it read-only and write only to `$AUDIT_SCRATCH`.

```bash
# 0. pins (startup integrity)
git fetch origin ccr-689a0c12-vys6ag audit/v05-r5-sonnet55 --tags
git rev-list --parents -n1 4ed66de4e2f3161464b9205583b3ee7a97133904   # -> parent b22263e5...
git rev-list --parents -n1 435cdbaa0ce9702307c4780746aec30e7f3da2e9   # -> parent 4ed66de4...
git diff --stat 4ed66de 435cdba                                       # only adapters/evidence/R6/CANDIDATE.txt
git diff --stat b22263e 4ed66de -- . ':!adapters'                     # empty: nothing outside adapters/
for t in src tests config tools DECISIONS v04_pack; do
  echo "$t $(git rev-parse v0.4-foundation-freeze^{commit}:$t) $(git rev-parse 4ed66de:$t) $(git rev-parse 435cdba:$t)"; done
git rev-list --merges b22263e..435cdba                                # empty
git rev-parse origin/audit/v05-r5-sonnet55                            # 472f2603...
(cd <worktree@472f260>/independent_audits/v05_r5_sonnet55 && sha256sum -c ARTIFACT_MANIFEST.sha256)
(cd <worktree@4ed66de>/adapters/evidence/R6 && sha256sum -c HASHES.sha256)

# worktrees used below (all detached, read-only use)
git worktree add --detach $S/cand    4ed66de4e2f3161464b9205583b3ee7a97133904   # the audited code
git worktree add --detach $S/r5audit 472f2603b0ded3e0199609d59f19185f7c8e4294   # = b22263e code + R5 audit (BASE control)
export AUDIT_SCRATCH=$S/ascratch P=independent_audits/v05_r6_hostile_reaudit/probes
```

## Suites

```bash
cd $S/cand
for PY in python3.11 python3.12 python3.13; do
  PYTHONPYCACHEPREFIX=$(mktemp -d) $PY -B -m unittest discover -s adapters/adapter_tests -t adapters -v; done
PYTHONDONTWRITEBYTECODE=1 python3.11 -m unittest discover -s tests -t . -v               # frozen V0.4 (quiet host)
PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/run_nonet.py $S/cand                    # independent audit hook
PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/n01_nonet_callsites.py $S/cand          # + call-site attribution
unshare -rn python3.11 $P/netns_run.py $S/cand                                            # loopback-only netns
# frozen T6 hard-link race test: 10x quiet, 10x under 4 busy loops (python3 busy.py &)
python3.11 -m unittest tests.test_astra_t6_risk_log_integrity.T6HardLinkAliasTests.test_t6_concurrent_writers_through_a_toggled_hard_link_keep_one_valid_chain
```

## Findings

```bash
# RA6-001  rejection coverage lost after a crash when the rejected capture is not the newest attempt
CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/a01_settle_gap.py
# RA6-002  QUOTA_DIVERGENCE response: no observation uninterrupted, usable observations after restart (R6 and BASE)
CAND_DIR=$S/cand    PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/q01_quota_divergence_restart.py
CAND_DIR=$S/r5audit PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/q01_quota_divergence_restart.py
# RA6-003  tls_context() environment race (needs t01 first: it restores the retired CA into $AUDIT_SCRATCH/oldtls)
python3.11 $P/t01_tls_trust.py $S/cand python3.11 R6
for PY in python3.11 python3.12 python3.13; do PYTHONPYCACHEPREFIX=$(mktemp -d) $PY -B $P/t02_tls_env_race.py $S/cand 300; done
# RA6-004  name resolution outside the absolute deadline (isolated user+mount+net namespace, fake resolver on lo)
unshare -rmn python3.11 -B $P/r02_dns_stall.py $S/cand 3
R02_THREE_NAMESERVERS=1 unshare -rmn python3.11 -B $P/r02_dns_stall.py $S/cand 3
# RA6-005  a BASE-written runtime root opened by the candidate (and stale G2R pin, replay determinism)
PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/v01_versioning_replay.py $S/cand $S/r5audit
```

## Closure checks of RA5-001 .. RA5-004 (all HELD on R6)

```bash
# RA5-001
CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/a13_corpus_e2e.py              # 29-case corpus
CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/a10_fuzz_e2e.py <seed> <n> out.jsonl   # e2e fuzz
CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/a11_fuzz_pure.py <seed> <n>      # pure-stage fuzz
CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/a12_sweep_pure.py                # exhaustive sweep
# RA5-002
for PY in python3.11 python3.12 python3.13; do CAND_DIR=$S/cand PYTHONPYCACHEPREFIX=$(mktemp -d) $PY -B $P/d01_date_totality.py 7 20000; done
PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/d02_accepted_forms.py $S/cand
# RA5-003 (production trust vs the RETIRED CA + leaf key restored from b22263e history into $AUDIT_SCRATCH only)
for PY in python3.11 python3.12 python3.13; do python3.11 $P/t01_tls_trust.py $S/cand $PY R6; done
python3.11 $P/t01_tls_trust.py $S/r5audit python3.11 BASE-b22263e                                  # control: breaches
# RA5-004 (real loopback TLS server; slow drips, stalls, relay, multi-address connect stall, EINTR, clock step)
for PY in python3.11 python3.12 python3.13; do PYTHONPYCACHEPREFIX=$(mktemp -d) $PY -B $P/r01_deadline.py $S/cand 3; done
```

## Modified tests: old assertions against R6 code

```bash
git worktree add --detach $S/oldtests 4ed66de
for f in test_v05_reader.py test_v05_jsonstrict.py test_v05_parser_schema.py test_v05_credential.py test_v05_tx01.py \
         test_v05_r2_transport_boundary.py; do
  git show b22263e:adapters/adapter_tests/$f > $S/oldtests/adapters/adapter_tests/old_$f; done
cd $S/oldtests && PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B -m unittest discover -s adapters/adapter_tests -t adapters -p 'old_test_v05_reader.py'
# (jsonstrict / parser_schema: the same with a signature shim that supplies the two new bounds; see evidence/old_tests_against_R6.txt)
```

## Mutation

```bash
# three scratch worktrees of 4ed66de at $S/w{1,2,3}/mut; specs split round-robin (each worker starts with the no-op control)
AUDIT_SCRATCH=$S/w1 PYTHONPYCACHEPREFIX=$(mktemp -d) python3.11 -B $P/mutate.py $S/w1/specs.json $S/w1/results.jsonl
# specs: $P/mutants.json + $P/mutants_round2.json (R5, 51 + control; M15/M37 must report BAD_SPEC),
#        $P/mutants_r6_adapted.json (implementer's re-anchored M15/M37, semantics re-checked), $P/mutants_r6_audit.json (mine)
```
