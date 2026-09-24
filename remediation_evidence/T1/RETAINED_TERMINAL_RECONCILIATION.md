# Retained terminal-transition reconciliation before fixture adaptation

Date: 2026-09-24

Sealed source checkpoint: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`

Exact retained test blobs before any adaptation in this reconciliation:

- `tests/test_astra_s2_replay.py`: Git blob `e0bbb839998b659fee07f690146b94c9ce4d6fb3`
- `tests/test_astra_s3_v3_adversarial.py`: Git blob `7c9cdadb9d1dbc541032c088afcb9b8b7851f100`

The exact originals remain immutable in Git and are recoverable with:

```
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_astra_s2_replay.py
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_astra_s3_v3_adversarial.py
```

A retained-test scan excluding `tests/test_astra_t1*.py` found exactly these
two additional calls to `transition_reservation(..., SETTLED|VOID)` outside
the S1/R6 fixtures already covered by `RETAINED_S1_RECONCILIATION.md`.

## `test_consumption_after_expiry_or_release_is_not_valid_history`

Original invariant: a risk approval consumption appended after the approval's
authority has ended is invalid active history. Both expiry and prior release
must make risk replay fail closed on the existing process and on restart.

Why the old fixture is invalid under B3: the `released` subtest manufactured
VOID with only a caller-selected terminal enum and timestamp. That call did
not establish that the approval was unconsumed, had no order intent, and had
no unexplained fill. Those are the exact facts required before capacity can be
released.

Conflict classification: this test does **not** assert that a bare terminal
state should free capacity. The terminal call is setup; every retained
assertion concerns rejection of the later, invalid consumption.

Smallest legitimate adaptation: create an empty real PAPER execution owner
and empty settlement ledger, issue an exact `UNCONSUMED_APPROVAL_NO_ORDER`
proof for the approval, attach the proof owner, and call `release_with_proof`.
Then append the same deliberately late consumption and preserve both original
`RegistryConflict` assertions unchanged.

The module-local `restarted()` fixture also has to reopen the new durable
strategy and mode authorities and retain the deterministic offline clock.
Its original invariant is that a restart observes the same authority/history,
including duplicate-intent and corrupt-replay outcomes. Reopening only the old
bankroll/qualification/safety/risk owners relied on the now-invalid assumption
that no separate current strategy or PAPER-mode head participated in risk
admission. This setup-only change preserves every restart assertion unchanged.

## `test_legacy_order_is_audit_replay_only_but_can_finish_settlement`

Original invariant: a pre-activation legacy order must remain audit-replay
only for new intent/consumption APIs, while its already-recorded matched order
can still advance to order `SETTLED` and its associated risk reservation can
advance to risk `SETTLED`.

Why the old fixture is invalid under B3: after manually replaying a legacy
qualification, consumed approval, and fully matched order, it calls
`transition_reservation(..., SETTLED)` with only a terminal enum and timestamp.
It records no fill, no settlement head, and no exact release proof. Moreover,
the deliberately legacy qualification has no v3 decision-output lineage, so
the current `OfflinePaperReleaseProofStore` cannot issue a legal proof for it.

Conflict classification: **genuine contract conflict requiring owner
reconciliation**. The final equality assertion directly requires this bare
legacy risk terminal transition to succeed. Replacing it with an expected
failure, retaining the reservation charge, deleting it, or changing the
legacy qualification into v3 would weaken, invert, delete, or change the
test's original invariant. No fixture-only proof adaptation preserves all of
the assertions under the current B3 contract.

Frozen S3b authority already resolves the intended contract direction:
`PROJECT_STATE.md` states that legacy v1/v2 history remains readable and
terminal settlement remains legal, while legacy identity cannot authorize new
actions. Therefore conservatively retaining the charge forever would conflict
with that authority rather than reconcile it.

The narrow compatible design is a separate audit-only legacy release proof
schema/path. The retained fixture must add a real fill and terminal settlement
head. The proof must bind the immutable legacy qualification row hash (never a
fabricated v3 `decision_output_hash`), exact risk approval and consumption,
PAPER order head, complete fill set, and every current terminal ledger head
under the same release/admission fence. It must expose no qualification,
approval, intent, pending, or send authority; a late fill or incompatible
correction must restore UNKNOWN/full charge. Once that production authority
exists, the fixture may replace only its bare release setup with that proof and
retain the final `ExposureState.SETTLED` assertion exactly.

Disposition: do not edit this retained test until that scoped authority exists.
The current v1 proof schema cannot express legacy lineage truthfully, and
overloading its `decision_output_hash` field would manufacture authority. This
conflict keeps the retained S3 module and full-suite gate red; it must not be
reported as a green exception or silently rewritten.

## 2026-09-24 resolution

`LEGACY_V2_RELEASE_DECISION_MEMO.md` reconciled the conflict as an additive,
already-authorized ADR-0002 implementation repair. Production now has a
separate `offline-paper-legacy-release-proof-v1` and
`risk-reservation-legacy-release-v1`; neither contains or invents a v3 output
identity. The retained test's new-action denials are unchanged. Only its bare
terminal setup was replaced with an exact fill, terminal settlement head and
audit-only proof; its final SETTLED assertion remains and was strengthened with
exact v2 row-hash/no-v3-output assertions. The preserved diff is
`retained_s3_legacy_fixture_adaptation.patch`.

Focused retained plus hostile legacy result: 5/5 passed in 15.037 seconds.
The final T1 gate, retained gate and full suite are recorded in
`GREEN_FINAL.md`.

## Pre-adaptation evidence

The exact targeted red transcript is preserved in
`retained_terminal_prechange_transcript.txt`. The eventual S2-only fixture
diff is preserved separately in `retained_terminal_fixture_adaptation.patch`.

The adapted S2 module transcript is preserved in
`retained_terminal_postchange_transcript.txt`.
