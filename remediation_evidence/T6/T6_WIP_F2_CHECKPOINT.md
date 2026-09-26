# T6 WIP checkpoint: F-2 approval causality (NOT the T6 candidate)

This checkpoint repairs only finding F-2 of the independent T5 review. F-1 is
not started. It is not the T6 candidate, carries no package and grants no
authority: the foundation stays HOLD for protected, shadow and live work. The
design and its classification (B) are in `T6_F2_AUTHORITY_MEMO.md`.

## Base and scope

| Item | Value |
|---|---|
| Branch | `t6-remediation` |
| Base (F-3 checkpoint) | commit `7a548ff52cd12ffec35bcb878b22255d1844968a`, tree `b6e4f0a446be4ad27e078022845db96c2994e2f4`, parent `c3d27d91cf9108dce3ddce084b11c532ce4ab99d` |
| Auditor probe (read only) | `probe_o5_composed_store.py` `88875c55…`, recorded T5 result `probe_o5_composed_store_t5.txt` `41334c08…`; both equal the review's hash list |

T5, the F-4 and F-3 checkpoints, every earlier `remediation_evidence/` file
(including the committed `F4_*` and `F3_*` files) and all review evidence under
`C:\Users\abbot\gv` are unchanged. The checkpoint's own commit, tree and parent
are recorded after committing.

Changed paths relative to the F-3 checkpoint:

- `src/genesis/selection.py`: the witness sidecar, the guarded witness storage,
  recording and admission checks.
- `src/genesis/risk.py` (2 lines) and `src/genesis/execution.py` (3 lines): the
  witness log joins each read-lock set that already locks the approval ledger.
- `tests/test_astra_t6_approval_causality.py`: 11 new permanent tests.
- `remediation_evidence/T6/`: the authority memo, this record, two evidence
  scripts, transcripts and `F2_EVIDENCE_HASHES.sha256`.

No retained test was changed.

## Evidence

