# R7 RED-before evidence

- Authority baseline: commit `8bb86f3`.
- Isolation: detached Git worktree at that exact commit.
- Test module copied without modification from the active R7 worktree:
  `tests.test_remediation_r7_settlement`.
- Command: `python -m unittest tests.test_remediation_r7_settlement -v`.
- Result: **RED** — 7 tests ran; 2 failed and 5 errored.

Observed unsafe baseline behavior included:

- both racing, unlinked settlements succeeded (`[0, 0]` instead of `[0, 2]`);
- cross-fill correction was not rejected;
- `FillRecord.fragment()` raised because it constructed `MatchedFragment` with the wrong shape;
- settlement events had no separate `delta_pnl` / `effective_pnl` fields;
- no current-head query existed; and
- cancellation had no correction-lineage input.

This is the expected pre-fix failure signature for T-F04-001..011 and
T-ADJ-LEDGER-001. The detached baseline was not modified or committed.
