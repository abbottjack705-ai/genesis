# Retained S1 reconciliation before fixture adaptation

Date: 2026-09-23

Sealed source checkpoint: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`

Exact retained blobs before any T1 adaptation:

- `tests/test_astra_s1_reservation.py`: Git blob `dfbe2585d822fb61f0235cb1a2c9fd3c7ac0dcf8`
- `tests/test_astra_s1_submission.py`: Git blob `430d742415b6dfda0412ba03d1d9d8e7ddb1d3c8`

The exact originals remain immutable in Git and are recoverable with:

```
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_astra_s1_reservation.py
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_astra_s1_submission.py
```

The first attempted adaptation is preserved verbatim in
`retained_s1_first_attempt.patch`. It was frozen and rejected before further
editing because it substituted historical proofless terminal rows rather than
supplying legal proof-bearing evidence.

## Per-test original invariants and fixture reconciliation

### `test_own_unknown_void_and_settled_block_both_submission_phases`

Original invariant: a consumed approval is not enough to authorize PENDING or
SENT; the exact current reservation must still be active, and an UNKNOWN,
VOID, or SETTLED reservation must deny recertification and append no new order
event.

Invalid old setup: `release_or_unknown()` called
`transition_reservation(... VOID|SETTLED)` with only a caller enum and
timestamp. B3 establishes that those two inputs are not terminal evidence.

Permitted fixture-only adaptation: retain the UNKNOWN setup unchanged; for
VOID and SETTLED, create the complete synthetic PAPER order/fill/ledger proof,
append the proof-bound release, and then run the original denial/no-append
assertions. Add a direct assertion that the exact approval is no longer valid.

### `test_reservation_transition_at_order_transaction_entry_blocks`

Original invariant: an UNKNOWN transition racing at order-transaction entry is
observed under the fence and prevents an append. It never relied on terminal
release and requires no B3 semantic adaptation.

### `test_restart_keeps_released_and_unknown_reservations_blocking`

Original invariant: restart cannot resurrect a reservation as authority for a
new submission; UNKNOWN and legitimate terminal release both continue to deny
PENDING and append no event.

Invalid old setup: VOID/SETTLED were manufactured by the bare terminal API.

Permitted fixture-only adaptation: persist a real proof-bound release, restart
all proof owners, attach the proof owner to restarted risk, and preserve the
original recertification/transition/no-append assertions.

### `test_valid_reservation_and_later_terminal_release_preserve_history`

Original invariant: one valid PAPER send is retained exactly once, and after
legal settlement release the risk reservation is no longer open.

Contract conflict explicitly identified: the old test did assert that a bare
`SETTLED` reservation transition frees capacity. That setup expectation is
incompatible with B3. It must not be inverted or weakened. Reconciliation is
to replace only the terminal-release setup with exact order, fill, settlement,
and proof-owner evidence, while keeping the empty-reservation and one-send
assertions unchanged.

### Submission tests adapted for B7 fencing

- `test_each_failed_owner_check_blocks_pending_and_sent`: original invariant
  is unchanged; a strategy withdrawal must deny both appends. The old fixture
  swapped in a caller-owned boolean view. The legitimate setup writes a real
  RETIRED current registry head.
- `test_cross_thread_authority_writer_waits_until_submission_is_durable`:
  original invariant is unchanged. Its wrapper must forward the new captured
  owner parameters so it still injects the writer inside the same fenced
  recertification.
- `test_process_death_inside_fenced_check_leaves_no_pending_event_or_lock`:
  original invariant is unchanged. The legacy unfenceable view is now rejected
  before its callback; the crash is therefore injected inside the genuine
  fenced recertification, preserving and strengthening the no-append check.

## Pre-reconciliation retained-suite transcript

Command:

```
python -m unittest tests.test_remediation_r5_risk tests.test_remediation_r6_execution tests.test_astra_s1_submission tests.test_astra_s1_reservation -q
```

Result before the legitimate proof-fixture adaptation:

```
Ran 30 tests in 31.802s

FAILED (errors=8)
```

All eight errors were the same intentional new contract boundary,
`genesis.registry.RegistryConflict: terminal reservation requires exact
release proof`: one retained R6 bare-VOID fixture, four phase/state subtests in
`test_own_unknown_void_and_settled_block_both_submission_phases`, two restart
subtests, and the old positive bare-SETTLED release fixture. There were no
assertion failures in this run. This is retained historical evidence, not a
green-gate exception.
