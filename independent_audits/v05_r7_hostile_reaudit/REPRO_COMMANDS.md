# Reproduction commands (PowerShell, from audit worktree root)

The audited commit is `b2eabac1da9ed3989de966583a51d97b3834aa9c`; the audit branch was created directly from it. Set a fresh bytecode location for each Python run. No command contacts the provider or uses a real credential.

```powershell
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP ('genesis-audit-' + [guid]::NewGuid())
& .\independent_audits\v05_r7_hostile_reaudit\probes\integrity.ps1

py -3.12 -B -m unittest discover -s adapters/adapter_tests -t adapters -p 'test_v05_r7_*.py' -v
py -3.12 -B -m unittest discover -s adapters/adapter_tests -t adapters -v
py -3.12 -B -m unittest discover -s tests -t . -v

$env:PYTHONPATH = (Join-Path (Get-Location).Path 'adapters')
py -3.12 -B -m unittest adapter_tests.test_v05_r7_quota_divergence.TheHaltAndItsRecoveryTests.test_a_replay_and_a_rebuild_never_derive_the_divergent_response adapter_tests.test_v05_pipeline.RebuildTests.test_pit09_rebuilding_into_empty_stores_gives_identical_artifacts_and_record_ids -v
py -3.12 -B -m unittest adapter_tests.test_v05_zz_final_provenance -v
py -3.12 -B -m compileall -q src tests adapters/src adapters/adapter_tests

$env:PYTHONPATH = ((Join-Path (Get-Location).Path 'adapters\src') + [IO.Path]::PathSeparator + (Join-Path (Get-Location).Path 'src'))
py -3.12 -B -c "from pathlib import Path; from genesis_adapters.oddspapi.verify import compare_frozen_transcripts; a=Path('adapters/evidence/S0/FROZEN.txt').read_text(); b=Path('independent_audits/v05_r7_hostile_reaudit/evidence/frozen_v04.txt').read_text(); print(compare_frozen_transcripts(a,b) is not None)"
```

The final test in full adapter discovery is `test_no_test_contacted_a_non_loopback_address`; it must report `ok`.

```powershell
$P = 'independent_audits\v05_r7_hostile_reaudit\probes'
$env:CAND_DIR = (Get-Location).Path
$env:AUDIT_SCRATCH = Join-Path $env:TEMP ('genesis-audit-prior-' + [guid]::NewGuid())
$env:PYTHONIOENCODING = 'utf-8'
py -3.12 -B (Join-Path $P 'prior_a01_settle_gap.py')
py -3.12 -B (Join-Path $P 'prior_q01_quota_divergence_restart.py')
py -3.12 -B (Join-Path $P 'prior_p113_poison.py')
py -3.12 -B (Join-Path $P 'prior_p123_date_overflow.py')
py -3.12 -B (Join-Path $P 'combined_failure_crash.py')
py -3.12 -B (Join-Path $P 'tls_concurrency.py')
py -3.12 -B (Join-Path $P 'dns_exhaustion.py')
py -3.12 -B (Join-Path $P 'dns_shutdown.py')
```

The retired TLS test CA and leaf key are extracted from Git history **only into a new temporary scratch directory**, then removed. The old TLS probe needs the OpenSSL binary bundled with Git for its hashed CA directory.

```powershell
$env:GIT_DIR_FOR_HISTORY = (Get-Location).Path
$auditTlsScratch = Join-Path $env:TEMP ('genesis-r7-oldtls-' + [guid]::NewGuid())
$env:AUDIT_SCRATCH = $auditTlsScratch
$env:PATH = 'C:\Program Files\Git\usr\bin;' + $env:PATH
py -3.12 -B (Join-Path $P 'prior_t01_tls_trust.py') (Get-Location).Path 'C:\Users\abbot\AppData\Local\Programs\Python\Python312\python.exe' R7
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
$target = [IO.Path]::GetFullPath($auditTlsScratch)
if (-not $target.StartsWith($tempRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'scratch path outside TEMP' }
Remove-Item -LiteralPath $target -Recurse -Force
```

Mutations must run in a detached scratch checkout, never in the audited candidate or audit worktree. The R7 campaign writes `adapters/evidence/R7/MUTATION.txt` only in scratch; compare or copy its output into the independent audit directory.

```powershell
git worktree add --detach 'C:\Users\abbot\fz\r7-mutant' b2eabac1da9ed3989de966583a51d97b3834aa9c
Push-Location 'C:\Users\abbot\fz\r7-mutant'
py -3.12 -B adapters/evidence/R7/scripts/mutation_campaign.py
Pop-Location
py -3.12 -B (Join-Path $P 'independent_mutations.py') 'C:\Users\abbot\fz\r7-mutant'
git -C 'C:\Users\abbot\fz\r7-mutant' diff --quiet -- adapters/src adapters/adapter_tests
```

The `prior_*.py` reproducers and `boot.py` were carried from the R6 independent hostile audit at `2ef9fa0`; their stdout in this package is from the R7 run. The remaining probes and mutation campaign were authored for this audit.


Additional prior hostile reproductions:

```powershell
py -3.12 -B (Join-Path $P 'prior_p130_replay.py')
py -3.12 -B (Join-Path $P 'prior_p140_rejected_restart.py')
py -3.12 -B (Join-Path $P 'prior_p80_provenance_windows.py')
py -3.12 -B (Join-Path $P 'prior_p95_f44.py')
```

The Windows provenance variant changes only the prior script's Linux `mktemp -d` invocation to Python `tempfile.mkdtemp`; the original probe and its initial platform error are retained. Its same-length byte-swap case raises a syntax error before provenance verification, so it establishes fail-closed import behavior rather than a hash-specific result. Its `.pth` case is inconclusive because its referenced shadow directory is absent; the direct shadow case does exercise `COMPETING_GENESIS`.
