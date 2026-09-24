# B3 release/concurrency targeted current result

Date: 2026-09-23

Command from `work/genesis-remediation`:

```powershell
python -m unittest tests.test_astra_t1_release_concurrency -v
```

Result: exit 0; **5 methods passed**. The concurrency method runs both
deterministic serial orders. In each, the second thread is observed entering
the contended risk transaction and cannot finish until the first operation
commits. Release-first admits the competing 7.5 approval only after the
release row, at exactly 60 total liability; approval-first denies at 67.5,
then release leaves 52.5. Neither outcome exceeds the 60 cap.

Artifact hashes:

- `tests/test_astra_t1_release_concurrency.py` SHA-256:
  `1546C8385CE9ACDE0D9EE5FB954BD380A002EDA4157BD681194ACC4E05F79486`
- `green_release_concurrency_current.txt` SHA-256:
  `2D1A11CD3A2306C9E6DCCB5852763974605C1FF90389EFA46E7828F30151B6EF`

The adjacent B3 targeted run also passed 28/28:

```powershell
python -m unittest tests.test_astra_t1_release tests.test_astra_t1_release_proof tests.test_astra_t1_release_integration tests.test_astra_t1_release_concurrency -v
```

This is targeted synthetic PAPER evidence only. It is not a full-suite,
restart/crash-gate, B3 closure, or GO claim.
