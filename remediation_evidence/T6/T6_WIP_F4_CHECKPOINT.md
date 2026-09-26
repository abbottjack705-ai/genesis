# T6 WIP checkpoint: F-4 raw evidence Git binding (NOT the T6 candidate)

This checkpoint repairs only finding F-4 of the independent T5 review. F-1, F-2
and F-3 are not started. It is not the T6 candidate, carries no package, and
grants no authority: the foundation stays HOLD for protected, shadow and live
work.

## Base and scope

| Item | Value |
|---|---|
| Branch | `t6-remediation` |
| Base (frozen T5 candidate) | commit `6c2464e470fd5f82f53839492593a0c0ac1cd51f`, tree `9731b581310e0244ea40323bdad54f949c835dc0`, parent `42e46c7c0cbe0eee725172f9f56586c91f8040e5` |
| T5 package (read only) | `GENESIS_V04_T5_INTEGRATED_REAUDIT_6c2464e.zip`, SHA-256 `04becfb939863d967306e3ea472ca557f86f28127b7c040ab5e8a6dbb1683217` |
| Review report (read only) | `C:\Users\abbot\gv\out\GENESIS_V04_T5_INDEPENDENT_VERIFICATION_REPORT.md`, SHA-256 `edca08baa8d14d45d8e62cb33a415b6ab65295eabba48bbe27875386e7b22af8` |
| Review handoff (read only) | `C:\Users\abbot\gv\out\GENESIS_V04_T5_REMEDIATION_HANDOFF_F1_F4.md`, SHA-256 `f11e48c45cc5bc6f859fc7e0b1f99107bf21f6e700a8fa1f76a8e1d6db7bf81f` |

Both review hashes equal the review's own `GENESIS_V04_T5_REVIEW_HASHES.sha256`.
T5 history, every earlier `remediation_evidence/` directory, the T5 package and
all review evidence under `C:\Users\abbot\gv` are unchanged. The checkpoint's
own commit, tree and parent cannot appear inside the commit; they are recorded
after committing.

Changed paths relative to T5:

- `tools/genesis_audit_package.py`: the repair.
- `tests/test_astra_t6_raw_evidence_git_binding.py`: new permanent tests.
- `tests/test_astra_t4_evidence_package.py`: retained-test amendment (below).
- `.gitattributes`: stores `remediation_evidence/T6/*.txt` without end-of-line
  conversion, as for T4 and T5.
- `remediation_evidence/T6/`: this record, the two evidence scripts
  (`F4_AUDITOR_P1_DRIVER.py`, `F4_GATE_RUNNER.py`), ten transcripts and
  `F4_EVIDENCE_HASHES.sha256`, which lists every other checkpoint file.

## F-4 and the invariant

**Finding.** Under `verify --repo`, only `git_blob_bytes` members were compared
with Git. Raw evidence members were checked for completeness (O-3) but never for
content. A self-consistent rewrite of a raw member therefore passed `--repo`
with every caller pin. The auditor's reproducer is P1 in `probe_pkg_t5_pins.py`,
which changes `raw-worktree/remediation_evidence/T5/GREEN_FINAL.md`.

**Invariant.** With `--repo`, every raw-worktree member is byte-identical to the
Git blob of its `source_path` at the target commit. O-3 already makes every raw
member a tracked file of that commit, so every raw member is Git-backed. No
normalization or line-ending relation is accepted.

**Repair.** `_require_raw_equals_git` is the single statement of the invariant:

- `verify_package` calls it in the `--repo` branch, after the Git-blob check.
  Its error is `package raw evidence member differs from its Git blob: <member>`.
- `build_package` calls it before writing anything. A checkout whose raw-root
  bytes differ from Git, for example a `core.autocrlf=true` checkout of LF blobs,
  is refused and leaves no ZIP or sidecar behind.

The manifest schema (v2), the representation contract and every member row are
unchanged. The T5 package therefore still verifies and rebuilds byte for byte.

**Trust modes.** The verify report now names the mode explicitly:

