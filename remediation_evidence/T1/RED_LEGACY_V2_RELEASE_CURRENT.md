# Legacy-v2 audit-only release RED-before evidence

Date: 2026-09-24

- Base commit: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`.
- This run used the preserved uncommitted T1 B1/B2/B3/B7 green work but was
  performed before any legacy-v2 production repair.
- Test source: `tests/test_astra_t1_legacy_release.py`.
- Test SHA-256:
  `A9241C3998C13DBA19317BD3B7F03D8AF6D0E06996AEBF3B16D2CB58157A9E6A`.

Command:

```powershell
python -m unittest tests.test_astra_t1_legacy_release -v
```

Exact test/result summary:

```text
test_late_fill_invalidates_legacy_release_and_restores_full_charge ... FAIL
test_missing_fill_or_terminal_head_never_creates_legacy_release ... FAIL
test_v2_and_v3_proof_paths_never_cross_or_fabricate_lineage ... FAIL
test_valid_legacy_full_settlement_releases_once_and_restarts ... FAIL

----------------------------------------------------------------------
Ran 4 tests in 5.213s

FAILED (failures=4)
```

Every failure is the same deliberate invariant assertion:

```text
AssertionError: B3 requires a separate audit-only legacy-v2 settlement proof operation
```

There were zero import, collection, fixture, or setup errors. The fixtures had
already constructed exact v2 qualification/approval/consumption/order/fill and
terminal-ledger evidence before reaching the missing operation. These tests do
not permit a legacy identity to authorize any new action and grant no GO.
