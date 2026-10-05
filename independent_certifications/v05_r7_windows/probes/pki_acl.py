"""Inspect the actual NTFS ACL of a throwaway test PKI key; never print key bytes."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters"), str(candidate / "adapters" / "src"), str(candidate / "src")]
from adapter_tests import tls_support
from genesis_adapters.credential import _windows_principals, _windows_user

pki = tls_support.new_pki("localhost")
try:
    print("TEMP_KEY_PATH", pki.key_file)
    print("KEY_FILE_EXISTS", pki.key_file.is_file())
    print("MODE", oct(pki.key_file.stat().st_mode & 0o777))
    acl = subprocess.run(["icacls", str(pki.key_file)], capture_output=True, text=True)
    print("ICACLS_EXIT", acl.returncode)
    print(acl.stdout)
    print(acl.stderr)
    principals = _windows_principals(pki.key_file)
    print("OWNER_ONLY_ACL", principals == {_windows_user()})
    print("PRINCIPALS", sorted(principals))
    print("SERVER_CONTEXT_LOADED", pki.server_context().verify_mode.name)
finally:
    shutil.rmtree(pki.directory)
    print("TEMP_KEY_REMOVED", not pki.key_file.exists())