| Mode | When | Fields | What it binds |
|---|---|---|---|
| `git_bound` | `--repo` given | `trust_mode: "git_bound"`, `raw_evidence_git_bound: true` | Git-blob and raw members are bound to Git objects. Historical artifacts, the commit and the raw roots are bound by caller pins. |
| `git_free_self_consistent` | no `--repo` | `trust_mode: "git_free_self_consistent"`, `raw_evidence_git_bound: false` | Nothing is bound to Git. Self-consistency and caller pins only. |

Git-free mode behaves exactly as before and is explicitly weaker. A
self-consistent forgery of any member, raw evidence content included, still
passes it unless the package SHA-256 is checked against an out-of-band value.

**Deviation from the handoff's suggested repair (recorded, stricter).** The
handoff suggested a schema-v3 declared relation such as `crlf_of_blob`, plus a
`--require-raw-equals-git` pin. This checkpoint instead enforces plain byte
equality whenever `--repo` is used, with no schema change and no new pin:

- A CRLF-transformed raw member is always rejected under `--repo`, never
  accepted "when declared".
- Evidence packages must be built from a checkout whose raw-root bytes equal
  their blobs. The T5 package was built from a `core.autocrlf=false` clone.

**Corrected R-3 wording.** This supersedes, without editing, the T5 sentence
"pins and `--repo` narrow what a forger can change, never more" and the T5
authority memo's R-3 paragraph:

- Until this repair, raw evidence content was forgeable with `--repo` and every
  pin.
- With this repair, the checks mean that `--repo` plus the complete pin set
  (`--expect-commit`, `--require-raw-root`, `--require-historical`,
  `--authority`) determines every member name and byte, and the manifest bytes,
  from Git and the pins.
- The ZIP container encoding is not determined. The out-of-band package SHA-256
  remains the only anchor for the exact file.
- Without `--repo`, or without a pin, the documented substitutions (P4, P6, P8,
  03a) remain possible.
- This is the producer's reading of its own checks, not an independent audit
  result.

## Evidence (all transcripts written as UTF-8 with LF by their scripts)

Execution environment:

