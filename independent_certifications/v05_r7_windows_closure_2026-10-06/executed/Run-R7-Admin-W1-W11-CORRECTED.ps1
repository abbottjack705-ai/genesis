#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$candidate = 'C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf'
$support = 'C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED\R7_W13_LF'
$cert = 'C:\Users\abbot\a8\v05_prep\genesis_r7_windows_worktree\independent_certifications\v05_r7_windows'
$evidence = 'C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED\R7_W13_results\closure_2026-10-06'
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

function Invoke-NativeCaptured {
    param(
        [string]$Label,[string]$FilePath,[string[]]$ArgumentList,
        [string]$WorkingDirectory,[string]$StdoutPath,[string]$StderrPath
    )
    Remove-Item $StdoutPath,$StderrPath -Force -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
    if ($p.ExitCode -ne 0) { throw "$Label exited $($p.ExitCode). See evidence files." }
}
function Read-All([string]$Path) {
    if (Test-Path $Path) { return Get-Content $Path -Raw }
    return ''
}

$prodHead = (& git -C $candidate rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $prodHead -ne 'be898d3865685ac0261cdb255008db902b030521') {
    throw "Pinned production checkout has wrong HEAD: $prodHead"
}
$supportHead = (& git -C $support rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $supportHead -ne 'deec08ffc66c56d156bc09addf548c62166cea17') {
    throw "Certification-support checkout has wrong HEAD: $supportHead"
}
if (@(& git -C $candidate status --porcelain).Count -ne 0 -or @(& git -C $support status --porcelain).Count -ne 0) {
    throw 'A certification checkout is not clean'
}

# Record token state, but do not require the privilege string:
# Developer Mode can permit real symlink creation without it appearing in whoami /priv.
whoami /priv | Out-File (Join-Path $evidence 'W01_admin_token.txt') -Encoding utf8

# W5
$timeStatus = w32tm /query /status
if ($LASTEXITCODE -ne 0) { throw "Windows time status exited $LASTEXITCODE" }
if (($timeStatus -join "`n") -match 'Leap Indicator:\s*3') {
    $resync = w32tm /resync 2>&1
    $resync | Out-File (Join-Path $evidence 'W05_admin_resync.txt') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Windows time resync exited $LASTEXITCODE" }
    Start-Sleep 5
    $timeStatus = w32tm /query /status
    if ($LASTEXITCODE -ne 0) { throw "Windows time status after resync exited $LASTEXITCODE" }
}
$timeStatus | Out-File (Join-Path $evidence 'W05_admin_w32tm_status.txt') -Encoding utf8
$timeText = $timeStatus -join "`n"
if ($timeText -notmatch 'Leap Indicator:\s*0' -or $timeText -match 'Stratum:\s*0' -or
    $timeText -match 'Source:\s*(Local CMOS Clock|Free-running System Clock)') {
    throw 'W5 time-sync attestation is not healthy'
}

# W1 unchanged probe
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-w1-pycache'
$w1Out = Join-Path $evidence 'W01_admin_real_symlink_probe.stdout.txt'
$w1Err = Join-Path $evidence 'W01_admin_real_symlink_probe.stderr.txt'
Invoke-NativeCaptured 'Unchanged W1 certification probe' 'py.exe' `
    @('-3.12','-B',(Join-Path $cert 'probes\credential_ntfs.py'),$candidate) `
    $candidate $w1Out $w1Err
$w1 = (Read-All $w1Out) + "`n" + (Read-All $w1Err)
if ($w1 -notmatch 'W1_REAL_SYMLINK CREATED is_symlink True' -or
    $w1 -notmatch 'CASE real_symlink_refused .*ACTUAL CREDENTIAL_PERMISSIONS MATCH True') {
    throw 'W1 did not create and refuse a genuine NTFS symbolic link'
}

# W11 targeted adapter symlink test
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-adapter-target-pycache'
$aOut = Join-Path $evidence 'W11_adapter_symlink_target.stdout.txt'
$aErr = Join-Path $evidence 'W11_adapter_symlink_target.stderr.txt'
Invoke-NativeCaptured 'Adapter real-symlink test' 'py.exe' `
    @('-3.12','-B','-m','unittest','adapter_tests.test_v05_credential.CredentialTests.test_f04_a_link_is_refused','-v') `
    (Join-Path $support 'adapters') $aOut $aErr
