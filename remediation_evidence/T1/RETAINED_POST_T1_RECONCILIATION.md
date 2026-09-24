# Retained post-T1 fixture reconciliation

Date: 2026-09-24

Sealed source checkpoint: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`

Exact retained blobs before this fixture adaptation:

- `tests/test_v04_foundation.py`: Git blob `dc420b51d70ea8f6468d60d6ca4b659286831d2e`
- `tests/test_astra_s2_admission.py`: Git blob `e7a9a539b05b623aa2dc15f3d93b280f3e906a69`

The exact originals remain in Git and are recoverable with:

```
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_v04_foundation.py
git show 27dd525c1fd7d531c4833c4bf7e44204a9345f19:tests/test_astra_s2_admission.py
```

The complete adaptation diff, including every removed pre-change line, is
preserved in `retained_post_t1_fixture_adaptation.patch`. The exact initial
test transcript is preserved in `retained_post_t1_prechange_transcript.txt`.

## Contract-conflict check

No test changed in these two modules asserted that a bare terminal reservation
state should free capacity. No terminal-release setup or assertion was edited.
Accordingly, this reconciliation found no B3 terminal-release contract conflict
to rewrite or waive. The invalid assumptions here were instead unfenced
strategy booleans, qualifications without an exact decision-contract hash, and
restart/worker fixtures that reopened only part of the current durable
authority set.

## Per-test invariants and fixture-only adaptations

### `test_risk_counts_pending_and_unknown_and_approvals_are_single_use`

Original invariant: an upward rebase changes the current bankroll authority; a
valid approval is consumable exactly once; an UNKNOWN exposure blocks later new
risk; and the durable risk event count is exact.

Invalid setup: the hand-built qualifications carried no exact registered
strategy decision-contract hash, the engine had no current durable PAPER
strategy/mode owners, and the request's nonempty `cluster-1` comparison was not
present in the trusted decision output. A caller-supplied cluster cannot replace
the content-addressed output's dependence evidence.

Adaptation: use the synthetic nonoperational PAPER fixture, derive the first
qualification from a content-addressed output that itself contains
`cluster-1`, bind the second qualification to the same registered contract,
and use the fixture's exact authority owners. Every original assertion and the
nonempty caller comparison remain unchanged.

### `test_paper_order_idempotency_and_unknown_reconciliation`

Original invariant: an identical order intent is idempotent; material critical
evidence change fails recertification and requires a new candidate; a forbidden
transition appends nothing; and timeout reconciliation remains non-recertified.

Invalid setup: the local `Active.is_active() -> True` object was a bare caller
boolean, not a fenced current strategy head or exact contract proof. It caused
the new gate to fail before the test could reach its intended material-change
assertion. The adapter also lacked the durable PAPER mode owner and a synthetic
offline action clock.

Adaptation: use `RegistryStrategyExecutionView` over the fixture's durable
strategy registry, the fixture's coherent PAPER mode store, and the explicit
synthetic action clock. All assertions are byte-for-byte unchanged.

### `test_unknown_exposure_at_entry_and_competing_last_capacity_block`

Original invariant: an UNKNOWN exposure inserted at admission entry blocks the
approval, while independently a competing position plus the first valid
reservation consumes the last portfolio capacity and blocks the second
approval with `open_liability_limit`.

Invalid setup: the second synthetic qualification omitted the now-required
exact contract hash, so it could not be legal input to the capacity assertion.

Adaptation: bind only that qualification to
`other["contract"].contract_hash`. Assertions and exposure amounts are
unchanged.

### `test_preexisting_stake_survives_rebase_but_new_risk_uses_current_cap`

Original invariant: a previously approved stake retains its issued amount
after a downward bankroll rebase, while later new risk is evaluated against the
new current cap.

Invalid setup: the later qualification omitted the exact contract hash, and
the restart helper reopened bankroll, qualification, safety, and audit logs but
not the current strategy/mode owners needed to judge a new approval.

Adaptation: bind the later qualification to the fixture contract and reopen the
same durable strategy and mode logs in `_restarted`. Both original assertions
are unchanged.

### Transaction-entry denial tests using `_assert_no_approval`

Affected tests:

- `test_downward_rebase_at_transaction_entry_cannot_commit_old_7_5_stake`
- `test_kill_at_transaction_entry_cannot_commit_approval`
- `test_qualification_ambiguity_at_transaction_entry_cannot_commit`

Original invariants, respectively: a rebase at transaction entry prevents a
stale-bankroll approval; a kill switch at transaction entry prevents an
approval; and an ambiguous qualification at transaction entry prevents an
approval. In every case no approval event may be durable before or after a
restart.

Invalid shared setup: `_assert_no_approval` constructed a partial restarted
engine without reopening the durable strategy/mode owners. That partial
construction is no longer a valid restart fixture even when the immediate
assertion only reads the audit log.

Adaptation: `_restarted` now reopens `strategies.jsonl` and `mode.jsonl` and
uses the explicit synthetic action clock. No test body or assertion changed.

### `test_multiprocess_rebase_before_admission_resumes_blocks_stale_head`

Original invariant: a cross-process rebase committed while admission is paused
must be observed when admission resumes, preventing a stale approval and
leaving no durable approval event.

Invalid setup: the spawned isolated engine reopened neither the registered
strategy contract/current PAPER head nor the durable PAPER mode head. It was no
longer a valid admission participant.

Adaptation: the isolated worker imports and reopens both owners from the exact
checkout under test and uses the synthetic action clock. Assertions are
unchanged.

### `test_multiprocess_authority_writers_wait_for_locked_admission`

Original invariant: bankroll and safety writers cannot cross an admission
transaction that holds the authority fence; the approval commits first, each
writer then commits, both processes exit cleanly, and exactly one approval is
durable.

Invalid setup: the approval worker's engine omitted the now-required exact
strategy and mode owners, so it could not represent a legal positive admission
inside the lock test.

Adaptation: reopen the exact strategy registry and mode store in the worker;
the writer setup, barriers, timeouts, and every assertion remain unchanged.

### `test_uncertain_post_append_response_restarts_as_exactly_one_approval`

Original invariant: losing the response after the fsynced approval append
still leaves exactly one approval, and retry after restart returns
`duplicate_order_intent` without another append.

Invalid setup: the restart helper omitted the strategy registry/current exact
contract owner, so retry failed at `strategy_authority_unavailable` before it
could prove duplicate replay.

Adaptation: reopen the strategy and mode owners in `_restarted`. All assertions
remain unchanged.

### `test_coordinator_commit_failure_after_jsonl_fsync_replays_once`

Original invariant: a coordinator commit failure after the JSONL fsync does not
erase or duplicate the approval; restart sees one event and retry is the exact
duplicate.

Invalid setup and adaptation: identical to the uncertain-response restart
case. The restart now carries the complete durable authority set; all original
assertions remain unchanged.

## Verification

Pre-change command:

```
python -m unittest tests.test_v04_foundation tests.test_astra_s2_admission -v
```

Historical result: `Ran 23 tests in 3.954s`, `FAILED (failures=3, errors=6)`.
Three errors were missing `contract_hash`; two assertion failures were restart
strategy-authority failures; one assertion failure was the deliberately
unfenced boolean masking the intended material-change result; and three errors
were Windows sandbox denial of multiprocessing queues. The full transcript is
preserved separately.

Post-adaptation commands and final results:

```
python -m unittest tests.test_v04_foundation -v
# Ran 14 tests in 13.992s — OK

python -m unittest tests.test_astra_s2_admission -v
# Ran 9 tests in 43.476s — OK
```

The S2 command ran outside the restricted Windows process sandbox so its
`spawn`/`Queue` concurrency cases could execute. A preceding cold full-module
attempt had two 15-second barrier timeouts; the unchanged locked-worker test
then passed focused (`Ran 1 test in 24.160s`) and the immediate complete rerun
passed all 9 tests. No timeout or assertion was weakened to obtain green.
