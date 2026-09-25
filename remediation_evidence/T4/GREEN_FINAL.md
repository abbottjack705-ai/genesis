# T4 / B8 local green evidence

Date: 2026-09-25 (Europe/London)

Base commit: `39a21328f76cb522bb5b198af1c1e76485d6fe5f`

Base tree: `b730ee8423accaaa56308558cf8d3d513e948670`

Scope: B8 evidence/package representation only. The authority classification
and construction are in `T4_B8_AUTHORITY_MEMO.md`. No GO is granted.

Reconciliation note: this record supersedes the unsealed Codex WIP version of
this file (SHA-256
`2b7700b5ca3cb6122c87280671e9a201f7344b8a289ae20732afc67fb1c9aef0`, 4370
bytes, recorded in the external Claude Code handoff manifest). Every run fact in
that version is retained below as history. Its full-suite and compileall
results preceded later verifier hardening and are not the sealing gates.

## Historical RED-before

Command:

```text
python remediation_evidence/T4/red_before_probe.py --repo . --archive ..\..\outputs\GENESIS_V04_S5_REAUDIT_REPOSITORY_27dd525.zip --manifest ..\..\outputs\GENESIS_V04_S5_REAUDIT_MANIFEST.json
```

Exact result: exit 1; four methods, five intended invariant assertion failures,
zero errors in 22.305 seconds. The probe found 192 tracked files and 192 exact-
byte archive/Git mismatches, with zero mismatches after CRLF-to-LF comparison.
Archived ADR-0002 was
`4e9f40c124d1557ecf4959bc9d2afd6878b83a3119f79a3d9ca81aa025a1efab`
instead of approved Git-blob
`7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`;
archived ADR-0003 was
`b735e0805588d6f994bf9d6ea6aa8a4a19b0c84f4d4a469ede26f6b600f24aea`
instead of approved Git-blob
`0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`.
Repository and S5 transcript representations were absent or unlabeled.

Exact transcript: `HISTORICAL_B8_RED_T3.txt`. The historical archive and
producer manifest were read only and remain unchanged.

## Independent acceptance RED-before

Command:

```text
python -m unittest tests.test_astra_t4_evidence_package -v
```

Exact result: five tests, five explicit missing-contract assertion failures,
zero errors in 3.954 seconds. Transcript: `INDEPENDENT_B8_RED_T3.txt`.

## Initial Codex GREEN (historical, pre-hardening)

The same five-test command passed 5/5 in 10.666 seconds. It proves:

- exact Git-object source and ADR bytes, independent of checkout line endings;
- separate `git_blob_bytes`, `raw_worktree_bytes` and
  `historical_raw_artifact_bytes` namespaces and manifest labels;
- approved-authority pins;
- deterministic repeated ZIP builds and exact SHA-256 sidecars;
- verification from a fresh extraction without a Git repository;
- optional every-file commit/tree/Git-object cross-check; and
- fail-closed duplicate/tampered archive handling.

On that earlier tool, full discovery passed 293/293 in 377.852 seconds and
`python -m compileall -q src tests tools` exited 0. Codex then made the external
sidecar mandatory and hardened the duplicate fixture; the targeted suite passed
5/5 in 28.799 seconds, but full discovery and compileall were not rerun on those
bytes before the handoff. None of these results is claimed for the final bytes.

## Handoff-state re-verification (inherited bytes)

Claude Code confirmed that all eleven dirty/untracked files matched the external
handoff manifest (tool
`7a3e6b59acb367fbd598455e8052a91fbcf580e7affa9f9927460127988d4c91`, test
`8eac39423cf6154c67b9d19a27b0d153a9456c97c87e3a9da940e25ef684947f`). On those
exact inherited bytes: targeted 5/5 in 7.076 seconds, full discovery 293/293 in
174.256 seconds and compileall exit 0. Transcript:
`HANDOFF_STATE_REVERIFY_INHERITED.txt`. These are not the sealing gates.

## Verifier hardening RED-before

Adversarial review of the inherited tool found three verifier gaps. New
acceptance tests were added first and run against the unchanged inherited tool:

- `verify` accepted no caller-pinned approved authorities, so a package whose
  manifest stripped its authority rows still verified;
- raw-worktree and historical member rows accepted undeclared fields; and
- `repository_status`, `non_authorizations` and `self_reference_note` values
  were not checked.

Exact result: eight tests, five assertion failures (four closed-manifest
subtests plus the caller-pin test), zero errors in 10.816 seconds. The content-
tamper/unsafe-path/stale-or-missing-sidecar test was new positive coverage and
already passed; it is not claimed as RED. Transcript:
`CLAUDE_VERIFIER_HARDENING_RED_WIP.txt`.

After the repair, targeted passed 8/8 in 10.595 seconds and full discovery
passed 296/296 in 159.710 seconds. Transcript:
`INTERMEDIATE_GATES_GREEN_BEFORE_IGNORED_FIX.txt`. These results are intermediate
because the tool changed again afterwards.

