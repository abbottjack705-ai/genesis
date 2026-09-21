# R8 RED-before evidence

- Authority checkpoint: commit `b1f22e5` (clean R7 green checkpoint).
- Isolation: detached Git worktree at that exact commit.
- Command: `$env:PYTHONPATH = "src"; python remediation_evidence/R8/red_before_probe.py`.
- Result marker: `EXPECTED_F14_UNSAFE_BEHAVIOURS_REPRODUCED`.

Exact reproduced baseline outcomes:

```json
{
  "concurrent_exit_codes": [0, 0, 0, 0, 0, 0, 0, 0],
  "concurrent_usage": [8, 8],
  "evidence_free_cached_true_allowed": true,
  "monthly_used_after_191": 190,
  "normal_call_191_allowed": false
}
```

All eight workers constructed their old process-local views before a barrier released
them. Every worker passed the 7-unit daily ceiling and the authoritative log persisted
8 units. The old boolean cache API also granted a zero-cost hit without a cache artifact.
R0 independently preserved the original F14 `191 blocked at 190` exploit result against
the audited foundation baseline.