$a = (Read-All $aOut) + "`n" + (Read-All $aErr)
if ($a -notmatch 'test_f04_a_link_is_refused.*ok' -or $a -match 'skipped') {
    throw 'Adapter real-symlink test did not execute cleanly'
}

# W11 targeted frozen symlink test
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-frozen-target-pycache'
$fOut = Join-Path $evidence 'W11_frozen_symlink_target.stdout.txt'
$fErr = Join-Path $evidence 'W11_frozen_symlink_target.stderr.txt'
Invoke-NativeCaptured 'Frozen real-symlink test' 'py.exe' `
    @('-3.12','-B','-m','unittest','tests.test_astra_t5_hostile_preaudit.T5HostileOwnerTests.test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not','-v') `
    $candidate $fOut $fErr
$f = (Read-All $fOut) + "`n" + (Read-All $fErr)
if ($f -notmatch 'test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not.*ok' -or $f -match 'skipped') {
    throw 'Frozen real-symlink test did not execute cleanly'
}

# Full adapter suite
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-adapter-full-pycache'
$aFullOut = Join-Path $evidence 'W11_adapter_full.stdout.txt'
$aFullErr = Join-Path $evidence 'W11_adapter_full.stderr.txt'
Invoke-NativeCaptured 'Complete adapter suite' 'py.exe' `
    @('-3.12','-B','-m','unittest','discover','-s','adapters/adapter_tests','-t','adapters','-v') `
    $support $aFullOut $aFullErr
$aFull = (Read-All $aFullOut) + "`n" + (Read-All $aFullErr)
if ($aFull -notmatch 'Ran 919 tests' -or $aFull -notmatch 'OK \(skipped=1\)' -or
    $aFull -notmatch 'test_f04_a_link_is_refused.*ok') {
    throw 'Complete adapter suite did not meet expected W11 count and symlink coverage'
}

# Full frozen suite
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-frozen-full-pycache'
$fFullOut = Join-Path $evidence 'W11_frozen_full.stdout.txt'
$fFullErr = Join-Path $evidence 'W11_frozen_full.stderr.txt'
Invoke-NativeCaptured 'Complete frozen V0.4 suite' 'py.exe' `
    @('-3.12','-B','-m','unittest','discover','-s','tests','-t','.','-v') `
    $candidate $fFullOut $fFullErr
$fFull = (Read-All $fFullOut) + "`n" + (Read-All $fFullErr)
if ($fFull -notmatch 'Ran 493 tests' -or $fFull -match 'OK \(skipped=' -or
    $fFull -notmatch 'test_h3_directory_alias_is_the_same_owner_and_file_symlink_is_not.*ok') {
    throw 'Complete frozen suite did not meet expected W11 count and symlink coverage'
}

# Final raw integrity
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'genesis-r7-final-admin-raw-pycache'
$rOut = Join-Path $evidence 'W00_admin_raw_checkout_final.stdout.txt'
$rErr = Join-Path $evidence 'W00_admin_raw_checkout_final.stderr.txt'
Invoke-NativeCaptured 'Final raw candidate integrity' 'py.exe' `
    @('-3.12','-B',(Join-Path $cert 'probes\raw_checkout.py'),$candidate) `
    $candidate $rOut $rErr

if (@(& git -C $candidate status --porcelain).Count -ne 0 -or @(& git -C $support status --porcelain).Count -ne 0) {
    throw 'A certification checkout changed during the suites'
}

$summary = Join-Path $evidence 'W01_W11_admin_summary.txt'
@(
'W1 PASS: genuine NTFS symlink created and credential refused'
'W5 PASS: synchronized Windows time source and healthy status'
'W11 PASS: adapter 919 tests with only the Windows-inapplicable POSIX skip; frozen 493 with no skips'
) | Out-File $summary -Encoding utf8

$manifest = Join-Path $evidence 'SHA256SUMS.txt'
Get-ChildItem $evidence -Recurse -File |
    Where-Object { $_.FullName -ne $manifest } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($evidence.Length + 1).Replace('\','/')
        "$(Get-FileHash $_.FullName -Algorithm SHA256 | Select-Object -ExpandProperty Hash)  $relative"
    } | Out-File $manifest -Encoding ascii

Write-Output 'W1 PASS; W5 PASS; W11 PASS. Evidence is in the closure_2026-10-06 directory.'
