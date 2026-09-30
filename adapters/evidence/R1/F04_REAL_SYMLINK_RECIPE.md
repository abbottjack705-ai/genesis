# F-04: real symbolic-link verification (external recipe)

## Status on the implementing host: NOT EXECUTED

`test_v05_credential.CredentialTests.test_f04_a_link_is_refused` still **skips** on the implementing host. It is
**not** reported as passing anywhere in this remediation. The reason is recorded in `SYMLINK_CHECK.txt`: the account
(`jack\abbot`, Windows 11 build 26200) does not hold `SeCreateSymbolicLinkPrivilege`, Developer Mode is off, and the
session is not elevated, so `os.symlink` fails with `[WinError 1314] A required privilege is not held by the client`.
Nothing on the host was changed to make the test runnable, and the credential loader was not weakened.

The fail-closed implementation is unchanged (`adapters/src/genesis_adapters/credential.py`):

1. `os.lstat` on the configured path; `S_ISLNK` or not `S_ISREG` → `CREDENTIAL_PERMISSIONS` (the branch this
   recipe exercises on a real symbolic link);
2. `Path.resolve()`, then refusal of any path inside the repository worktree or the runtime root;
3. owner-only ACL (Windows) / mode `0600` and owner (POSIX);
4. after `open`: the same `(st_dev, st_ino)` as checked, and `st_nlink == 1`.

What remediation R-4 now runs on every host without any privilege (`UnprivilegedLinkAttackTests`, ported from the
auditor's `probe_credential_links.py`): a junction resolving into the repository, a junction resolving into the
runtime root, a hard link whose second name is inside the repository (all refused, `CREDENTIAL_PERMISSIONS`), and
two controls that must load (a plain file, and a junction to an allowed folder). The simulated-`lstat` test also
remains. Only the genuine symbolic link needs the environment below.

## Environment that qualifies

Windows 10/11 with any one of:

- **Developer Mode on** (Settings → System → For developers → Developer Mode). A standard user can then create
  symbolic links; Python's `os.symlink` passes `SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE`.
- an **elevated** shell (Run as administrator), or
- an account granted **Create symbolic links** (`secpol.msc` → Local Policies → User Rights Assignment).

Plus Git and Python 3.12 (the version in every transcript). No credential, no network, no provider account is
needed: the test uses the fixed sentinel key in a temporary directory.

## Steps

```text
# 1. A fresh LF clone at the remediation commit (FRZ-09 fails closed on a CRLF checkout of src/)
git clone --no-hardlinks --no-checkout <path-or-URL of the repository> v05-symlink-check
cd v05-symlink-check
git config core.autocrlf false
git checkout --detach <REMEDIATION_COMMIT>            # the commit that adds this file

# 2. Prove the environment qualifies (must print: symlink OK True)
python -c "import os,tempfile,pathlib; d=pathlib.Path(tempfile.mkdtemp()); (d/'t').write_text('x'); os.symlink(d/'t', d/'l'); print('symlink OK', os.path.islink(d/'l'))"
#    [WinError 1314] here means the environment does not qualify: stop, and do not report a result.

# 3. Run the credential tests with isolated bytecode (the provenance guard requires it)
#    PowerShell:
$env:PYTHONPATH = "adapters"
$env:PYTHONPYCACHEPREFIX = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([guid]::NewGuid()))).FullName
python -B -m unittest -v adapter_tests.test_v05_credential 2>&1 | Tee-Object -FilePath F04_REAL_SYMLINK_TRANSCRIPT.txt
#    Git Bash:
PYTHONPATH=adapters PYTHONPYCACHEPREFIX="$(mktemp -d)" python -B -m unittest -v adapter_tests.test_v05_credential 2>&1 | tee F04_REAL_SYMLINK_TRANSCRIPT.txt

# 4. Record the evidence
git rev-parse HEAD
python --version
whoami /priv                                         # or a screenshot of Developer Mode = On
sha256sum F04_REAL_SYMLINK_TRANSCRIPT.txt
```

## Acceptance

- The transcript contains `test_f04_a_link_is_refused (adapter_tests.test_v05_credential.CredentialTests.test_f04_a_link_is_refused) ... ok`
  (not `skipped`).
- The module summary is `OK` with **no** `skipped=` count, and every `UnprivilegedLinkAttackTests` case is `ok`.
- Optional: the full adapter suite
  (`PYTHONPYCACHEPREFIX=<fresh> python -B -m unittest discover -s adapters/adapter_tests -t adapters -v`) reports
  `OK` with zero skips on such an account; on the implementing host its single skip is this test.

What the test proves: `os.symlink(target, link)` creates a **file** symbolic link to an owner-only, one-line key
file that itself lies outside the repository and the runtime root; the loader must still refuse it with
`CREDENTIAL_PERMISSIONS`, because `os.lstat` reports `S_IFLNK` (design 7.5: a regular file, not a link). Every link
the test creates lives in a temporary directory and is removed with it.
