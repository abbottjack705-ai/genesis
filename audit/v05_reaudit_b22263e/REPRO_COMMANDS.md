# REPRO_COMMANDS

All paths are relative to the repository root unless stated otherwise. `PKG=audit/v05_reaudit_b22263e`.
The tools are stdlib-only Python 3.11+ plus `git` (and `openssl` for one self-test variant).

## A. Reproduce every result in this package (any host with a clone of origin)

```bash
git fetch origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'

# A0 candidate reachability (RA-000)
git ls-remote origin
git fetch origin cfcff3dbb285eaa48a6cfc1eceedb91e27662c81        # -> "not our ref" (exit 128)
git rev-parse --verify b22263e^{commit}                           # -> fatal
python -B $PKG/reaudit/run_reaudit.py --repo . --candidate b22263e \
    --predecessor cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 --out /tmp/drv   # -> R00 CANNOT_RUN, exit 2

# A1 frozen identity at the reachable commits
for c in 4f11606 2278e2a c8dfafd 37b86fb; do
  for t in src tests config tools DECISIONS v04_pack; do echo "$c $t $(git rev-parse $c:$t)"; done
done
git cat-file -p v0.4-foundation-freeze | head -3
git rev-parse c8dfafd:V05_ADAPTER_ARCHITECTURE.md                  # 30c4ca7d43fe11504e873e25944f9bdd30079253
git diff --stat 2278e2a c8dfafd
git diff --name-status 2278e2a c8dfafd -- src tests config tools DECISIONS v04_pack   # empty

# A2 frozen suite at c8dfafd (Linux: 493 / skipped=19; Windows: 493 / skipped=1)
git worktree add --detach /tmp/wt c8dfafd
(cd /tmp/wt && python -B -m unittest discover -s tests -t . && \
 git status --porcelain -- src tests config tools DECISIONS v04_pack)

# A3 FRZ-09 expectation (36 modules) and the CRLF precondition
#    regenerate the expectation from git ls-tree 51cb635 (as in $PKG/evidence/FRZ09_EXPECTED_ENTRIES.json),
#    then compare a core.autocrlf=true checkout:
git -c core.autocrlf=true clone -q --no-checkout . /tmp/crlf && \
  git -C /tmp/crlf -c core.autocrlf=true checkout -q --detach c8dfafd && \
  git -C /tmp/crlf ls-files --eol src/genesis/pit.py               # i/lf w/crlf -> bytes differ from blobs

# A4 the prior oracle regenerated against the frozen code (all four outputs identical to 37b86fb)
mkdir -p /tmp/prior && git archive 37b86fb audit/v05_slice1_hostile | tar -x -C /tmp/prior
O=/tmp/prior/audit/v05_slice1_hostile/oracle
(cd /tmp/prior/audit/v05_slice1_hostile && sha256sum -c ARTIFACT_MANIFEST.sha256 | grep -vc ': OK$')   # 0
python -B $O/oracle_pit_head_expected.py --repo /tmp/wt --out PIT.json
python -B $O/oracle_boundary_guard_edges.py --out EDGES.json
python -B $O/oracle_secret_corpus.py --out CORPUS.json
python -B $O/oracle_quota_semantics.py --repo /tmp/wt > quota.txt
for f in "PIT.json EXPECTED_PIT_HEADS.json" "EDGES.json EXPECTED_BOUNDARY_EDGES.json" "CORPUS.json SECRET_CORPUS.json"; do
  set -- $f; cmp <(tr -d '\r' < $1) <(tr -d '\r' < $O/$2) && echo "$1 identical"; done

# A5 re-auditor tool self-tests
python -B $PKG/reaudit/selftest/selftest_run_reaudit.py --source . --out /tmp/st     # 22/22 (about 4 min)
python -B $PKG/reaudit/selftest/selftest_mutate_sites.py                             # 7/7
python -B $PKG/reaudit/selftest/selftest_p20.py                                      # 5/5 mocks
for p in $PKG/reaudit/probes/p2*.py; do python -B $p --repo /tmp/wt --out /dev/null; echo "exit=$?"; done   # all 2

# A6 network block self-test (see evidence/selftest_netblock.txt for probe_mod.py)
REAUDIT_NETLOG=$PWD/net.jsonl PYTHONPATH=$PKG/reaudit/netblock_site python -B $PKG/reaudit/netblock.py -m probe_mod
```

