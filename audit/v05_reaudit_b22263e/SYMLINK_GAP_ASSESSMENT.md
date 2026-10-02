# SYMLINK_GAP_ASSESSMENT — the real-Windows-symlink credential test (HA-004 carried as RA-001)

**Classification under c8dfafd: CERTIFICATION GAP.** It blocks GREEN. It is **not** a non-blocking
external verification requirement. It can be closed **without a code change** by external runs (§4),
provided they pass.

**What is known.** The implementer reports that the adapter suite at b22263e has "1 real-symlink skip".
On the 37b86fb audit of cfcff3d, `os.symlink` failed with `winerror 1314` on this Windows account, and the
real-symlink check was recorded as **NOT RUN**. Nothing in this re-audit could change that:

- b22263e is unreachable (RA-000);
- this session runs on Linux, not the deployment platform.

A skip is not a PASS, and other link types passing does not stand in for it.

## 1. What the architecture requires

| Text | Requirement |
| --- | --- |
| §7.5 | The credential file lies outside the repository worktree and outside `GENESIS_ADAPTER_ROOT`. On Windows the ACL grants only the runner user. It holds one line. "**Anything else is refused.**" |
| §16.2 (G1 prerequisites) | "Stages 0–7 GREEN, **including a GREEN secret-handling suite**." |
| §19, every stage | "Adapter suite fully GREEN." |
| §3.1 / §16 | The credential loader is first exercised for real at G1 on the operator's Windows host. |

The implementer chose to meet "anything else is refused" by refusing symbolic links (an `lstat`
`S_ISLNK`-type check), plus hard-link-count, junction-into-runtime, ACL and one-line rules (37b86fb
deviations 16 and 19). The refusal is therefore the **mechanism that enforces §7.5 on the deployment
platform**. Without it, a link can do three things:

- point from an outside-looking path into the repository or runtime root;
- inherit the ACL check of a target the attacker does not control, while the link itself stays
  replaceable;
- be swapped between the check and the read.

## 2. Why the simulated `lstat` does not certify it

A unit test that patches `os.lstat` to return `S_IFLNK` proves only that the branch reacts when `lstat`
says "link". It cannot detect the defects that matter on a real filesystem:

1. **Resolve-before-lstat ordering.** If the loader calls `Path.resolve()` / `os.path.realpath()` (or opens
   the file) *before* `lstat`, the link is already followed. `lstat` then sees a regular file and a real
   symlink is **accepted**, while the simulated test still passes because it patches `lstat` on whatever
   path it receives.
2. **Windows reparse semantics.** Python reports `S_IFLNK` only for name-surrogate reparse points (file and
   directory symbolic links), not junctions (`os.path.isjunction`, 3.12+). Which tag the real `mklink` link
   carries, and which call the loader actually makes, is a fact of the OS, not of a mock.
3. **Check-to-read identity.** Deviation 19 says the bytes are read "from the very file that was checked".
   Only a real link, swapped between the check and the read, shows whether "the file" means a handle or a
   path.

These are certification questions about the deployment platform. A simulation answers none of them.

## 3. Assessment of the other link types (cfcff3d evidence; b22263e unverified)

| Case | cfcff3d (37b86fb a11, real NTFS) | b22263e |
| --- | --- | --- |
| Second hard-link name | refused | NOT VERIFIED |
| Junction in an ancestor resolving **into** the runtime root | refused | NOT VERIFIED |
| Junction in an ancestor resolving to an **outside** directory | not tested | NOT VERIFIED |
| Real file symbolic link | **NOT RUN** (`winerror 1314`) | **skips** (implementer's own report) |
| Directory symbolic link in an ancestor | not tested (needs the same privilege) | NOT VERIFIED |

They are **not** substitutes. A hard link and a junction are different reparse and identity mechanisms.
That they pass says nothing about the `S_ISLNK` branch or about resolve-before-lstat ordering.

**Windows path aliasing (RA-008, new).** The "outside the repository / runtime root" rule (§7.5) was never
attacked with path aliasing that does not involve a link at all:

- a UNC admin-share path to a file inside the worktree (`\\localhost\C$\…\fz\g\k.key`): `realpath` keeps
  it as UNC, so a string-prefix comparison against `C:\…` does not see that it is inside;
- an 8.3 short name;
- a case-varied spelling;
- a `\\?\` prefix;
- a `subst` drive letter;
- a volume mount point.

A loader that compares `realpath` strings can be bypassed by some of these. A loader that compares file
identity (`st_dev`, `st_ino`) of the repository and runtime roots against every ancestor of the opened file
is robust. These cases need no symlink privilege and belong in the same run.

## 4. What closes it (no code change presumed)

1. **Windows, privileged** (Developer Mode or an elevated shell, on the deployment host): run
   `python -B attacks/a11_windows_credential.py --repo <b22263e clone>` (37b86fb package; `run_all.sh`
   step 6). "a real file symbolic link → refused" must PASS.
   - In the same session, run the candidate's own skipped test so that it **executes** (a skip under the
     privilege is a FAIL of the run).
   - Add a directory-symlink-in-ancestor case and a swap-between-check-and-read case.
2. **Linux** (no privilege needed; e.g. this cloud environment once b22263e is pushed): run the candidate's
   real-symlink test and a11's symlink case with real POSIX links. This does not replace step 1. It does
   catch the platform-independent ordering defect (§2.1) cheaply.
3. **Path-aliasing family** (RA-008) on Windows: UNC admin share, 8.3, case, `\\?\`, `subst`, mount point,
   and an ancestor junction pointing outside. Each must be refused when it reaches the repository or
   runtime root, and must load only when the real file is genuinely outside both with an owner-only ACL.
4. Commit the outputs under `adapters/evidence/` with SHA-256s, and record them in the certification
   record.

## 5. Why not "non-blocking external verification"

The case for calling it non-blocking would be: the code path is simple, the other link types pass, and the
credential does not exist until G1.

c8dfafd closes that door. G1 is the very gate whose prerequisite is "a GREEN secret-handling suite"
(§16.2), and V0.5 certification exists to satisfy that prerequisite. A credential boundary that has never
run on the platform where the credential will live is not GREEN. The cost of closing it is one privileged
run, and it must happen before the first credential is stored. Treating it as optional would certify by
simulation exactly the branch the architecture's precedence rule (D15) protects.