A further review found that the builder's clean check uses `git status`, which
omits ignored files, while raw-worktree roots were collected with `rglob`.
Ignored `__pycache__` bytes under `remediation_evidence/R8`, `R9` and `T4` would
therefore have entered the `raw_worktree_bytes` namespace as if they were
evidence. The new ignored-file test failed on tool
`05f8e7ecdd223e7962a51c492c90c872166cd6497b346c7f02954193fbe1f345` with one
assertion failure and zero errors in 1.185 seconds. Transcript:
`CLAUDE_IGNORED_RAW_RED_WIP.txt`.

## Verifier hardening construction

All changes are confined to `tools/genesis_audit_package.py` and
`tests/test_astra_t4_evidence_package.py`; the package format and the three
representation labels are unchanged.

- `verify --authority PATH=SHA256` requires the manifest authority rows to equal
  the caller's approved pins exactly; the builder re-verifies with its own pins.
- Non-Git member rows must have exactly the five declared fields.
- `repository_status` must be `clean`; `non_authorizations` and
  `self_reference_note` must equal their fixed values.
- Raw-worktree members come only from `git ls-files` beneath each requested
  root, so ignored files can never become evidence.
- The existing duplicate/tamper test now also asserts the rejection is the
  duplicate-member check rather than an incidental failure.

## Final exact-byte GREEN (sealing gates)

Input bytes:

```text
2015c7e7fcd3754a796aa608a59337bca97e2cb022ada546073aa1e64e03a6ef  tools/genesis_audit_package.py
9035434ae0cd02490ec93658012abc976f9a4db9c975dfca1b0b87b2a0e9e535  tests/test_astra_t4_evidence_package.py
```

The first attempt at these gates began at 2026-09-25T20:26:08+01:00. Its
targeted run completed 9/9, but an unplanned machine restart killed full
discovery mid-run; that partial transcript is not claimed as evidence. After the
restart Git showed no lock, merge, rebase, cherry-pick or stash state, HEAD was
unchanged and both input files still matched the hashes above. The complete gate
sequence was then rerun on the same bytes:

```text
python -m unittest tests.test_astra_t4_evidence_package -v
Ran 9 tests in 12.138s
OK

python -m unittest discover -s tests -t . -v
Ran 297 tests in 153.972s
OK

python -m compileall -q src tests tools          exit 0, empty output
git diff --check                                  exit 0
git diff --exit-code HEAD -- DECISIONS/ src/ v04_pack/ V04_MIGRATION_PLAN.md
                                                  exit 0 (no delta)
```

Both input hashes were verified unchanged after the full run. No test was
skipped. The one `zipfile` duplicate-name warning is deliberately emitted by the
hostile tamper fixture before the verifier rejects that archive; that test
passes. Transcript: `FINAL_GATES_GREEN_AFTER_RESTART.txt`.

The killed test left an untracked scratch directory,
`work/test_runtime/4e47dcec35c444d28657c45c3196a52e/`. It is not T4 content and
was moved out of the repository intact, so the builder's clean-repository
requirement can hold; nothing was deleted.

`.gitattributes` now stores `remediation_evidence/T4/*.txt` with `-text`. These
transcripts mix LF headers with captured CRLF test output; without the attribute
the system `core.autocrlf=true` setting would rewrite them on commit and
checkout. With it, Git-blob, checkout and hashed bytes are identical.

## Original artifacts retained byte-for-byte

```text
e96b9ec08953b15bbd60f1a511be950480a76a9898b647aad144ebd06008596c  GENESIS_V04_S5_REAUDIT_REPOSITORY_27dd525.zip  498904 bytes
b185932f43ad606ba4b343cbf1bb3eb2dbe42a45587fd1dfc26591df5192a688  GENESIS_V04_S5_REAUDIT_MANIFEST.json  1929 bytes
bc0d5a07684aa8a9ee02d695cf3a13a4faf2487b5856bd307007193ab94fb8bb  GENESIS_V04_S5_REAUDIT_HANDOFF.md  4680 bytes
6317d24f070f344af1c1f87a4d6a3e2878c584bb9149aa44b25e2fff35f01765  GENESIS_V04_S5_REAUDIT_VERIFICATION.txt  523 bytes
3eb889bf4b30c5b5d1b232335e80a9a5a150e190b4e754d5b5e8445d2cdca4f3  GENESIS_V04_S5_ASTRA_AUDIT_REPORT.md  27462 bytes
3f2caa1268ba4e2dd77d935703233b7e36cfcdd10f8085766edec577e52f9e2f  GENESIS_V04_S5_ASTRA_AUDIT_EVIDENCE.zip  2390669 bytes
```

All six were re-hashed on 2026-09-25 after the restart and match.

## Post-commit gate

The final integrated ZIP, embedded manifest and sidecar cannot truthfully name
the T4 commit until it exists. After this independently reviewable commit is
sealed, build the package from that exact clean HEAD, include all six historical
artifacts above without transformation, include raw `remediation_evidence`
working bytes under their separate representation, then verify both against Git
and in a new extraction directory with both approved ADR hashes pinned. Record
the returned commit/tree/package/manifest hashes externally without amending T4.

## Truthful disposition

B8 is locally repaired and reviewable as an independent T4 checkpoint. Together
T1–T4 locally address B1–B8, but local tests and packaging are not independent
hostile approval. Genesis remains HOLD / adapter NO-GO. No strategy, adapter,
shadow research, protected campaign or live-money work is authorized.
