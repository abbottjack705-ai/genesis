# T5 authority memo: N1, N2, N3, O-5 and O-1/O-2/O-3 (plus H1, PA-1)

Date: 2026-09-26 (Europe/London)

Base: sealed T4 `ac6b66be9dc119a75a0dfb772890cfd2c3919c52` (tree
`730b931ed8f6b5fa066a60e9de8467f5d6b6ebd7`), through the three unmodified WIP
resume checkpoints `220c4d0` → `582459b` → `42e46c7`
(`42e46c7c0cbe0eee725172f9f56586c91f8040e5`). None of those commits is
rewritten. The T5 candidate is one further commit on top of `42e46c7`.

Findings closed here are those of
`GENESIS_V04_T1_T4_INDEPENDENT_HOSTILE_REAUDIT_REPORT.md` (foundation HOLD,
adapter NO-GO), plus two defects found during T5's own hostile pre-audit. This
memo classifies and describes constructions. It grants no GO.

Classification scale (as in T2–T4): **A** = a correction the audit requires,
with no change to an approved ADR, historical identity or record meaning;
**B** = a new durable fact or schema added beside unchanged history; **C** =
would need a new ADR version and operator approval. No T5 change is C.

## N1 (HIGH) — protected-research closure (WIP checkpoints; summarized)

Implemented in the three WIP checkpoints and described in
`T5_RESUME_HANDOFF.md` §5, §7a and §8; evidence `N1_*` in this directory. It is
summarized here because T5 seals it.

- Every code object of the hashed program is statically audited (forbidden
  reflection/eval names; only top-level, level-0 imports of allowed modules;
  control modules such as `importlib`, `sys`, `builtins`, `gc`, `ctypes` are
  denied). Import roots now only locate the one hashed module; they are no
  longer placed on `sys.path`, so unhashed helper code under a root cannot run.
- The program executes with restricted builtins and a guarded `__import__`; a
  meta-path origin guard refuses research-root modules; a permanent
  closure-captured PEP 578 audit hook is armed only while research code runs;
  post-execution checks reject any live `FutureOutcomeLabel`, foreign research
  code objects and changed interpreter state, and latch the worker poisoned.
- One research worker per `ProtectedEvaluationClient`, still started before
  labels and the evaluator endpoint exist, is permanently bound in parent and
  worker to the first valid program digest. A different digest fails with the
  fixed generic error in that client and can certify in a fresh client.

