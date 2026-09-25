# T4 / B8 final representation-only diff and evidence review

Date: 2026-09-25 (Europe/London). Reviewer: Claude Code, before staging T4.

Base: sealed T3 `39a21328f76cb522bb5b198af1c1e76485d6fe5f`, tree
`b730ee8423accaaa56308558cf8d3d513e948670`. This is a local producer review, not
independent hostile approval.

## Exact T4 path set

```text
.gitattributes
ARCHITECTURE.md
HANDOFF.md
PROJECT_STATE.md
TEST_EVIDENCE.md
remediation_evidence/T4/CLAUDE_IGNORED_RAW_RED_WIP.txt
remediation_evidence/T4/CLAUDE_VERIFIER_HARDENING_RED_WIP.txt
remediation_evidence/T4/FINAL_GATES_GREEN_AFTER_RESTART.txt
remediation_evidence/T4/FINAL_REVIEW.md
remediation_evidence/T4/GREEN_FINAL.md
remediation_evidence/T4/HANDOFF_STATE_REVERIFY_INHERITED.txt
remediation_evidence/T4/HASHES.sha256
remediation_evidence/T4/HISTORICAL_B8_RED_T3.txt
remediation_evidence/T4/INDEPENDENT_B8_RED_T3.txt
remediation_evidence/T4/INTERMEDIATE_GATES_GREEN_BEFORE_IGNORED_FIX.txt
remediation_evidence/T4/T4_B8_AUTHORITY_MEMO.md
remediation_evidence/T4/red_before_probe.py
tests/test_astra_t4_evidence_package.py
tools/genesis_audit_package.py
```

No other path is staged. No `src/genesis`, `DECISIONS/`, `v04_pack/`,
`V04_MIGRATION_PLAN.md`, Project Law, policy, adapter or historical-artifact
path changes: `git diff --exit-code HEAD -- DECISIONS/ src/ v04_pack/
V04_MIGRATION_PLAN.md` exited 0 on the final bytes.

## Scope review

- `tools/genesis_audit_package.py` is audit-only. Nothing under `src/` imports
  it, and it neither reads nor writes Genesis runtime state.
- `tests/test_astra_t4_evidence_package.py` builds throwaway Git fixtures in
  scratch directories and never mutates this repository.
- `.gitattributes` adds one rule, `remediation_evidence/T4/*.txt -text
  whitespace=-trailing-space`. It changes stored representation only for T4
  transcripts and makes their Git-blob, checkout and hashed bytes identical.
- The four state documents change only T4/B8 status text, figures and the
  handoff re-run command (`compileall` now also covers `tools`). Each keeps the
  HOLD / adapter NO-GO disposition.
- No historical RED or archive was replaced. The original five-test RED, the
  standalone probe RED and both Claude hardening REDs are separate files. The
  pre-hardening `FINAL_GATES_GREEN.txt` was renamed to
  `INTERMEDIATE_GATES_GREEN_BEFORE_IGNORED_FIX.txt` before any final claim, so
  that name no longer implies it is final.

## Frozen-authority and evidence integrity

Checked on 2026-09-25 against the external Claude Code handoff manifest,
using both worktree bytes and HEAD Git blobs:

- All four approved ADR/approval-note hashes match: ADR-0002
  `7e851df9…ae00`, its approval `aea4202f…cbb6`, ADR-0003 `0fd4c63d…afad` and
  its approval `f5a2556b…62e4`.
- All fourteen sealed T1–T3 important-evidence hashes match.
- The five inherited T4 files that were not meant to change (both REDs, memo,
  probe and pre-reconciliation `GREEN_FINAL.md`) matched before reconciliation.
  Only the tool and test differed, and those differences are the RED-first
  hardening recorded in `GREEN_FINAL.md`.
- All six original external S5/audit artifacts match their recorded byte
  lengths and SHA-256 values.

## Gate record

| Run | Tool/test bytes | Targeted | Full | compileall |
|---|---|---|---|---|
| Final sealing gates (`FINAL_GATES_GREEN_AFTER_RESTART.txt`) | `2015c7e7…` / `9035434a…` | 9/9, 12.138 s | 297/297, 153.972 s | exit 0 |
| Pre-seal confirmation after doc and `.gitattributes` edits | same bytes, re-hashed OK | 9/9, 12.156 s | 297/297, 162.442 s | exit 0 |

For both runs, `git diff --check` exited 0 and the authority/source diff was
empty. No test was skipped.

## Residual observations for the hostile auditor

These are not known B8 defects. They are the limits of the construction and
should be attacked independently:

1. `verify` enforces approved authorities only when the caller passes
   `--authority` pins. Without pins it checks internal consistency only. The
   recorded package verification passes both ADR pins.
2. The adjacent `.sha256` sidecar authenticates the ZIP only against accidental
   or one-sided change. Someone who replaces both files together is caught only
   by comparing against the package SHA-256 recorded out of band in the
   external verification report and handoff.
3. `raw_worktree_bytes` members are exact checkout bytes. Under this host's
   `core.autocrlf=true`, most tracked LF blobs check out as CRLF, so raw members
   intentionally differ from their `git_blob_bytes` counterparts. Only the Git
   namespace is cross-checked against the object database.
4. The embedded manifest is parsed with Python's `json`, which keeps the last
   of duplicate keys. The manifest is covered by the sidecar and the member
   hashes are rechecked, so this matters only together with (2).
5. On case-insensitive filesystems, members differing only by case would
   collide during fresh extraction. The post-extraction rehash would then fail
   closed rather than pass silently.

## Disposition

The final T4 bytes are representation-only and within the class-A scope in
`T4_B8_AUTHORITY_MEMO.md`. They are ready to seal as one new commit on T3.
Local green is not independent approval. Genesis remains HOLD / adapter NO-GO.
