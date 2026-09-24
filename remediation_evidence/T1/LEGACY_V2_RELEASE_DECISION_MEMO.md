# T1 decision memo — legacy-v2 terminal settlement proof

Date: 2026-09-24
Status: implementation-authorized, additive versioned repair; no new ADR

## Exact conflict

Retained test:
`tests.test_astra_s3_v3_adversarial.AstraV3AdversarialTests.test_legacy_order_is_audit_replay_only_but_can_finish_settlement`.

The preserved pre-change run reaches the final risk-reservation transition and
errors at `RiskEngine.transition_reservation(..., SETTLED)` with:

```text
genesis.registry.RegistryConflict: terminal reservation requires exact release proof
Ran 1 test in 0.771s
FAILED (errors=1)
```

The exact transcript and original blobs are retained in
`retained_terminal_prechange_transcript.txt`. The test's original invariant is
two-sided: the historical v2 identity remains incapable of authorizing any
new intent/consumption, while its already-existing sent and fully matched
order remains able to settle and release its reservation.

## New proof requirement that exposed it

B3 correctly makes a caller's bare `SETTLED` or `VOID` label non-authoritative.
A consumed reservation may become spendable only through a durable proof that
is validated under the same risk/order/ledger fence and binds the approval,
qualification lineage, exact order head, complete fill set, and current
terminal settlement heads. A stale proof, late fill, incompatible correction,
UNKNOWN state, or identity mismatch must retain/restore the full charge.

The current `offline-paper-release-proof-v1` additionally requires a
`decision_output_hash`. That is correct for v3, but impossible for an honest
v2 qualification.

## Actual historical v2 evidence and identity

The existing history has all of the following authoritative facts:

- an immutable `qualification-record-v2`; its `qualification_record_id` is the
  SHA-256 of its canonical v2 content, and its append-only
  `record_hash` identifies the exact durable row;
- the unchanged legacy `candidate_decision_hash` and strategy contract hash;
- one exact `risk-approval-v2`, including approval ID, qualification ID,
  candidate hash, side, odds, stake/liability, bankroll, policy, safety and
  issue/expiry facts;
- one exact consumption binding approval, candidate and order ID;
- the PAPER order intent and append-only state/head lineage;
- exact fill rows and current same-fill terminal settlement/void heads in the
  settlement ledger.

It has no `decision_output_hash` or `feature_manifest_hash`, by design.
Creating either would rewrite history and violate the v2 identity contract.

## Governing authority

- Approved ADR-0002 v1, `Legacy, failure and activation rules`, states that
  v1/v2 hashes and events retain their original meaning, existing sent/matched
  orders may reconcile and settle under R7/S1, no old record is rewritten, and
  legacy identity is audit-only for new qualification, approval, pending and
  send actions.
- `PROJECT_STATE.md` records the same approved S3b invariant: legacy history is
  readable and terminal settlement remains legal, but legacy identity cannot
  authorize new actions.
- Project Genesis requires exact order/settlement reconciliation and the
  Project Laws preserve hold-to-settlement.
- B3 requires proof-bearing release and forbids bare terminal labels from
  creating capacity.
- ADR-0002 requires new approval only if legacy treatment or identity meaning
  changes materially. This repair implements its already-approved treatment;
  it does not change either identity.

## Smallest backward-compatible solution

Add a separate, explicitly audit-only schema and path:

- `offline-paper-legacy-release-proof-v1`, scoped to
  `LEGACY_AUDIT_SETTLEMENT_ONLY`, for consumed, already-sent/matched v2 orders;
- bind the exact v2 `qualification_record_id` and durable qualification
  `record_hash` instead of a nonexistent v3 output;
- retain the exact approval, consumption, candidate, order-head, full fill-set,
  terminal-head, amount, reason and issuance-time checks used by B3;
- add a separate `risk-reservation-legacy-release-v1` event rather than
  changing or overloading `risk-reservation-release-v1`;
- validate both schemas under the same append locks; duplicate replay remains
  idempotent, and a late fill or incompatible head restores UNKNOWN/full
  charge on replay;
- expose no path from the legacy proof to qualification, approval, intent,
  pending or sent submission. The existing v3-only new-action gates remain
  unchanged.

All existing v1 proof rows, v1/v2 candidate hashes, v2 qualification hashes,
v3 output identities and current risk-release rows remain byte-for-byte and
semantically unchanged.

## Authority classification

This is class **A + B**, not class C:

- **A — implementation repair already required by existing authority:** make
  approved legacy terminal settlement coexist with B3's proof requirement.
- **B — compatible additive schema evolution:** a new audit-only proof/release
  schema represents evidence that the v3 schema intentionally cannot express.
- **Not C:** it neither changes candidate identity nor authorizes a new action,
  risk policy, strategy rule, adapter, campaign or live behavior. Therefore a
  new ADR/human approval is not required. Any proposal to synthesize a v3
  output, make the v2 proof authorize new risk/submission, infer absent fills,
  or reinterpret a historical hash would be class C and must stop for approval.

## RED-before tests required

Before production changes, add independent hostile tests proving:

1. a fully matched historical v2 PAPER order with exact fill and terminal
   ledger head cannot yet obtain an audit-only proof/release (RED), then does
   so exactly once and survives restart (GREEN);
2. normal v3 proof issuance rejects v2 lineage, and the legacy issuer rejects
   v3 qualifications—no cross-version fallback;
3. a fabricated v3 `decision_output_hash` on a v2 lineage, a substituted v2
   qualification row hash, candidate/approval/order mismatch, missing fill,
   or nonterminal head all fail closed without appending release;
4. duplicate proof/release replay is exactly once;
5. a later fill or incompatible correction invalidates the old release for
   capacity and restores UNKNOWN/full charge;
6. the retained test keeps its original new-action denials and final SETTLED
   assertion, changing only setup to add real fill/head evidence and invoke the
   audit-only proof path.

The repair remains synthetic/offline PAPER-only and grants no adapter,
strategy, shadow-research, protected-campaign or live-money GO.
