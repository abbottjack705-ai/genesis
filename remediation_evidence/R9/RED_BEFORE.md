# R9 RED-before evidence

- Authority checkpoint: commit `d486297` (clean R8 green checkpoint).
- Isolation: detached Git worktree at that exact commit.
- Command: `$env:PYTHONPATH = "src"; python remediation_evidence/R9/red_before_probe.py`.
- Result marker: `EXPECTED_F13_UNSAFE_BEHAVIOURS_REPRODUCED`.

Exact reproduced baseline outcomes:

```json
{
  "callback_introspected_label": 1,
  "callback_pid": 20848,
  "concurrent_exit_codes": [0, 0],
  "directly_introspected_label": 1,
  "label_owner_pid": 20848,
  "persisted_attempt_rows": 2
}
```

The research-facing boundary directly exposed the name-mangled label tuple. Arbitrary
strategy code recovered the same label while executing in the exact label-owner process.
Both barrier-synchronised workers also reserved the single final attempt and persisted
two reservation rows. R0 independently retains the original F13 label-introspection
result against the audited foundation baseline.