All transcripts were written as UTF-8 with LF by their scripts, in short-path
`core.autocrlf=false` clones under `C:\Users\abbot\t6\`; no test ran in the
OneDrive repository. Transcript headers record every uncommitted path with its
SHA-256.

- Checkpoint source: `selection.py` `1c738265…`, equal to T5's recorded hash.
- Repaired source: `selection.py` `d02e357a…`.
- `decision_output.py` is unchanged: `6e6ab351…` in both.

### RED (F-3 checkpoint source)

**`F2_RED_AUDITOR_PROBE.txt`.** The auditor's probe was run unmodified, twice,
by `F2_AUDITOR_PROBE_DRIVER.py`:

- The runs are identical, and every variant equals the review's recorded T5
  result.
- The control is refused at recording.
- `copied_ledger_store` and `raw_log_append` both reach `risk_approved` after a
  backdated grant appended after the qualification
  (`VIOLATION_o5_ordering_circumvented: true`).

**`F2_RED_T6_TESTS_ON_F3_CHECKPOINT.txt`.** Ten of the 11 new tests fail
(4 failures, 11 errors). The failures are risk admitted after a later grant,
including a grant byte-identical to one made in a copied ledger. The errors
are the missing durable witness and its storage guard. The revocation control
passes.

### GREEN (repaired source)

**`F2_GREEN_AUDITOR_PROBE.txt`.** Both circumvention variants now end
`[false, "authority_unavailable"]` with `VIOLATION_o5_ordering_circumvented:
false`. Only those four keys changed from the recorded T5 result; the control is
still refused at recording.

**`F2_GREEN_ADJACENT_SUITES.txt`.** 215 tests OK, 1 skipped. The set is the 11
F-2 tests plus every retained suite on the adjacent authority and composition
paths:

- O-5 and H6 (`test_astra_t5_approval_ordering`, `test_astra_t5_hostile_preaudit`);
- B6 (`test_astra_t2_b6_approval`);
- qualification evaluation and ranking (r3, r4, s3 manifest/output/v3
  adversarial, registry and selection);
- risk, execution, release, owner binding and replay suites, including T6 F-3.

**`F2_CAUSALITY_ENUMERATION.txt`.** Static inventory of `src/genesis`:

- Qualification rows are appended only by `QualificationRecordStore.append`,
  which `QualificationAuthority.evaluate` calls.
- Witness rows are appended only through `_ApprovalWitnessLog.transaction`,
  from `_record_witness`.
- `get_for_new_risk` is called by `approve`, `consume_for_order`,
  `approval_still_valid`, the adapter's `create_intent`, `bind_risk` and
  `_recertify_record` (used by `transition` and `recertify`), and
  `rank_qualified_v3`.
- All seven read-lock sets that name the approval ledger also lock the witness
  log.

Dynamic trace: the complete discovery (387 tests, 0 failures, 0 errors,
1 skip) was run with `AppendOnlyJsonl._append_exactly` and `get_for_new_risk`
instrumented.

| Count | Observation |
|---|---|
| 305 | V3 qualification rows written through the recording path; every one already had its witness |
| 308 | witness rows, all through the guarded storage and all before their record. The three extra are witnesses with no recording-path record after them. Two come from retained S3 tests whose frozen-input proof fails at qualification commit (`test_pit_correction_at_qualification_commit_cannot_escape_proof`, `test_source_block_at_qualification_commit_cannot_escape_proof`); one is the squatting test's copied-ledger witness. A per-test count over those modules identified them |
| 6 | V3 rows written by tests' raw instruments: five without a witness (the raw-route and legacy tests), one duplicate row injected by the retained ambiguity test `test_qualification_ambiguity_at_transaction_entry_cannot_commit` for an already-witnessed record |
| 1,343 | admissions by `get_for_new_risk`; every one had its witness |

Causality violations: **0**. Children started by multi-process tests are not
instrumented, but they run the same code.

**`F2_FULL_SUITE_AND_STATIC.txt`.** complete discovery (`python -m unittest discover -s tests -t . -v`) in
a fresh clone with the final code bytes and no concurrent load:

- **387 tests OK, 1 skipped**, 503.5 s. That is the F-3 checkpoint's 376 plus
  the 11 F-2 tests; the skip is the Windows symlink-privilege test H3.
- `compileall -q src tests tools remediation_evidence/T6` exits 0.
- `git diff --check 7a548ff` exits 0.
- No test left files behind.

**`F2_STATIC_GATES.txt`.** `git diff --cached --check` over the complete staged
change set (excluding only itself and the hash list), the staged file list, and
an empty frozen-path diff for `DECISIONS`, `v04_pack`, `config`,
`V04_MIGRATION_PLAN.md`, `requirements.lock`, `pyproject.toml`, `tools`,
`src/genesis/protected.py`, `src/genesis/protected_research_worker.py`,
`src/genesis/decision_output.py`, `src/genesis/registry.py`,
`src/genesis/owner_binding.py` and every earlier `remediation_evidence/` file.

## New tests (`tests/test_astra_t6_approval_causality.py`)

| Test | Case |
|---|---|
| `grant_reproduced_from_a_copied_ledger_never_admits_risk` | the smart copied-ledger attack; the later real grant row is asserted byte-identical to the copy's |
| `raw_written_qualification_never_admits_risk_after_a_later_grant` | the auditor's raw route |
| `recording_path_rerun_after_the_record_exists_adds_no_witness` | the public path cannot witness retroactively |
| `witness_storage_refuses_a_forged_or_late_witness` | the exact witness the path would write, offered through the storage after the record exists |
| `witness_storage_refuses_a_wrong_grant_before_the_record` | wrong grant hash, sequence or ledger |
| `copied_ledger_witness_neither_admits_nor_blocks_the_real_grant` | squatting |
| `pre_witness_v3_qualification_is_audit_only_for_new_risk` | legacy treatment: readable, verifiable, not spendable |
| `prior_grant_is_witnessed_and_admits_risk_after_relocation` | witness fields; approval, then consumption from a relocated deployment |
| `revoked_grant_blocks_new_risk_after_recording` | revocation after recording still blocks |
| `crash_after_the_witness_resumes_to_one_witness_and_one_record` | crash recovery |
| `concurrent_recording_of_one_qualification_has_one_witness` | concurrent recording |

## Residuals and limits

- **Raw writes.** Byte-level writes to the witness sidecar, or a generic
  `AppendOnlyJsonl` over its path, are history writes outside the same-user
  boundary, as for every JSONL authority (see the memo). So is deliberately
  replacing the real ledger or qualification log while recording.
- **Legacy V3 rows** become audit-only for new risk. The memo classifies this
  as B, with the operator decision recorded.
- **Not in this checkpoint:**
  - F-1.
  - Top-level documents (`HANDOFF.md`, `PROJECT_STATE.md`, `TEST_EVIDENCE.md`,
    `ARCHITECTURE.md`); update them at the T6 candidate.
  - Any package or candidate.
  - An organisationally independent review.
