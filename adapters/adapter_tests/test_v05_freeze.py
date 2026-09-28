"""FRZ-01..04 and FRZ-09: freeze guard and runtime module-provenance guard."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from genesis_adapters import provenance_guard as guard
from genesis_adapters.oddspapi import verify

from .support import (
    CONFIG, REPO, child_env, git, git_bytes, run_child, scratch_root, shared_clone,
    synthetic_commit,
)

MANIFEST = CONFIG / "frozen_genesis_modules.json"
FROZEN_SRC_TREE = "51cb635bc42b993815b6c02a23c4c3ceb7d98476"
EXPECTED = {
    "src": "51cb635bc42b993815b6c02a23c4c3ceb7d98476",
    "tests": "e90b298180068fec03ba7e2fa81957082e7fb3ce",
    "config": "abd22db01ff482a8da84634ee740ba382b68c804",
    "tools": "a0e3411edb4e068fd4708050516cb6870834e7ac",
    "DECISIONS": "cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64",
    "v04_pack": "3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12",
}


class FreezeGuardTests(unittest.TestCase):
    def test_frz01_six_tree_shas_equal_the_freeze_record(self):
        self.assertEqual(dict(verify.FROZEN_TREE_SHAS), EXPECTED)
        for tree, sha in EXPECTED.items():
            self.assertEqual(git(REPO, "rev-parse", f"HEAD:{tree}"), sha, tree)
        verify.verify_frozen_trees(REPO, "HEAD")

    def test_frz02_guard_fails_on_added_file_and_on_edited_config(self):
        with scratch_root() as root:
            clone = shared_clone(root / "clone")
            added = synthetic_commit(clone, {"src/genesis/x.py": b"X = 1\n"})
            with self.assertRaises(verify.FreezeViolation) as caught:
                verify.verify_frozen_trees(clone, added)
            self.assertIn("src", str(caught.exception))
            original = git_bytes(clone, "show", "HEAD:config/oddspapi_quota_policy_v2.json")
            edited = synthetic_commit(
                clone, {"config/oddspapi_quota_policy_v2.json": original + b"\n"})
            with self.assertRaises(verify.FreezeViolation) as caught:
                verify.verify_frozen_trees(clone, edited)
            self.assertIn("config", str(caught.exception))
            deleted = synthetic_commit(clone, {"tools/genesis_audit_package.py": None})
            with self.assertRaises(verify.FreezeViolation):
                verify.verify_frozen_trees(clone, deleted)
            # an adapters/ addition alone is fine
            fine = synthetic_commit(clone, {"adapters/new_file.txt": b"ok\n"})
            verify.verify_frozen_trees(clone, fine)

    def test_frz03_worktree_clean_over_the_frozen_trees(self):
        verify.verify_frozen_worktree_clean(REPO)

    def test_frz03_dirty_frozen_worktree_is_detected(self):
        with scratch_root() as root:
            clone = shared_clone(root / "clone")
            git(clone, "checkout", "--quiet", "HEAD", "--", *verify.FROZEN_TREE_SHAS)
            verify.verify_frozen_worktree_clean(clone)
            (clone / "config" / "defaults.json").write_bytes(b"{}\n")
            with self.assertRaises(verify.FreezeViolation):
                verify.verify_frozen_worktree_clean(clone)

    def test_frz04_transcript_comparison(self):
        base = "Ran 493 tests in 671.000s\n\nOK (skipped=1)\n"
        same = "noise\nRan 493 tests in 12.5s\n\nOK (skipped=1)\n"
        self.assertEqual(verify.parse_unittest_summary(base),
                         {"ran": 493, "failures": 0, "errors": 0, "skipped": 1, "ok": True})
        verify.compare_frozen_transcripts(base, same)
        for bad in ("Ran 492 tests in 1s\n\nOK (skipped=1)\n",
                    "Ran 493 tests in 1s\n\nOK (skipped=2)\n",
                    "Ran 493 tests in 1s\n\nFAILED (failures=1, skipped=1)\n",
                    "no summary at all\n"):
            with self.assertRaises(verify.FreezeViolation):
                verify.compare_frozen_transcripts(base, bad)


def _guard_child(repo: Path, *, manifest: Path = MANIFEST, prepend: list[str] = (),
                 append: list[str] = (), site_dirs: list[Path] | None = None,
                 imports: str = "import genesis, genesis.quota, genesis.evidence, genesis.pit",
                 pre: str = "", check_git: bool = True) -> str:
    site = "None" if site_dirs is None else repr([str(p) for p in site_dirs])
    lines = [
        "import sys",
        f"sys.path[:0] = {list(map(str, prepend))!r}",
        f"sys.path[:0] = [{str(repo / 'adapters' / 'src')!r}, {str(repo / 'src')!r}]",
        f"sys.path.extend({list(map(str, append))!r})",
        "from pathlib import Path",
        "from genesis_adapters import provenance_guard as g",
        "from genesis_adapters.oddspapi import verify as v",
        pre,
        imports,
        "try:",
        "    g.verify_loaded_genesis_modules(",
        f"        Path({str(repo)!r}), manifest_path=Path({str(manifest)!r}),",
        "        expected_manifest_sha256=v.FROZEN_MANIFEST_SHA256,",
        f"        site_dirs={site}, check_git={check_git!r})",
        "    print('OK')",
        "except g.ModuleProvenanceError as exc:",
        "    print('FAIL:' + exc.code)",
    ]
    return chr(10).join(lines) + chr(10)


def _outcome(result) -> str:
    return result.stdout.decode().strip().splitlines()[-1] if result.stdout.strip() else \
        "NOOUT:" + result.stderr.decode(errors="replace")[-300:]


class ModuleProvenanceTests(unittest.TestCase):
    def test_frz09_manifest_equals_git_ls_tree_of_the_frozen_src_tree(self):
        raw = MANIFEST.read_bytes()
        self.assertEqual(guard.sha256_hex(raw), verify.FROZEN_MANIFEST_SHA256)
        data = json.loads(raw)
        self.assertEqual(data["src_tree"], FROZEN_SRC_TREE)
        listing = git(REPO, "ls-tree", "-r", FROZEN_SRC_TREE).splitlines()
        blobs = {}
        for line in listing:
            meta, path = line.split("\t", 1)
            blobs[path] = meta.split()[2]
        py = {path: sha for path, sha in blobs.items() if path.endswith(".py")}
        self.assertEqual({k: v["blob_sha1"] for k, v in data["entries"].items()}, py)
        self.assertEqual(guard.generate_manifest(REPO, FROZEN_SRC_TREE), raw)
        self.assertTrue(all(k.startswith("genesis/") for k in data["entries"]))

    def test_frz09_clean_isolated_run_passes_and_records_the_verdict(self):
        result = run_child(_guard_child(REPO))
        self.assertEqual(_outcome(result), "OK", result.stderr.decode(errors="replace"))
        from . import GUARD_VERDICT
        for key in ("modules", "adapter_modules", "sys_path", "flags", "site_dirs",
                    "manifest_sha256", "python", "repo", "genesis_origin", "verdict"):
            self.assertIn(key, GUARD_VERDICT)
        self.assertEqual(GUARD_VERDICT["verdict"], "PASS")
        self.assertEqual(GUARD_VERDICT["manifest_sha256"], verify.FROZEN_MANIFEST_SHA256)
        self.assertTrue(GUARD_VERDICT["flags"]["dont_write_bytecode"])
        self.assertTrue(GUARD_VERDICT["flags"]["pycache_prefix"])
        for module in GUARD_VERDICT["modules"]:
            self.assertEqual(set(module), {"name", "path", "blob_sha1", "sha256"})

    def test_frz09_shadow_package_through_pythonpath_fails(self):
        with scratch_root() as root:
            (root / "shadow" / "genesis").mkdir(parents=True)
            (root / "shadow" / "genesis" / "__init__.py").write_text("SHADOW = True\n")
            script = textwrap.dedent(f"""
                import sys
                from pathlib import Path
                sys.path.extend([{str(REPO / 'adapters' / 'src')!r}, {str(REPO / 'src')!r}])
                from genesis_adapters import provenance_guard as g
                from genesis_adapters.oddspapi import verify as v
                import genesis
                try:
                    g.verify_loaded_genesis_modules(
                        Path({str(REPO)!r}), manifest_path=Path({str(MANIFEST)!r}),
                        expected_manifest_sha256=v.FROZEN_MANIFEST_SHA256, site_dirs=None)
                    print("OK")
                except g.ModuleProvenanceError as exc:
                    print("FAIL:" + exc.code)
            """)
            result = run_child(script, env=child_env({"PYTHONPATH": str(root / "shadow")}))
            self.assertEqual(_outcome(result), "FAIL:GENESIS_ORIGIN")

    def test_frz09_pth_file_referencing_a_genesis_package_fails(self):
        with scratch_root() as root:
            (root / "evil" / "genesis").mkdir(parents=True)
            (root / "evil" / "genesis" / "__init__.py").write_text("")
            (root / "site").mkdir()
            (root / "site" / "evil.pth").write_text(f"{root / 'evil'}\n")
            result = run_child(_guard_child(REPO, site_dirs=[root / "site"]))
            self.assertEqual(_outcome(result), "FAIL:PTH_REFERENCE")

    def test_frz09_pth_pointing_at_the_repo_root_or_import_line_fails(self):
        with scratch_root() as root:
            (root / "site").mkdir()
            (root / "site" / "repo.pth").write_text(f"{REPO}\n")
            self.assertEqual(_outcome(run_child(_guard_child(REPO, site_dirs=[root / "site"]))),
                             "FAIL:PTH_REFERENCE")
            (root / "site" / "repo.pth").write_text("import genesis\n")
            self.assertEqual(_outcome(run_child(_guard_child(REPO, site_dirs=[root / "site"]))),
                             "FAIL:PTH_REFERENCE")

    def test_frz09_pth_pointing_exactly_at_the_listed_src_is_allowed(self):
        with scratch_root() as root:
            (root / "site").mkdir()
            (root / "site" / "ok.pth").write_text(f"{REPO / 'src'}\n")
            self.assertEqual(_outcome(run_child(_guard_child(REPO, site_dirs=[root / "site"]))), "OK")
            (root / "site" / "ok.pth").write_text("# comment\n\n")
            self.assertEqual(_outcome(run_child(_guard_child(REPO, site_dirs=[root / "site"]))), "OK")

    def test_frz09_competing_genesis_on_a_lower_precedence_path_fails(self):
        with scratch_root() as root:
            (root / "comp" / "genesis").mkdir(parents=True)
            (root / "comp" / "genesis" / "__init__.py").write_text("")
            result = run_child(_guard_child(REPO, append=[str(root / "comp")]))
            self.assertEqual(_outcome(result), "FAIL:COMPETING_GENESIS")
            (root / "comp2").mkdir()
            (root / "comp2" / "genesis.py").write_text("")
            result = run_child(_guard_child(REPO, append=[str(root / "comp2")]))
            self.assertEqual(_outcome(result), "FAIL:COMPETING_GENESIS")

    def test_frz09_competing_genesis_adapters_fails(self):
        with scratch_root() as root:
            (root / "comp" / "genesis_adapters").mkdir(parents=True)
            (root / "comp" / "genesis_adapters" / "__init__.py").write_text("")
            result = run_child(_guard_child(REPO, append=[str(root / "comp")]))
            self.assertEqual(_outcome(result), "FAIL:COMPETING_ADAPTERS")

    def _copy_repo(self, root: Path) -> Path:
        import shutil
        copy = root / "repo"
        shutil.copytree(REPO / "src" / "genesis", copy / "src" / "genesis",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "adapters" / "src", copy / "adapters" / "src",
                        ignore=shutil.ignore_patterns("__pycache__"))
        return copy

    def test_frz09_a_modified_frozen_module_fails(self):
        with scratch_root() as root:
            copy = self._copy_repo(root)
            target = copy / "src" / "genesis" / "time.py"
            target.write_bytes(target.read_bytes() + b"\n# tampered\n")
            result = run_child(_guard_child(copy, check_git=False,
                                            imports="import genesis, genesis.time"))
            self.assertEqual(_outcome(result), "FAIL:MODULE_HASH_MISMATCH")

    def test_frz09_an_unlisted_module_file_fails(self):
        with scratch_root() as root:
            copy = self._copy_repo(root)
            (copy / "src" / "genesis" / "extra_module.py").write_text("X = 1\n")
            result = run_child(_guard_child(copy, check_git=False,
                                            imports="import genesis, genesis.extra_module"))
            self.assertEqual(_outcome(result), "FAIL:MODULE_NOT_IN_MANIFEST")

    def test_frz09_stale_pyc_is_defeated_by_isolated_bytecode_and_refused_without_it(self):
        import py_compile
        with scratch_root() as root:
            copy = self._copy_repo(root)
            target = copy / "src" / "genesis" / "reasons.py"
            evil = root / "evil_reasons.py"
            evil.write_bytes(target.read_bytes() + b"\nPLANTED_PYC = True\n")
            cache = target.parent / "__pycache__" / f"{target.stem}.{sys.implementation.cache_tag}.pyc"
            cache.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(evil), cfile=str(cache), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            probe = "import genesis, genesis.reasons\nprint('PLANTED' if hasattr(genesis.reasons, 'PLANTED_PYC') else 'CLEAN')\n"
            # 1. without -B and without a pycache prefix the stale pyc really is loaded ...
            unisolated = run_child(_guard_child(copy, check_git=False,
                                                imports="import genesis, genesis.reasons") ,
                                   isolated_bytecode=False)
            self.assertEqual(_outcome(unisolated), "FAIL:BYTECODE_NOT_ISOLATED")
            loaded = run_child("import sys" + chr(10) + f"sys.path[:0] = [{str(copy / 'src')!r}]"
                               + chr(10) + probe, isolated_bytecode=False)
            self.assertEqual(_outcome(loaded), "PLANTED")   # the attack is real
            # 2. ... with -B and a fresh pycache prefix it is never consulted, and the guard passes.
            isolated = run_child(_guard_child(copy, check_git=False,
                                              imports="import genesis, genesis.reasons\n"
                                                      "print('PLANTED' if hasattr(genesis.reasons,"
                                                      " 'PLANTED_PYC') else 'CLEAN')"))
            self.assertEqual(isolated.stdout.decode().split(), ["CLEAN", "OK"])

    def test_frz09_prefix_directory_must_be_fresh(self):
        with scratch_root() as root:
            prefix = root / "prefix"
            (prefix / "x").mkdir(parents=True)
            (prefix / "x" / "stale.cpython-312.pyc").write_bytes(b"\0")
            script = _guard_child(REPO)
            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                env=child_env(pycache=prefix), cwd=str(REPO), capture_output=True)
            self.assertEqual(_outcome(result), "FAIL:BYTECODE_NOT_ISOLATED")

    def test_frz09_non_source_file_loader_fails(self):
        pre = textwrap.dedent(f"""
            import importlib.machinery, importlib.util, sys
            class Sneaky(importlib.machinery.SourceFileLoader):
                pass
            class Finder:
                @classmethod
                def find_spec(cls, name, path=None, target=None):
                    if name != "genesis":
                        return None
                    origin = {str(REPO / 'src' / 'genesis' / '__init__.py')!r}
                    return importlib.util.spec_from_file_location(
                        "genesis", origin, loader=Sneaky("genesis", origin),
                        submodule_search_locations=[{str(REPO / 'src' / 'genesis')!r}])
            sys.meta_path.insert(0, Finder)
        """)
        result = run_child(_guard_child(REPO, pre=pre))
        self.assertEqual(_outcome(result), "FAIL:LOADER_TYPE")

    def test_frz09_manifest_pin_and_shape_are_enforced(self):
        with scratch_root() as root:
            other = root / "manifest.json"
            other.write_bytes(MANIFEST.read_bytes() + b" ")
            result = run_child(_guard_child(REPO, manifest=other))
            self.assertEqual(_outcome(result), "FAIL:MANIFEST_PIN")


if __name__ == "__main__":
    unittest.main()
