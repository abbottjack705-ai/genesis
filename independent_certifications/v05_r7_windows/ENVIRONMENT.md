# Windows certification environment

- Host: Jack, Lenovo ThinkPad L380 (20M5S09D00), Microsoft Windows 10.0.26200.9457.
- Runner account: jack\abbot. The observed token has no SeCreateSymbolicLinkPrivilege; creating an NTFS file symlink returned WinError 1314. The account was not changed or elevated for W1.
- Runtime: CPython 3.12.10 at C:\Users\abbot\AppData\Local\Programs\Python\Python312\python.exe; 3.11 and 3.13 were not installed. The only deployed runtime assessed was this Windows image.
- Filesystem: NTFS temporary paths under LOCALAPPDATA\Temp; LongPathsEnabled=1. Git long-path worktree/checkout behavior is recorded under W8.
- Time: W32Time and Dnscache running. w32tm /query /status reported source time.windows.com,0x9, a recent successful sync, Leap Indicator 0. w32tm /query /source returned access denied; the status output itself supplies the source required by design section 6.1.
- Candidate: be898d3865685ac0261cdb255008db902b030521, detached LF checkout C:\Users\abbot\a8\v05_prep\genesis_r7_candidate_lf. Local clone core.autocrlf=false. Initial raw-byte check matched all 756 tracked Git blobs.
- Certification branch: cert/v05-r7-windows, worktree C:\Users\abbot\a8\v05_prep\genesis_r7_windows_worktree, based on independent audit commit 342d3e4a38634aad8abf7a93ff85f5ebf2012972.
- The original C:\Users\abbot\OneDrive\Desktop\GENESIS_F1_8ae25e7_REMEDIATED checkout was not modified. No real provider call, real credential, live betting, production execution, OS trust-store change or persistent machine configuration change was made. Loopback and synthetic fixtures were used; W15 also queried randomized .invalid names through the Windows resolver.
- Throwaway PKI key files and synthetic credentials were deleted by their probe cleanup. W13 records the ACL of a key before its removal.
- The first interactive W11 suite processes were interrupted before their summaries and remain as incomplete transcripts. Full detached reruns are the count evidence.

Raw host and privilege output: evidence/W00_environment.txt. Clock output: evidence/W05_w32tm.txt.
