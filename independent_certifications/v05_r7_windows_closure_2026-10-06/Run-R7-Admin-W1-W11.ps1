#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$candidate = 'C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf'
$support = 'C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED\R7_W13_LF'
$cert = 'C:\Users\abbot\a8\v05_prep\genesis_r7_windows_worktree\independent_certifications\v05_r7_windows'
$evidence = 'C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED\R7_W13_results\closure_2026-10-06'
$env:PYTHONDONTWRITEBYTECODE = '1'

function Assert-Exit([string]$label) {
    if ($LASTEXITCODE -ne 0) { throw "$label exited $LASTEXITCODE" }
}

if ((& git -C $candidate rev-parse HEAD).Trim() -ne 'be898d3865685ac0261cdb255008db902b030521') {
    throw 'Pinned production checkout has the wrong HEAD'
}
if ((& git -C $support rev-parse HEAD).Trim() -ne 'deec08ffc66c56d156bc09addf548c62166cea17') {
    throw 'Certification-support checkout has the wrong HEAD'
}
if (@(& git -C $candidate status --porcelain).Count -ne 0 -or
    @(& git -C $support status --porcelain).Count -ne 0) {
    throw 'A certification checkout is not clean'
}

$rights = whoami /priv
$rights | Out-File -LiteralPath (Join-Path $evidence 'W01_admin_token.txt') -Encoding utf8

$timeStatus = w32tm /query /status
Assert-Exit 'Windows time status'
if (($timeStatus -join "`n") -match 'Leap Indicator:\s*3') {
    $resyncLog = Join-Path $evidence 'W05_admin_resync.txt'
    w32tm /resync *> $resyncLog
    Assert-Exit 'Windows time resync'
    Start-Sleep -Seconds 5
    $timeStatus = w32tm /query /status
    Assert-Exit 'Windows time status after resync'
}
$timeStatus | Out-File -LiteralPath (Join-Path $evidence 'W05_admin_w32tm_status.txt') -Encoding utf8
$timeText = $timeStatus -join "`n"
if ($timeText -notmatch 'Leap Indicator:\s*0' -or
    $timeText -match 'Stratum:\s*0' -or
    $timeText -match 'Source:\s*(Local CMOS Clock|Free-running System Clock)') {
    throw 'W5 time-sync attestation is not healthy; no final Windows PASS is certified'
}

