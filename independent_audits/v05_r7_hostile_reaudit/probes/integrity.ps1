$ErrorActionPreference='Stop'
$candidate='C:\Users\abbot\fz\g'
$audit=(Resolve-Path '.').Path
$pin='b2eabac1da9ed3989de966583a51d97b3834aa9c'
$code='be898d3865685ac0261cdb255008db902b030521'
$ref=git -C $candidate rev-parse refs/heads/ccr-f8478091-s6i6d1
if ($ref -ne $pin) { throw "branch pin mismatch $ref" }
$head=git -C $candidate rev-parse HEAD
if ($head -ne $pin) { throw "candidate HEAD mismatch $head" }
$status=git -C $candidate status --porcelain=v1
if ($status) { throw "candidate worktree dirty: $status" }
$parents=(git -C $candidate rev-list --parents -n 1 $pin).Split(' ')
if ($parents.Count -ne 2 -or $parents[1] -ne $code) { throw "code parent mismatch" }
git -C $candidate merge-base --is-ancestor $code $pin
if ($LASTEXITCODE -ne 0) { throw 'ancestry check failed' }
$changed=@(git -C $candidate diff --name-only $code $pin)
if ($changed.Count -eq 0 -or @($changed | Where-Object { -not $_.StartsWith('adapters/evidence/R7/') }).Count) { throw "non-evidence change: $changed" }
$trees=@('src','tests','config','tools','DECISIONS','v04_pack')
foreach($tree in $trees) {
    $at=git -C $candidate rev-parse "$($pin):$tree"
    $frozen=git -C $candidate rev-parse "v0.4-foundation-freeze:$tree"
    if ($at -ne $frozen) { throw "frozen tree mismatch: $tree" }
}
$manifest=Join-Path $candidate 'adapters/evidence/R7/HASHES.sha256'
$base=Split-Path $manifest -Parent
$covered=@()
foreach($line in Get-Content -LiteralPath $manifest) {
    if ($line -notmatch '^([0-9a-f]{64}) \*(.+)$') { throw "malformed manifest: $line" }
    $expected=$Matches[1]; $relative=$Matches[2]
    $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $base $relative)).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "hash mismatch: $relative" }
    $covered += $relative.Replace('\','/')
}
$actualFiles=@(Get-ChildItem -LiteralPath $base -Recurse -File | ForEach-Object { $_.FullName.Substring($base.Length+1).Replace('\','/') } | Where-Object { $_ -ne 'HASHES.sha256' })
$missing=@($actualFiles | Where-Object { $_ -notin $covered })
$extra=@($covered | Where-Object { $_ -notin $actualFiles })
if ($missing.Count -or $extra.Count) { throw "manifest coverage mismatch missing=$missing extra=$extra" }
git -C $candidate diff --quiet v0.4-foundation-freeze $pin -- src tests config tools DECISIONS v04_pack
if ($LASTEXITCODE -ne 0) { throw 'frozen diff nonempty' }
git -C $audit diff --quiet HEAD -- adapters/src adapters/adapter_tests
if ($LASTEXITCODE -ne 0) { throw 'audit worktree modified production/tests' }
"branch_pin=$ref"
"candidate_head=$head clean=True"
"code_parent=$($parents[1]) ancestry=True"
"evidence_only_files=$($changed.Count)"
"frozen_trees=6/6 match freeze"
"R7_manifest_entries=$($covered.Count) coverage_complete=True hashes_match=True"
"audit_production_tests_unchanged=True"
