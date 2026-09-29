# Run the whole independent oracle against a candidate checkout (Windows).
#   powershell -ExecutionPolicy Bypass -File run_oracle.ps1 -Repo C:\Users\abbot\fz\g -Commit cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 -Out C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_run
param([Parameter(Mandatory)][string]$Repo, [Parameter(Mandatory)][string]$Commit, [string]$Out = "oracle_out")
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Stages = "63e06a1,1bc6001,78bedb9,b95465e,9de0790,ff7f4ba,9c35c5c,cfcff3d"
function Run($name, $args) { Write-Host "=== $name"; & python @args 2>&1 | Tee-Object -FilePath "$Out\$name.txt"; "exit=$LASTEXITCODE" | Tee-Object -Append -FilePath "$Out\$name.txt" }
Run 01_frozen_identity  @("$Here\oracle_frozen_identity.py","--repo",$Repo,"--commit",$Commit,"--stages",$Stages,"--json","$Out\01_frozen_identity.json")
Run 02_provenance_crlf  @("$Here\oracle_provenance_crlf.py","--repo",$Repo,"--json","$Out\02_provenance_crlf.json")
Run 04_pit_head_expected @("$Here\oracle_pit_head_expected.py","--repo",$Repo,"--out","$Out\EXPECTED_PIT_HEADS.json")
Run 09_quota_semantics  @("$Here\oracle_quota_semantics.py","--repo",$Repo)
Run 07_boundary_edges   @("$Here\oracle_boundary_guard_edges.py","--out","$Out\EXPECTED_BOUNDARY_EDGES.json")
Run 06_secret_corpus    @("$Here\oracle_secret_corpus.py","--repo",$Repo,"--out","$Out\SECRET_CORPUS.json")
Run 12_tls_key          @("$Here\oracle_tls_key_check.py","--repo",$Repo,"--commit",$Commit)
Run 13_static_scan      @("$Here\oracle_static_scan.py","--repo",$Repo,"--json","$Out\13_static_scan.json")
Push-Location $Repo
Write-Host "=== frozen suite"; python -m unittest discover -s tests -t . 2>&1 | Select-Object -Last 3 | Tee-Object -FilePath "$Out\frozen_suite_tail.txt"
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP ("pyc-" + [guid]::NewGuid())
Write-Host "=== adapter suite"; python -B -m unittest discover -s adapters/adapter_tests -t adapters 2>&1 | Select-Object -Last 3 | Tee-Object -FilePath "$Out\adapter_suite_tail.txt"
git status --porcelain -- src tests config tools DECISIONS v04_pack | Out-File "$Out\frz03_porcelain.txt"
git ls-files --eol -- src tests config tools DECISIONS v04_pack | Select-String "w/crlf|w/mixed" | Out-File "$Out\frozen_worktree_crlf.txt"
Write-Host "Windows worktree CRLF lines in frozen trees: $((Get-Content "$Out\frozen_worktree_crlf.txt" | Measure-Object -Line).Lines)"
Pop-Location
Get-ChildItem $Out -File | Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  $($_.Path | Split-Path -Leaf)" } | Out-File "$Out\ORACLE_OUT_MANIFEST.sha256"
