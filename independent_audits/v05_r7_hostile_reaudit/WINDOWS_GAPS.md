# Windows certification gaps

## WINDOWS CERTIFICATION: OPEN

This independent audit ran on Windows NT 10.0.26200.0 with CPython 3.12.10. A passing Windows suite is evidence for this build, but the W1–W15 checklist remains open until its deployment-specific items are completed and reviewed against the final candidate.

| Item | This audit's observation | Remaining certification work |
| --- | --- | --- |
| W1 real NTFS symlink credential refusal | Suite's privileged real-link test skipped | Run under an identity with link privilege; confirm actual refusal |
| W2 junction paths | Not executed | Exercise repository, runtime-root and allowed external junctions |
| W3 credential ACLs | Simulated branches covered by suite | Real inherited/Users/Administrators ACLs under deployment identity |
| W4 killed-process run lock | Not executed | Force-kill lock holder and prove next process acquires lock |
| W5 time-sync attestation | Not executed against deployment clock service | Record acceptable `w32tm` source/status |
| W6 uncaught control-C exit status | Process-control tests passed | Prove actual `0xC000013A` launch exit |
| W7 coarse-clock soak | Fixed-clock and deadline tests passed | 1–16 ms deployment-clock soak |
| W8 MAX_PATH/long paths | No dedicated deployment-path run | Long runtime/evidence/credential path cases |
| W9 Windows production trust | 47/47 stock CAs, hostile env CA rejected, certificate/hostname required | Deployment-image trust-store and localized environment cases |
| W10 socket timing | Controlled deadline and loopback tests passed | Coarse-clock slow-drip, slow-head and handshake-stall overshoot measurement |
| W11 full suites and frozen compare | 917 adapter tests passed with two skips; 493 frozen passed with one skip; S0 counts identical | Resolve relevant skips and review complete W1–W15 package |
| W12 LF deployment checkout | Audit checkout uses `core.autocrlf=false` | Verify deployed checkout bytes and FRZ-09 |
| W13 throwaway PKI loopback | Loopback PKI and TLS tests passed | Owner-only key-file behavior under target NTFS ACL |
| W14 TLS concurrency | 80 concurrent hostile-environment contexts passed; R7 suite also covers races | Reconfirm on deployment image under its environment policy |
| W15 Windows resolver deadline | Controlled blocked-resolver deadline, no late socket and no shutdown hang reproduced | Windows DNS Client/LLMNR/NetBIOS stall and long-lived worker soak |

CPython 3.11 and 3.13 were unavailable on this host. This table records partial checks; none changes the overall certification status.