- Short-path `core.autocrlf=false` clones under `C:\Users\abbot\t6\`. No test ran
  in the OneDrive repository.
- Windows 11 Pro 10.0.26200, CPython 3.12.10, Git 2.55.0.windows.3, 8 CPUs.
- Transcript headers record every uncommitted path with its SHA-256, and the
  tool bytes under test:
  - T5 tool `0b32c9ca4e0ab945290b836f5de8870757329c13c4279fe5d583d881d53367a4`
  - T6 tool `4206b6313312c6cb669350059807c63bbe8d057583af99bdd80de9a71c4a1052`

### RED (frozen T5 tool)

**`F4_RED_T5_AUDITOR_P1.txt`.** The auditor's unmodified probe (SHA-256
`e2543a5a…`, pins `2c0089ee…`, both equal to the review's recorded hashes), run
twice by `F4_AUDITOR_P1_DRIVER.py` on a clean clone of `6c2464e`:

- `P1_raw_content_forged_repo_all_pins` exits **0**.
- The forged package is byte-identical across runs:
  `a429e4fe454acb5b2b57a913f17cd3fd3aef73b16c13448db4eeb096207b8c71`.
- Its raw member (`4d220a32…`) differs from the Git blob (`add692e2…`).
- Every probe case equals the auditor's recorded exit.
- Driver case D1 (line endings only) also exits 0 under `--repo` with every pin.

**`F4_RED_T6_TESTS_ON_T5_TOOL.txt`.** The new T6 tests on the T5 tool fail (4
failures, 1 error), each for the F-4 reason:

- forged raw evidence verifies against Git;
- the builder packages non-Git raw bytes;
- no trust mode is reported.

### GREEN (T6 tool)

**`F4_GREEN_T6_AUDITOR_P1.txt`.** Same driver, probe and inputs; the forged
package is again `a429e4fe…`.

- P1 under `--repo` with every pin exits **1**:
  `package raw evidence member differs from its Git blob: raw-worktree/remediation_evidence/T5/GREEN_FINAL.md`.
- P1 is the only case whose exit changed from the auditor's result. P2 to P10
  are unchanged.
- D1 is rejected under `--repo`. D2 (raw and Git-blob members forged together)
  stays rejected by the existing source-inventory check.
- Git-free runs pass and report `git_free_self_consistent`.
- The genuine T5 package verifies `git_bound` with every pin.

**`F4_GREEN_PACKAGE_TESTS.txt`.** 17/17 OK: the 3 T6 tests and the 14 retained
package tests (T4, T5 package, T5 hostile H5).

**`F4_GREEN_PRIOR_B8_TAMPER_SUITE.txt`.** The prior auditor's unmodified 23-case
suite (`3f36c4ae…`). Every case's exit and expectation flag equal the T5
review's recorded results (`changed []`). The suite exits 1 for its two
T4-era expectations, 09 and 11, exactly as in the review.

**`F4_GREEN_T5_PACKAGE_REBUILD.txt`.** The T6 builder rebuilt the T5 package
from a clean `autocrlf=false` checkout of `6c2464e`, with the same historical
inputs and ADR pins. The ZIP `04becfb9…` and sidecar `80fd6775…` are
byte-identical to the originals.

**`F4_FULL_SUITE_AND_STATIC.txt`.** Complete discovery
(`python -m unittest discover -s tests -t . -v`) in a fresh clone with the final
code bytes and no concurrent load:

- **364 tests OK, 1 skipped**, 269.4 s. That is T5's 361 plus the 3 T6 tests.
- The skip is the known Windows symlink-privilege test
  `test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not`, which
  remains unverified on this host.
- `compileall -q src tests tools remediation_evidence/T6` exits 0.
- `git diff --check 6c2464e` exits 0 for the modified tracked files.

**`F4_STATIC_GATES.txt`.** Runs over the complete staged checkpoint change set,
new files included. It excludes only itself and `F4_EVIDENCE_HASHES.sha256`,
which are written after it.

- `git diff --cached --check 6c2464e` exits 0.
- The staged file list and stat are recorded.
- The frozen-path diff is empty for `DECISIONS`, `v04_pack`, `config`,
  `V04_MIGRATION_PLAN.md`, `requirements.lock`, `pyproject.toml`, `src`, and
  every `remediation_evidence/` directory except `T6`.

## Retained-test amendment (T4 fixture and one assertion)

`tests/test_astra_t4_evidence_package.py` changes in two places:

1. **Fixture.** It adds `.gitattributes` `evidence/** -text` to the synthetic
   repository. The CRLF transcript's blob then keeps its CRLF bytes and equals
   the raw member. Every other fixture byte is unchanged, and `core.autocrlf=true`
   still makes the ADR and source checkouts differ from their blobs, so the
   Git-blob exactness tests keep their discriminating power.
2. **Assertion.** `test_raw_worktree_and_historical_bytes_are_distinct_labeled_representations`
   asserted that the raw bytes *differ* from the blob and agree only after CRLF
   normalization. That is the F-4 root cause itself. It now asserts byte equality
   and that the raw bytes still contain CRLF, i.e. they were not normalized.

The old scenario is now the permanent negative test
`test_t6_builder_refuses_raw_evidence_that_differs_from_git`, together with the
line-ending subtest of the forgery test.

Neutrality evidence:

- **(a)** `F4_NEUTRALITY_A_ADJUSTED_FIXTURE_ON_T5_TOOL.txt`: with the amended
  file, all 14 retained package tests pass on the frozen T5 tool. The fixture
  change alone alters no outcome.
- **(b)** `F4_NEUTRALITY_B_T5_TESTS_ON_T6_TOOL.txt`: the unmodified T5 test bytes
  on the T6 tool fail 14/14 with one cause only, `package raw evidence member
  differs from its Git blob: raw-worktree/evidence/raw.txt`. That is the new
  refusal, and it is why the fixture changed.

`tests/test_astra_t5_package_evidence.py` and `tests/test_astra_t5_hostile_preaudit.py`
are unchanged.

## Not in this checkpoint

- F-1, F-2 and F-3.
- Top-level documents (`HANDOFF.md`, `PROJECT_STATE.md`, `TEST_EVIDENCE.md`,
  `ARCHITECTURE.md`). They stay accurate but do not yet describe the trust modes;
  update them at the T6 candidate.
- Any T6 evidence package, final gate set or candidate.
- Protected-set load reruns, which F-4 does not touch.
- An organisationally independent review of this repair.
