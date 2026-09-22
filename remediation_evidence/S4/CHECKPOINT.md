# S4 / Astra A6 evidence checkpoint

Date: 2026-09-22 UTC.

Audited sealed base: `166f9230a0fb773cad2ac3619b5f98989d78a818`.
Immediately preceding S3b green base:
`42f75403945ababb096ff250bc15389c2529d989`.

## RED before implementation

`tests/test_astra_s4_cache.py` SHA-256:
`caad51fcb4f75fa988e792b8cbb65a514690a8e697155614c69eede51877e305`.

The worktree test source was loaded against production modules from each clean
baseline. The logs print the exact base SHA and resolved `genesis` source.
All 11 methods were RED with 15 invariant assertion failures on each baseline;
there were no import, collection or setup errors.

- `RED_166F923.txt` SHA-256:
  `5d11d76c206e084a80b31d49b7893f1763801f3769711eac6f94f94fe9f6d50f`
- `RED_S3B_HEAD.txt` SHA-256:
  `48c6fdb80cd606d22c5b8bcd3f182a2792b69de0e0f61bb683aaae75515c6949`

The command form for each clean worktree was:

```text
python -c "import sys,unittest,subprocess; from pathlib import Path; import tests; base=Path(r'<resolved-clean-worktree>'); sys.path.insert(0,str(base/'src')); import genesis; print('BASE_SHA',subprocess.check_output(['git','-C',str(base),'rev-parse','HEAD'],text=True).strip(),flush=True); print('GENESIS_SOURCE',genesis.__file__,flush=True); suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_astra_s4_cache'); result=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(not result.wasSuccessful())"
```

## GREEN after implementation

```text
python -m unittest tests.test_astra_s4_cache tests.test_remediation_r8_quota tests.test_v04_foundation -v
39 tests passed in 11.630s

python -m unittest discover -s tests -t . -v
184 tests passed in 137.897s

python -m compileall -q src tests
PASS
```

- `GREEN_TARGETED.txt` SHA-256:
  `8fd463281598673eb87ff78a42be49958c9b8f12cf490e6c9878be849e402832`
- `GREEN_FULL.txt` SHA-256:
  `fec3504548edff7641923a2f9eca394b3d694d1b9fbad788ca77700c08025f8d`
- `GREEN_COMPILEALL.txt` SHA-256:
  `affdf327a8de6ebed6d9639733b04bcd0f8841c5c662a31c6c92193e7464b368`

## Closed invariant and retained authority

A cache hit now requires a reference resolved by `VerifiedCacheStore`. The
entry identity binds actual immutable object bytes and length, exact provider
request, provider, active quota-policy digest, capture and expiry. Append-only
invalidation history is evaluated at the quota decision time. The cache log is
locked through the fsynced quota decision, and the complete cache proof is in
the idempotency fingerprint and persisted event replay.

Nonexistent/missing/tampered objects, caller `verified=True`, provider, policy
or request mismatch, expiry, invalidation and incompatible cache history do not
produce a cache hit. A genuine current entry remains zero billable.

Interpretation A, the seven daily billable limit, 220 normal monthly plus 30
protected reserve, explicit reserve authority and one legitimate allowance are
unchanged. This is local A6 closure. A8 and the overall independent-audit HOLD
remain open; no adapter, research or live GO is granted.