**Classification A.** `ResearchProgramRef-v1` identity, the fresh label-free
worker topology and its pre-label/pre-evaluator ordering, attempts and
certificates are unchanged. ADR-0003 already requires changed code and
label-bearing state to fail generically; refusing unhashed helper imports is the
fail-closed closure route the audit itself offered ("reject every import ... the
audit cannot bind"). The retained T3 test
`test_changed_module_executes_new_verified_bytes_not_cached_callable` was made
stricter in WIP (changed digest refused in the bound client, certifies in a
fresh one); retained S5/R9 fixtures were relocated verbatim into
`tests/protected_research_programs.py`, shown behaviour-neutral on sealed T4.

**PA-1 (found by the WIP hostile self-audit).** A research callback could write
a forged artifact line to the inherited stdout IPC. Every parent request now
carries a fresh 64-hex nonce that the callback never sees; every reply
(including errors) must echo it; replies are one canonical JSON line with
unique keys; a queued unrequested line or protocol violation kills the worker.
Evaluator round trips are serialized. Classification A.

**N1 platform rerun (T5 candidate).** Every protected suite passed on the
target Windows 11 / CPython 3.12.10 at `42e46c7`
(`T5_BASELINE_WINDOWS_42e46c7_FULL.txt`). Two final-gates attempts then failed
intermittently in full discovery: two retained R9 tests
(`T5_FINAL_GATES_ATTEMPT_1_R9_TIMEOUT.txt`) and, after a partial fix, one WIP
lifecycle test (`T5_FINAL_GATES_ATTEMPT_2_LIFECYCLE_TIMEOUT.txt`). In each, a
trivial research request exceeded the fixed 10 s research timeout and failed
closed with "protected research unavailable", which consumes a nonrefundable
protected attempt. The cause is in the WIP N1 worker: every post-execution
`require_clean` scan (three per request) resolved the source path of each
live function (about 3,500) with `os.path.realpath` and then tested it against
the roots with `Path.is_relative_to`, most of a second of CPU per scan on
Windows. The timeout is deliberately bounded (a retained S5 test requires an
11 s program to time out), so it was not raised. Instead each distinct path
string is resolved and classified once per scan
(`test_astra_t5_worker_scan_cost.py`; RED 2,974 resolutions for 112 paths in
`T5_N1_SCAN_COST_RED.txt`, then RED 2,975 root checks for 112 paths after the
first partial fix in `T5_N1_SCAN_COST_RED_2.txt`). No research code runs
during a scan, so what it accepts and rejects is unchanged. In
`T5_N1_LATENCY_AB.txt` the median `run()` falls from 2.16 s to 0.15 s
unloaded, and the retained lifecycle sequence under eight busy CPU processes
fails 11 of 12 times with the WIP worker and 0 of 12 with the T5 worker (0 of
12 also under sixteen; the WIP worker's sixteen-process run failed its first
iteration and then aborted). Classification A.

## N2 (MEDIUM) — composed-owner identity bound (`owner_binding.py`)

**Invariant.** One risk authority acts through exactly one owner per authority
kind. Any individually valid but different owner fails closed at admission,
consumption, submission, proof issuance, attachment and release; the same
owner reopened through another object or an equivalent path, a restart and a
complete relocated deployment keep working.

**Construction.**

- Owner identity is the owner's location relative to the risk log's directory,
  with only the directory resolved and the final name kept literally. That is
  exactly how the owner's coordinator lock resolves, so one identity is always
  one lock (the existing mode precedent compares `coordinator_path.resolve()`).
  A file-symlink alias therefore counts as a different owner, and a relocated
  whole tree keeps every relative identity.
- A sidecar append-only JSONL `<risk log>.owners.jsonl`
  (`risk-owner-binding-v1`) binds each kind the first time a constructor
  presents it and never rebinds it. Kinds: bankroll, safety, qualification,
  its binding/approval ledgers and decision-output store, strategy, mode,
  order, market, refresh, release proof and ledger. The risk log itself is not
  touched, so every historical row count and meaning is unchanged.
- `RiskEngine` binds its own owners; `PaperExecutionAdapter` binds its order,
  market and refresh stores; `OfflinePaperReleaseProofStore` binds its proof
  log and ledger. Execution and proof registration is anchored on the order
  log, so a composition over a foreign order log can never claim an unbound
  ledger or market first. Constructors never raise on a mismatch (audit reads
  of a mismatched composition stay possible); actions refuse it.
- Checks (transactional ones hold the sidecar's lock with the action's other
  locks; bindings are write-once, so the adapter's own pre-consumption check
  cannot go stale): `approve` (`owner_authority_mismatch`), `consume_for_order`,
  `approval_still_valid`, `release_with_proof`, `attach_release_proofs`,
  `reserved_exposures`, `risk_ok`, `rebase`; adapter `create_intent`,
  `bind_risk` (before consumption), submission recertification and
  `recertify` (`owner_authority_mismatch`); proof issuance. Swapped owner
  attributes are caught because every check reads the current objects, and
  admission/consumption also refuse an owner changed mid-transaction.
- Factual `record_exposure` and a reservation's move to UNKNOWN are not
  gated: both only make the authority more conservative, and B2 requires
  further real exposure to stay recordable.

**Classification B.** New sidecar facts are added beside unchanged history. No
approval, order, settlement, qualification or risk row changes meaning.

## H1 (new, MEDIUM, found in T5 hostile pre-audit) — reverse owner binding

**Defect (RED retained in `T5_HOSTILE_H1_RED_WIP.txt`).** N2's forward binding
does not stop a *second* risk log from being composed over the same owners. A
second `RiskAuditLog` sharing the qualification store, bankroll and safety
approved the same candidate again (`risk_approved`, 7.5 charged in each log).
With two order logs that is one candidate sent twice, and a shared bankroll
gets two separate 60% open-liability ceilings. Predates T5 (present at T4).

**Construction.** The owners that carry portfolio capacity or candidate
lineage (bankroll, qualification log, decision-output store) get a write-once
claim sidecar `<owner>.risk-authority.jsonl` (`risk-owner-claim-v1`) naming the
single risk log they serve, relative to the owner's directory. It is written
only once the owner is that authority's bound owner, so a mismatched copy never
acquires a claim. Every owner check also requires those owners to claim this
risk log. Safety/mode (one global kill switch), strategy, market, refresh,
order, proof and ledger owners may be legitimately shared and carry no claim.
Relocated and restarted single authorities still approve.

**Classification B**, same basis as N2.

## N3 (LOW) — risk appends can never brick replay

**Construction.** `AppendOnlyJsonl.chained()` now computes the exact appended
row, chain fields included, and `transaction` uses it (byte-identical output).
Every risk-log append — `record_exposure`, `approve`, `consume_for_order`,
`transition_reservation`, `release_with_proof` — wraps its builder so the
verified history *plus that exact row* must replay through `_exposures`, under
the same locks, before any byte is written. A factual exposure colliding with an
approval ID, or an approval colliding with a prior exposure
(`risk_identity_collision`), is refused and the authority stays live. The
builder is wrapped rather than `transaction` given a new keyword, because
retained tests legitimately wrap `transaction` with fixed signatures.

**Classification A.** Pre-existing already-poisoned logs still fail closed on
replay exactly as before; T5 only prevents new poisoning.

## O-5 (LOW) — approval must exist before it is relied on

**Construction.** `QualificationRecordStore.append` of a new V3 record now
requires, under the qualification log plus the binding and approval ledger
locks, the record's decision output, its binding active at `decision_at`, and
the exact unrevoked human grant (`_require_separate_approval`, the production
validator or the fixture override) with `approved_at <= decision_at`. A grant
appended later — backdated or not — can never be the grant that admits that
qualification. Idempotent replays of an existing record are unchanged.

**Classification A.** No approval, binding or qualification bytes or identities
change; B6's acyclic construction is untouched. Risk-time validation remains.

## O-1 / O-2 / O-3 (LOW) — package verification pins

**Construction (tools only).** Manifest schema `genesis-audit-evidence-package-v2`
adds `raw_worktree_roots`. Verification now: parses exactly one canonical
manifest encoding (duplicate keys, non-finite numbers and any non-builder byte
form are rejected; O-2); requires each declared raw root to hold exactly the
target commit's tracked files beneath it, every raw member to lie under a
declared root, and raw/historical `source_path` to agree with the archive path
(O-3); and accepts caller pins `--expect-commit` (O-1), `--require-raw-root`
and `--require-historical LABEL=SHA256`, each compared exactly. The builder
self-verifies with all of them.

**Classification A.** Historical bytes, the T4 package and its sidecar are
unchanged. The T5 verifier accepts only v2; the sealed T4 package remains
verifiable with the T4 tool (`git show ac6b66b:tools/genesis_audit_package.py`).
R-3 is unchanged and documented: without an out-of-band package hash, a
self-consistent forgery that also drops a whole root, member row and file can
still pass unpinned verification.

## Retained-test amendments

1. `tests/test_astra_s1_reservation.py::test_missing_or_conflicting_exact_reservation_never_certifies`
   created its conflicting state with the N3 poisoning append through
   `record_exposure`, which the N3 RED suite requires to be refused.
2. `tests/test_astra_t1_dependence.py::test_d03_missing_output_binding_and_legacy_v2_do_not_default_empty`
   recorded a V3 qualification whose output binding does not exist, which O-5
   requires to be refused.

Both now seed the byte-identical hash-chain-valid row the pre-T5 API wrote,
and every assertion is unchanged. `T5_RETAINED_AMENDMENT_NEUTRALITY.txt` proves
on sealed T4 that the seeded rows equal the API rows byte for byte, and that the
original and amended tests both pass there. On T5 the original setup is refused
exactly by N3/O-5.

## Residual limits (attack these)

- Owner binding is trust-on-first-use per kind and per claim; whoever composes
  first defines the deployment. Deleting or pre-writing a sidecar is a JSONL
  history rewrite, outside the same-user trust boundary. A deliberate fork (the
  whole deployment, or content re-recorded into separate stores) is independent
  and cannot be detected locally.
- `AppendOnlyJsonl` locks resolve directories but not file symlinks. T5 makes
  owner identity follow the lock, so a file-symlinked alias is refused as a
  different owner; two writers to one risk log through a file symlink remain a
  pre-existing filesystem-level hazard. Symlink tests skip on this Windows
  account (no symlink privilege).
- Risk logs, or qualifications recorded without a grant, that were already
  written before T5 keep their historical replay behaviour.
- Research isolation is same-user process isolation, not an OS security
  principal; real protected activation remains disabled.

## Disposition

T5 is a local candidate for independent hostile review only. Foundation remains
HOLD; adapter NO-GO. No adapter, shadow research, protected campaign or
live-money work is authorized, and no strategy, model, tier, TTL or human
approval was created.
