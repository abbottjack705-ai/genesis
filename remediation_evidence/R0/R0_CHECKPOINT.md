# R0 — Baseline Freeze and RED-Before Evidence

Status: **CLOSED / GREEN CHECKPOINT**

## Frozen authority

- V2.1 outer ZIP: `GENESIS_V04_REMEDIATION_CODEX_PACK_V2_1.zip`
- Size: `704811` bytes
- SHA-256: `a3a8e191be2176551e6ae99367f601eddd08b93fd7434432c2e84ca4b4d448e0`
- Internal manifest: `156` entries checked, `0` failures
- Foundation snapshot ZIP SHA-256: `1015cf7507f5aebce87f812367df3c77eebe58da15a0fa478acfb8d168201585`
- Frozen `repository_snapshot` → working copy comparison: `122` files each, `0` missing/extra/hash differences before Git initialization

## Repository baseline

- Git baseline/tag: `ae9cfa11128a476b2ec7f598df3d68e30b91f156` / `v0.4-audited-v2.1-baseline`
- Baseline suite: `Ran 28 tests in 0.362s` — `OK`
- Baseline compile: `python -m compileall -q src tests` — success
- Baseline working tree after checks: clean

## Separate hostile probe

Command:

```text
python remediation_evidence\R0\red_before_probe.py
```

Result: `ALL_EXPECTED_UNSAFE_BEHAVIOURS_REPRODUCED`.

The probe reproduced F01–F15, including the F12 chain fork on stress attempt 1. Exact structured results are retained in `red_before_result.json`. The probe is outside `tests/`, so RED-before evidence does not make the primary suite red.

## Scope attestation

- Production source changed: none.
- Existing tests changed: none.
- Sport/source/network/cloud/dashboard/credential/live code added: none.