if (($rights -join "`n") -notmatch 'SeCreateSymbolicLinkPrivilege') {
    throw 'This elevated token still lacks SeCreateSymbolicLinkPrivilege. No symlink result is certified.'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-w1-pycache'
$w1Log = Join-Path $evidence 'W01_admin_real_symlink_probe.txt'
& py -3.12 -B (Join-Path $cert 'probes\credential_ntfs.py') $candidate *> $w1Log
Assert-Exit 'Unchanged W1 certification probe'
$w1 = Get-Content -LiteralPath (Join-Path $evidence 'W01_admin_real_symlink_probe.txt') -Raw
if ($w1 -notmatch 'W1_REAL_SYMLINK CREATED is_symlink True' -or
    $w1 -notmatch 'CASE real_symlink_refused .*ACTUAL CREDENTIAL_PERMISSIONS MATCH True') {
    throw 'W1 did not create and refuse a genuine NTFS symbolic link'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-adapter-target-pycache'
$adapterTargetOut = Join-Path $evidence 'W11_adapter_symlink_target.stdout.txt'
$adapterTargetErr = Join-Path $evidence 'W11_adapter_symlink_target.stderr.txt'
try {
    Push-Location (Join-Path $support 'adapters')
    & py -3.12 -B -m unittest `
        adapter_tests.test_v05_credential.CredentialTests.test_f04_a_link_is_refused -v 1> $adapterTargetOut 2> $adapterTargetErr
    Assert-Exit 'Adapter real-symlink test'
} finally { Pop-Location }
$adapterTarget = Get-Content -LiteralPath (Join-Path $evidence 'W11_adapter_symlink_target.stderr.txt') -Raw
if ($adapterTarget -notmatch 'test_f04_a_link_is_refused.*ok' -or $adapterTarget -match 'skipped') {
    throw 'Adapter real-symlink test did not execute cleanly'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-frozen-target-pycache'
$frozenTargetOut = Join-Path $evidence 'W11_frozen_symlink_target.stdout.txt'
$frozenTargetErr = Join-Path $evidence 'W11_frozen_symlink_target.stderr.txt'
try {
    Push-Location $candidate
    & py -3.12 -B -m unittest `
        tests.test_astra_t5_hostile_preaudit.T5HostileOwnerTests.test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not -v 1> $frozenTargetOut 2> $frozenTargetErr
    Assert-Exit 'Frozen real-symlink test'
} finally { Pop-Location }
$frozenTarget = Get-Content -LiteralPath (Join-Path $evidence 'W11_frozen_symlink_target.stderr.txt') -Raw
if ($frozenTarget -notmatch 'test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not.*ok' -or
    $frozenTarget -match 'skipped') {
    throw 'Frozen real-symlink test did not execute cleanly'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-adapter-full-pycache'
$adapterFullOut = Join-Path $evidence 'W11_adapter_full.stdout.txt'
$adapterFullErr = Join-Path $evidence 'W11_adapter_full.stderr.txt'
try {
    Push-Location $support
    & py -3.12 -B -m unittest discover -s adapters/adapter_tests -t adapters -v 1> $adapterFullOut 2> $adapterFullErr
    Assert-Exit 'Complete adapter suite'
} finally { Pop-Location }
$adapterFull = Get-Content -LiteralPath (Join-Path $evidence 'W11_adapter_full.stderr.txt') -Raw
if ($adapterFull -notmatch 'Ran 919 tests' -or $adapterFull -notmatch 'OK \(skipped=1\)' -or
    $adapterFull -notmatch 'test_f04_a_link_is_refused.*ok') {
    throw 'Complete adapter suite did not meet the expected W11 count and symlink coverage'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-frozen-full-pycache'
$frozenFullOut = Join-Path $evidence 'W11_frozen_full.stdout.txt'
$frozenFullErr = Join-Path $evidence 'W11_frozen_full.stderr.txt'
try {
    Push-Location $candidate
    & py -3.12 -B -m unittest discover -s tests -t . -v 1> $frozenFullOut 2> $frozenFullErr
    Assert-Exit 'Complete frozen V0.4 suite'
} finally { Pop-Location }
$frozenFull = Get-Content -LiteralPath (Join-Path $evidence 'W11_frozen_full.stderr.txt') -Raw
if ($frozenFull -notmatch 'Ran 493 tests' -or $frozenFull -match 'OK \(skipped=' -or
    $frozenFull -notmatch 'test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not.*ok') {
    throw 'Complete frozen suite did not meet the expected W11 count and symlink coverage'
}

$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-raw-pycache'
$rawLog = Join-Path $evidence 'W00_admin_raw_checkout_final.txt'
& py -3.12 -B (Join-Path $cert 'probes\raw_checkout.py') $candidate *> $rawLog
Assert-Exit 'Final raw candidate integrity'
if (@(& git -C $candidate status --porcelain).Count -ne 0 -or
    @(& git -C $support status --porcelain).Count -ne 0) {
    throw 'A certification checkout changed during the suites'
}

'W1 PASS: genuine NTFS symlink created and credential refused' |
    Out-File -LiteralPath (Join-Path $evidence 'W01_W11_admin_summary.txt') -Encoding utf8
'W5 PASS: synchronized Windows time source and healthy status' |
    Out-File -LiteralPath (Join-Path $evidence 'W01_W11_admin_summary.txt') -Encoding utf8 -Append
'W11 PASS: adapter 919 tests with only the Windows-inapplicable POSIX skip; frozen 493 with no skips' |
    Out-File -LiteralPath (Join-Path $evidence 'W01_W11_admin_summary.txt') -Encoding utf8 -Append
$manifest = Join-Path $evidence 'SHA256SUMS.txt'
Get-ChildItem -LiteralPath $evidence -Recurse -File |
    Where-Object { $_.FullName -ne $manifest } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($evidence.Length + 1).Replace('\', '/')
        "$(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 | Select-Object -ExpandProperty Hash)  $relative"
    } | Out-File -LiteralPath $manifest -Encoding ascii
Write-Output 'W1 PASS; W11 PASS. Evidence is in the closure_2026-10-06 directory.'
