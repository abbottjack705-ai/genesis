# T4 / B8 authority and construction memo

Date: 2026-09-25 (Europe/London)

Sealed base: commit `39a21328f76cb522bb5b198af1c1e76485d6fe5f`,
tree `b730ee8423accaaa56308558cf8d3d513e948670`.

Scope: B8 evidence/package representation only. T1–T3 production semantics,
all approved decisions and every historical artifact remain immutable. No GO is
authorized.

## Exact defect and retained RED

The original S5 producer ZIP contains 192 tracked files whose bytes all differ
from commit `27dd525` Git blobs, while every difference disappears after
CRLF-to-LF conversion. Its manifest lists repository hashes without saying
whether they identify Git blobs, checkout bytes or ZIP members. In particular,
the archived ADR-0002 and ADR-0003 hashes differ from their approved/committed
hashes. Six S5 transcript hashes instead identify the CRLF working/archive
representation, but that representation is not separately labeled.

`HISTORICAL_B8_RED_T3.txt` records four methods, five assertion failures and
zero errors against the untouched original archive/manifest. The independent
five-test future-package contract is separately RED on sealed T3 with five
assertion failures and zero errors; see `INDEPENDENT_B8_RED_T3.txt`.

## Authority classification

Classification: **A — already-authorized evidence/packaging repair**. B8's audit
acceptance explicitly requires byte-preserving Git/ADR snapshots, separately
labeled raw transcript bytes, preservation of the original archive, exact
manifests/hashes and verification after fresh extraction. Implementing that
contract changes no Project Law, ADR, identity preimage, runtime topology,
strategy rule, policy or product behavior. No new ADR or human decision is
required.

A class-C decision would be required if the repair redefined an approved ADR
hash, normalized or replaced a historical transcript/archive, changed a product
identity, or treated checkout conversion as authoritative source. None is
proposed. Any need to do so must stop T4.

## Smallest compliant construction

1. Add one audit-only command-line packager/verifier under `tools/`; change no
   `src/genesis` module.
2. Read the target source snapshot from Git plumbing at an exact commit. Store
   every raw Git blob under `git-blobs/` and record repository path, Git object
   ID/mode, byte length, SHA-256 and representation
   `git_blob_bytes`. Never source this snapshot from a checkout or normalize it.
3. Copy selected worktree evidence under `raw-worktree/` with representation
   `raw_worktree_bytes`. Copy the original S5 archive/manifest/handoff and audit
   artifacts under `historical/` with representation
   `historical_raw_artifact_bytes`. Preserve exact bytes even when another
   representation normalizes equal.
4. Pin approved ADR paths to their approved SHA-256 values and require the
   corresponding Git-blob member to match before building or verifying.
5. Put a closed versioned manifest inside a deterministic ZIP. Hash every member
   other than the manifest; authenticate the finished ZIP with a separate
   sidecar to avoid self-reference.
6. Verify member uniqueness, safe paths, closed representations, hashes/lengths,
   target commit/tree and authorities. Optionally cross-check every source member
   against Git. Verify a fresh extraction without requiring Git and reject
   tampered/duplicate members.
7. After the T4 commit exists, build the integrated re-audit package externally
   from that exact commit. This is necessary because a commit cannot contain its
   own final commit/tree/package hashes. Record those identities in the external
   manifest/sidecar and the handoff response, without amending T4.

## Expected files

- `tools/genesis_audit_package.py`: deterministic builder and strict verifier.
- `tests/test_astra_t4_evidence_package.py`: byte, representation, authority,
  fresh-extraction, tamper and determinism tests.
- `remediation_evidence/T4/`: immutable RED, memo and GREEN evidence.
- `ARCHITECTURE.md`, `PROJECT_STATE.md`, `TEST_EVIDENCE.md`, `HANDOFF.md`:
  truthful local B8 closure and re-audit-only disposition.
- external `outputs/GENESIS_V04_T4_INTEGRATED_REAUDIT_*`: generated only after
  the T4 commit and verified from a fresh extraction.

## RED to GREEN matrix

| Invariant | Sealed-T3 RED | Required GREEN |
|---|---|---|
| Source representation | 192/192 archive members differ from Git blobs | every `git-blobs/` member equals the exact target blob |
| Approved authority | archived ADR hashes differ from approved hashes | pinned ADR Git-blob members equal approved hashes |
| Representation semantics | producer rows omit representation | every member has one closed representation label |
| Raw evidence | transcript hashes are absent/conflated | raw worktree/transcript bytes are separately hashed and retained |
| Historical preservation | replacing/normalizing would erase evidence | original archive/manifest bytes are embedded unchanged |
| Fresh extraction | old manifest cannot establish intended bytes | complete hash/length/path/authority verification without Git |
| Git cross-check | checkout conversion can masquerade as source | optional verifier compares every source member to target Git object |
| Tamper/determinism | no producer contract | duplicate/tampered members reject; repeated build is byte-identical |

## Untouched invariants

- ADR-0002 remains SHA-256
  `7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`.
- ADR-0003 remains SHA-256
  `0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`.
- Original failed transcripts, producer archive and audit evidence are never
  overwritten, normalized, relabeled as Git bytes or deleted.
- Candidate/output/approval/order/risk/settlement/quota/protected identities and
  all T1–T3 code remain unchanged.
- Objective, odds/stake/risk law, quota Interpretation A, hold-to-settlement,
  one-candidate/one-intent, UNKNOWN/no-auto-retry and offline/PAPER status remain.
- No adapter, shadow research, protected campaign or live-money GO follows.
