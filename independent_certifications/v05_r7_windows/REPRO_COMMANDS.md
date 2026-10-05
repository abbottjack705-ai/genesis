# Reproduction commands

Run from the certification worktree root on the Windows ThinkPad. The code/tests candidate is the separate detached LF checkout. Only synthetic credentials and loopback TLS are used; the W15 real DNS names end in reserved .invalid. Use a fresh temporary PYTHONPYCACHEPREFIX for test modules.

~~~powershell
$C = 'C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf'
$A = 'independent_certifications\v05_r7_windows'
$env:PYTHONDONTWRITEBYTECODE = '1'
git rev-parse be898d3865685ac0261cdb255008db902b030521
git rev-parse b2eabac1da9ed3989de966583a51d97b3834aa9c^
git rev-parse 342d3e4a38634aad8abf7a93ff85f5ebf2012972^
git diff --exit-code be898d3865685ac0261cdb255008db902b030521 342d3e4a38634aad8abf7a93ff85f5ebf2012972 -- src tests adapters/src adapters/adapter_tests
~~~

| Item | Exact principal reproduction command |
| --- | --- |
| W1 | py -3.12 -B $A\probes\credential_ntfs.py $C (real os.symlink; WinError 1314 is OPEN) |
| W2 | py -3.12 -B $A\probes\credential_ntfs.py $C (mklink /J for allowed, repository, runtime) |
| W3 | py -3.12 -B $A\probes\credential_ntfs.py $C (icacls inherited, owner, Users and Administrators) |
| W4 | py -3.12 -B $A\probes\killed_lock.py $C (taskkill /F /PID of synthetic holder) |
| W5 | w32tm /query /status; w32tm /query /source |
| W6 | py -3.12 -B $A\probes\console_ctrl_c.py $C |
| W7 | py -3.12 -B $A\probes\coarse_socket_soak.py $C |
| W8 | py -3.12 -B $A\probes\credential_ntfs.py $C; reg query HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled; see long Git commands below |
| W9 | py -3.12 -B $A\probes\trust_case_variants.py $C |
| W10 | py -3.12 -B $A\probes\coarse_socket_soak.py $C |
| W11 | Full suite commands below |
| W12 | py -3.12 -B $A\probes\raw_checkout.py $C; provenance commands below |
| W13 | py -3.12 -B $A\probes\pki_acl.py $C |
| W14 | py -3.12 -B independent_audits\v05_r7_hostile_reaudit\probes\tls_concurrency.py |
| W15 | py -3.12 -B $A\probes\single_label_dns.py $C; py -3.12 -B $A\probes\resolver_soak.py $C; py -3.12 -B independent_audits\v05_r7_hostile_reaudit\probes\dns_exhaustion.py; py -3.12 -B independent_audits\v05_r7_hostile_reaudit\probes\dns_shutdown.py |

W8 long Git checkout attempts (the source clone is local; no network/provider call):

~~~powershell
$base = 'C:\Users\abbot\a8\v05_prep'
$p = Join-Path (Join-Path (Join-Path $base ('r'*80)) ('s'*80)) ('t'*80)
git -c core.longpaths=true worktree add --detach (Join-Path $p 'candidate') be898d3865685ac0261cdb255008db902b030521
git -c core.longpaths=true clone --no-hardlinks --no-checkout C:\Users\abbot\a8\v05_prep\genesis_r7_windows_cert (Join-Path $p 'candidate-clone')
git -c core.longpaths=true -C (Join-Path $p 'candidate-clone') checkout --detach be898d3865685ac0261cdb255008db902b030521
~~~

W11 complete suites, run in the exact candidate checkout with isolated bytecode. The recorded detached runs used Python 3.12.10 with the same arguments and separate stdout/stderr files. Preserve the stderr summaries; an interrupted earlier run is not a pass.

~~~powershell
Push-Location $C
$env:PYTHONPYCACHEPREFIX = 'C:\Users\abbot\AppData\Local\Temp\genesis-r7-cert-pycache-adapter2'
py -3.12 -B -m unittest discover -s adapters/adapter_tests -t adapters -v
$env:PYTHONPYCACHEPREFIX = 'C:\Users\abbot\AppData\Local\Temp\genesis-r7-cert-pycache-frozen2'
py -3.12 -B -m unittest discover -s tests -t . -v
Pop-Location
~~~

W12 raw-byte check used every staged blob ID from the candidate checkout (756 files), with Git blob SHA-1 computed from raw filesystem bytes; output is in evidence/W12_raw_checkout.txt. FRZ-09 and the final network sentinel were rerun as:

~~~powershell
Push-Location $C
$env:PYTHONPYCACHEPREFIX = 'C:\Users\abbot\AppData\Local\Temp\genesis-r7-cert-prov-pyc'
$env:PYTHONPATH = (Join-Path $C 'adapters')
py -3.12 -B -m unittest adapter_tests.test_v05_zz_final_provenance -v
git status --short
Pop-Location
~~~

W13 and W9 need a fresh PYTHONPYCACHEPREFIX because importing adapter_tests enforces FRZ-09. The W13 probe prints only path, ACL, mode and verification facts; never the throwaway private key. W6 creates a hidden new Windows console, attaches its parent, sends the real CTRL_C_EVENT and checks 0xC000013A.