## B. Make the candidate reachable (human owner; prerequisite for everything in C)

```bash
# on the Windows host that holds it (Git Bash or PowerShell):
git -C C:/Users/abbot/fz/g branch --contains b22263e          # find the branch name
git -C C:/Users/abbot/fz/g push -u origin <that-branch>       # pushes b22263e with its ancestry (cfcff3d, 63e06a1..9c35c5c)
# then publish the material the request names, e.g. on a separate branch:
#   C:\Users\abbot\fz\V05_REMEDIATION_REPORT_b22263e.md
#   C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\      (controlling audit + 17 probes)
#   C:\Users\abbot\a8\v05_prep\audit_oracle\                             (oracle)
#   C:\Users\abbot\a8\genesis_lab\C_reliability_audit\                  (Expedition C)
```

Confirm from any other host: `git fetch origin <full b22263e SHA>` succeeds.

## C. Complete the re-audit (run ALONE on the host; the 37b86fb audit lost runs to host memory)

```bash
bash $PKG/reaudit/run_all.sh <repo-with-b22263e> <out-dir> [<37b86fb package dir>]
```

The script does the following, in order. Every output is hashed into `<out-dir>/RESULTS_MANIFEST.sha256`.

| Step | What it runs |
| --- | --- |
| 1 | `run_reaudit.py`: pin and lineage; tree SHAs at every commit authority..candidate; diff scope (authority..candidate and cfcff3d..b22263e); no-touch list; LF blobs; `diff --check`; FRZ-09 parity with `git ls-tree 51cb635`; manifest pin; CRLF fail-closed attack; independent AST scans (FRZ-05/06/07/08/10/11, CLI trust seam, operator time flags, exception-text sites, production `sleep`); history secret sweep; sentinel confinement; private keys, export-ignore, `git archive`, certificate SAN; 167 test IDs; both suites under the network block with expected counts (Windows frozen 493:1, adapter 690:1); FRZ-03; `compileall` |
| 2 | The 37b86fb oracle, unchanged (`run_oracle.sh`; on Windows use `run_oracle.ps1` if `python3` is absent) |
| 3 | The 37b86fb attacks a01–a15 and a07 against the clean candidate clone (a01 also against an autocrlf clone) |
| 4 | The re-audit probes p20–p25. Exit codes: 0 PASS, 1 FAIL, 2 CANNOT_RUN. A CANNOT_RUN means the binding in `probes/_probe.py` must be adapted to a renamed API; never read it as a pass |
| 5 | `mutate_sites.py` over `cfcff3d..b22263e` `adapters/src` (assertion-kill accounting; hours) |
| 6 | The privileged a11 run for the real symlink (RA-001). It needs Developer Mode or an elevated shell |

Single checks:

```bash
python -B $PKG/reaudit/probes/p20_deadline_stages.py      --repo <clean b22263e clone> --out p20.json
python -B $PKG/reaudit/probes/p21_rejected_restart.py     --repo <clean b22263e clone> --out p21.json
python -B $PKG/reaudit/probes/p22_invalidation_selfheal.py --repo <clean b22263e clone> --out p22.json
python -B $PKG/reaudit/probes/p23_f44_protective_halts.py --repo <clean b22263e clone> --out p23.json
python -B $PKG/reaudit/probes/p24_tournament_omission.py  --repo <clean b22263e clone> --out p24.json
python -B $PKG/reaudit/probes/p25_operator_authority.py   --repo <clean b22263e clone> --out p25.json
python $PKG/reaudit/mutate_sites.py --repo <clean b22263e clone> --base cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 \
  --head b22263e --paths adapters/src --list-only --out sites.json     # inspect the mutant set first
```

**Reading a probe FAIL.** A FAIL is a probe verdict, not yet a finding. Confirm it by reading the cited
code, and record the file and line in a new FINDINGS row (fields as in `FINDINGS.csv`).
