# T6 authority memo: F-2, durable approval causality for V3 qualifications

Date: 2026-09-26 (Europe/London)

Base: the T6 F-3 WIP checkpoint `7a548ff52cd12ffec35bcb878b22255d1844968a`,
which is not rewritten. The finding is F-2 of
`GENESIS_V04_T5_INDEPENDENT_VERIFICATION_REPORT.md`. The authority for the
repair is that report and its handoff,
`GENESIS_V04_T5_REMEDIATION_HANDOFF_F1_F4.md`. This memo classifies and
describes one construction. It grants no GO and creates no approval, strategy,
model, tier or TTL.

Classification scale (as in T2–T5):

- **A**: a correction the audit requires, with no change to an approved ADR,
  historical identity or record meaning.
- **B**: a new durable fact or schema added beside unchanged history.
- **C**: would need a new ADR version and operator approval.

## Finding

T5's O-5 check ran only through the appending store instance's own output,
binding and approval objects, when a qualification was recorded. Nothing
durable linked a qualification to the grant that existed at that moment. At
risk time, `get_for_new_risk` checked only that a matching unrevoked grant
exists now with `approved_at <= decision_at`.

A qualification recorded before its human grant could therefore become
spendable later. The review reproduced this through two routes:

- a second store over the same qualification log, composed with a copied
  approval ledger that holds a grant;
- a raw append of the qualification row.

In each, a backdated grant appended later to the real ledger admitted risk.

**Additional producer observation.** A grant row is deterministic: its chain
position plus fields the caller chooses. A grant appended later to the real
ledger can therefore be byte-identical to one appended earlier to a copy of it
(`test_t6_grant_reproduced_from_a_copied_ledger_never_admits_risk` asserts the
two rows are equal). Binding a qualification to a grant-row hash alone,
Option A read literally, would not establish order. The identity of the ledger
that was checked is essential.

## Invariant (durable causality)

For every V3 qualification used for new risk, risk can verify from durable
facts that exactly one unrevoked grant row existed in the risk-bound approval
ledger before the qualification row was recorded.

## Construction (`selection.py`; five read-lock sets in `risk.py` and `execution.py`)

**Witness sidecar.** The sidecar is
`<qualification log>.approval-witness.jsonl`, schema
`qualification-approval-witness-v1`. Each row carries:

| Field | Content |
|---|---|
| `qualification_record_id` | the record witnessed |
| `decision_output_hash`, `decision_at` | the record's decision identity |
| `binding_hash`, `approval_reference` | the approval relied on |
| `approval_ledger` | the ledger's identity relative to the qualification log's directory, computed as N2 owner identity |
| `grant_record_hash`, `grant_sequence` | the exact grant row |

For approval references that are not ledger references (legacy v1
content-addressed notes and fixture-only references), `approval_ledger` and the
two grant fields are null.

**Recording.** `QualificationRecordStore.append` of a new V3 record works in
two steps:

1. It first appends the witness in its own transaction, under the
   qualification-log, binding and ledger locks. It does so only while the
   record is absent and the exact unrevoked grant, with
   `approved_at <= decision_at`, exists.
2. The record append then requires exactly that witness, under the witness
   log's lock as well.

Re-appending an existing record is idempotent and never adds a witness. A crash
between the two steps leaves a harmless witness; retrying records the row once.

**Guarded witness storage.** `_ApprovalWitnessLog` checks every append, from
any caller holding the store, under the same locks. The row must:

- be the first witness for that record and ledger;
- be for a record that does not exist yet;
- equal the witness the recording path computes at that moment.

A witness can therefore never follow its record, and no other witness can be
written through the store.

**Admission.** `get_for_new_risk` is the single admission check behind every
new-risk path:

- `approve`, `consume_for_order` and `approval_still_valid`;
- the adapter's `create_intent`, `bind_risk`, `transition` and `recertify`;
- `rank_qualified_v3`.

It now requires exactly one witness for the risk-bound ledger identity, equal
to the grant as the risk-bound ledger holds it now. The existing checks remain:
unrevoked, binding match, `approved_at <= decision_at`, active binding and
lineage. Witnesses are matched per ledger identity. A witness of a copied
ledger's grant therefore neither admits risk nor blocks the real grant's
witness.

**Why this proves order.** A witness is appended only after its grant exists
in the named ledger (checked under that ledger's lock). It is appended only
while its record is absent from that log (checked under the log's lock). The
risk authority reads the witness beside its own bound qualification log and
compares it with its own bound ledger. Hence, in real time: grant, then
witness, then record.

**Handoff options.**

- **Option A** (a sidecar fact carrying the grant `record_hash` and ledger
  identity): adopted, and extended with the storage guard.
- **Option B** (binding the qualification store's sub-stores to the risk
  authority): not adopted. Admission checks the witness against the risk-bound
  ledger, so a qualification recorded through any other composition is simply
  unspendable (fail closed). No new composition coupling or owner kind is
  needed.

## Classification: B

- **A new durable fact beside unchanged history**, as with the N2/H1 sidecars.
  No qualification, approval, binding, output, risk or order row changes bytes,
  fields, identity or canonicalization. `qualification-record-v3` and every
  ADR-0002 schema are untouched. No retained test was amended.
- **Enforcement of an existing ADR rule.** ADR-0002 already says runtime "may
  create a risk-authorising v3 qualification only when separately approved,
  active, exact strategy-specific resolver/rule bindings exist". It also says a
  missing or incompatible approval causes `PASS`/block. T6 adds no authority;
  it makes that rule verifiable at risk time.
- **Legacy treatment.**
  - V3 rows recorded before T6 carry no witness. They become audit-only for new
    risk: still readable, replayable and settleable.
  - This is the handoff's instruction ("Historical rows remain audit-only,
    following the existing v2 precedent"), and the ADR's treatment of missing
    approval evidence.
  - Operational `QUALIFY` has never been enabled, because no approved
    strategy-specific resolver exists. Only synthetic fixture rows are affected.
- **Operator decision recorded.** If the operator reads this legacy change as a
  material change of legacy treatment under ADR-0002's approval clause, it is C
  instead and needs an ADR version and operator approval.

## Unchanged

- ADR bytes and `protected.py`.
- Every historical record.
- B6's acyclic construction (reserve, then bind, then grant).
- T5's recording-time O-5 check, which now also returns the witness.
- Revocation after recording still blocks new risk.

## Residuals (attack these)

- **Byte-level writes.** Writing raw bytes to the witness sidecar, or through a
  generic `AppendOnlyJsonl` constructed over its path, is a history write
  outside the same-user trust boundary. That is the same as for every JSONL
  authority (T5 residual 1 and the F-3 boundary). Deliberately replacing the
  real ledger or qualification log while recording is the same class.
- **Witness without record.** A witness may exist whose record was never
  written, for example after a failed proof check. It records only that the
  grant existed while the record was absent, so it cannot violate the
  invariant.
- **Unchanged T5 residuals:** first-composer trust, deployment forks and
  sidecar deletion.
