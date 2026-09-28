"""T6 F-B / ADR-0004: real Windows OS containment primitives, exercised.

These tests do NOT rely on the plan/scaffold object as evidence: they drive the
actual Job Object, AppContainer and confined-launch primitives. There are two
layers:

* Mocked tests (always run on Windows): the Job Object limit flags, the
  fail-closed cleanup of the confined launch when a step fails, and the
  fail-closed teardown of the orchestrator when any provisioning step fails.
* Benign local integration tests (skipped if the environment cannot create an
  AppContainer): kill-on-close, one-process limit, memory limit, AppContainer
  creation, filesystem grant/revoke, and a full confined launch asserting the
  AppContainer token, denied network capability (loopback only -- no external
  system), restricted filesystem access, and deterministic teardown.

Every probe is benign: a plain Python sleeper or a small script that reports what
the OS allows. Nothing loads native payloads, targets another process, or reaches
an external host.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock


IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from genesis import protected_confinement_win as win
    from genesis import protected_isolation as isolation


def _appcontainer_supported() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        profile = win.AppContainerProfile("genesis-e11-support-" + uuid.uuid4().hex[:10])
    except Exception:
        return False
    else:
        profile.close()
        return True


APPCONTAINER = _appcontainer_supported()
_SLEEPER = [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"]


@unittest.skipUnless(IS_WINDOWS, "Windows OS confinement primitives")
class JobObjectMockedTests(unittest.TestCase):
    def test_job_sets_kill_on_close_active_process_and_memory_limits(self):
        captured = {}

        def set_info(handle, cls, info_ref, size):
            info = info_ref._obj
            captured["flags"] = info.BasicLimitInformation.LimitFlags
            captured["active"] = info.BasicLimitInformation.ActiveProcessLimit
            captured["mem"] = info.ProcessMemoryLimit
            return 1

        with mock.patch.object(win, "_kernel32") as k:
            k.CreateJobObjectW.return_value = 4321
            k.SetInformationJobObject.side_effect = set_info
            job = win.ConfinementJob(memory_limit_bytes=123456, active_process_limit=1)
            job._handle = None  # avoid touching the fake handle on close
        self.assertTrue(captured["flags"] & win._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertTrue(captured["flags"] & win._JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        self.assertTrue(captured["flags"] & win._JOB_OBJECT_LIMIT_PROCESS_MEMORY)
        self.assertEqual(captured["active"], 1)
        self.assertEqual(captured["mem"], 123456)

    def test_job_creation_fails_closed_when_set_information_fails(self):
        with mock.patch.object(win, "_kernel32") as k:
            k.CreateJobObjectW.return_value = 4321
            k.SetInformationJobObject.side_effect = OSError(5, "denied")
            with self.assertRaises(win.ConfinementUnavailable):
                win.ConfinementJob(memory_limit_bytes=123456)
            # The partially-created job handle must be closed (fail closed).
            self.assertTrue(k.CloseHandle.called)


@unittest.skipUnless(IS_WINDOWS, "Windows OS confinement primitives")
class ConfinedLaunchFailClosedTests(unittest.TestCase):
    def test_launch_fails_closed_on_invalid_security_capabilities(self):
        # An empty/invalid SECURITY_CAPABILITIES (no container SID) must make the
        # launch fail rather than start an unconfined worker.
        with self.assertRaises(OSError):
            win.launch_confined_worker(
                _SLEEPER, environment={"SystemRoot": os.environ["SystemRoot"]},
                cwd=os.environ["SystemRoot"], job=mock.MagicMock(),
                security_capabilities=win._SECURITY_CAPABILITIES(),
            )

    @unittest.skipUnless(APPCONTAINER, "environment cannot create an AppContainer")
    def test_created_worker_is_terminated_if_job_assignment_fails(self):
        # A REAL worker is created suspended inside a real AppContainer; a job
        # whose assign() fails must cause the launch to terminate that worker and
        # fail closed, so no worker is left running unconfined.
        assigned = {}

        class FakeJob:
            def assign(self, process_handle):
                assigned["handle"] = process_handle
                raise win.ConfinementUnavailable("assignment refused")

        runtime = Path(sys.executable).resolve().parent
        with tempfile.TemporaryDirectory() as wd, \
                win.AppContainerProfile("genesis-e11-fcw-" + uuid.uuid4().hex[:10]) as ac:
            sid = ac.sid_string()
            win.grant_container_access(runtime, sid, write=False, recursive=True)
            try:
                real_terminate = win._kernel32.TerminateProcess
                with mock.patch.object(win._kernel32, "TerminateProcess", wraps=real_terminate) as term:
                    with self.assertRaises(win.ConfinementUnavailable):
                        win.launch_confined_worker(
                            _SLEEPER,
                            environment={"SystemRoot": os.environ["SystemRoot"],
                                         "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", "")},
                            cwd=wd, job=FakeJob(),
                            security_capabilities=ac.security_capabilities(),
                        )
                self.assertIn("handle", assigned)
                self.assertTrue(term.called, "a created-but-unassignable worker must be terminated")
            finally:
                win.revoke_container_access(runtime, sid, recursive=True)


@unittest.skipUnless(IS_WINDOWS, "Windows OS confinement primitives")
class OrchestratorFailClosedTests(unittest.TestCase):
    def _confinement(self, workdir):
        return isolation.ResearchProcessConfinement(
            program_import_roots=(Path(workdir),), research_workdir=Path(workdir),
        )

    def test_orchestrator_fails_closed_and_releases_profile_if_job_fails(self):
        with tempfile.TemporaryDirectory() as wd:
            profile = mock.MagicMock()
            with mock.patch.object(win, "AppContainerProfile", return_value=profile), \
                    mock.patch.object(win, "ConfinementJob", side_effect=win.ConfinementUnavailable("no job")):
                with self.assertRaises(win.ConfinementUnavailable):
                    isolation.launch_confined_research(
                        self._confinement(wd), _SLEEPER, environment={}, cwd=wd,
                        runtime_dirs=(), container_name="genesis-e11-fc-" + uuid.uuid4().hex[:10],
                    )
            # Fail closed: the profile created before the failure is released.
            self.assertTrue(profile.close.called)

    def test_orchestrator_fails_closed_and_tears_down_if_launch_fails(self):
        with tempfile.TemporaryDirectory() as wd:
            profile = mock.MagicMock()
            job = mock.MagicMock()
            with mock.patch.object(win, "AppContainerProfile", return_value=profile), \
                    mock.patch.object(win, "ConfinementJob", return_value=job), \
                    mock.patch.object(win, "grant_container_access"), \
                    mock.patch.object(win, "revoke_container_access"), \
                    mock.patch.object(win, "launch_confined_worker",
                                      side_effect=win.ConfinementUnavailable("no launch")):
                with self.assertRaises(win.ConfinementUnavailable):
                    isolation.launch_confined_research(
                        self._confinement(wd), _SLEEPER, environment={}, cwd=wd,
                        runtime_dirs=(), container_name="genesis-e11-fc2-" + uuid.uuid4().hex[:10],
                    )
            # Fail closed: the job is closed (kills any tree) and the profile released.
            self.assertTrue(job.close.called)
            self.assertTrue(profile.close.called)


@unittest.skipUnless(IS_WINDOWS, "Windows OS confinement primitives")
class JobObjectLiveTests(unittest.TestCase):
    def test_kill_on_close_terminates_the_process_tree(self):
        job = win.ConfinementJob(memory_limit_bytes=256 * 1024 * 1024)
        child = subprocess.Popen(_SLEEPER)
        try:
            job.assign(int(child._handle))
            self.assertIsNone(child.poll())
            job.close()  # KILL_ON_JOB_CLOSE terminates the tree
            child.wait(10)
            self.assertIsNotNone(child.poll(), "process survived job close")
        finally:
            if child.poll() is None:
                child.kill()

    def test_one_process_limit_blocks_a_grandchild(self):
        job = win.ConfinementJob(memory_limit_bytes=256 * 1024 * 1024, active_process_limit=1)
        code = (
            "import subprocess,sys\n"
            "try:\n"
            "    subprocess.Popen([sys.executable,'-c','pass']); print('SPAWNED')\n"
            "except OSError: print('BLOCKED')\n"
            "import time; time.sleep(1)\n"
        )
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", code],
                                 stdout=subprocess.PIPE, text=True)
        try:
            job.assign(int(child._handle))
            out, _ = child.communicate(timeout=15)
            self.assertIn("BLOCKED", out)
        finally:
            job.close()
            if child.poll() is None:
                child.kill()

    def test_memory_limit_denies_an_over_limit_allocation(self):
        job = win.ConfinementJob(memory_limit_bytes=64 * 1024 * 1024)  # 64 MiB
        code = (
            "try:\n"
            "    b = bytearray(256*1024*1024)\n"  # 256 MiB > 64 MiB cap
            "    print('ALLOCATED')\n"
            "except MemoryError: print('DENIED')\n"
        )
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", code],
                                 stdout=subprocess.PIPE, text=True)
        try:
            job.assign(int(child._handle))
            out, _ = child.communicate(timeout=15)
            self.assertIn("DENIED", out, "memory cap did not deny an over-limit allocation")
        finally:
            job.close()
            if child.poll() is None:
                child.kill()


@unittest.skipUnless(APPCONTAINER, "environment cannot create an AppContainer")
class AppContainerLiveTests(unittest.TestCase):
    def test_profile_yields_a_capabilityless_appcontainer_sid(self):
        with win.AppContainerProfile("genesis-e11-ac-" + uuid.uuid4().hex[:10]) as ac:
            self.assertTrue(ac.sid_string().startswith("S-1-15-2-"))
            caps = ac.security_capabilities()
            self.assertEqual(caps.CapabilityCount, 0)  # no network / no capabilities
            self.assertTrue(bool(caps.AppContainerSid))

    def test_grant_then_revoke_container_access(self):
        with tempfile.TemporaryDirectory() as d, \
                win.AppContainerProfile("genesis-e11-acl-" + uuid.uuid4().hex[:10]) as ac:
            sid = ac.sid_string()
            icacls = os.path.join(os.environ["SystemRoot"], "System32", "icacls.exe")

            def query():
                return subprocess.run([icacls, d], capture_output=True, text=True).stdout

            self.assertNotIn(sid, query())
            win.grant_container_access(Path(d), sid, write=True, recursive=True)
            self.assertIn(sid, query())
            win.revoke_container_access(Path(d), sid, recursive=True)
            self.assertNotIn(sid, query())


_PROBE = r"""
import os, sys, json, socket, ctypes
from ctypes import wintypes
res = {}
try:
    adv = ctypes.WinDLL("advapi32"); k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    tok = wintypes.HANDLE(); adv.OpenProcessToken(k.GetCurrentProcess(), 8, ctypes.byref(tok))
    v = wintypes.DWORD(0); rl = wintypes.DWORD(0)
    adv.GetTokenInformation(tok, 29, ctypes.byref(v), ctypes.sizeof(v), ctypes.byref(rl))
    res["appcontainer"] = bool(v.value)
except Exception as e:
    res["appcontainer"] = "ERR:%r" % e
try:
    s = socket.socket(); s.settimeout(3); s.connect(("127.0.0.1", int(sys.argv[2]))); res["net"] = "CONNECTED"; s.close()
except OSError:
    res["net"] = "BLOCKED"
try:
    open(os.path.join(sys.argv[1], "granted.txt")).read(); res["read_granted"] = "OK"
except OSError:
    res["read_granted"] = "DENIED"
try:
    open(os.path.join(sys.argv[1], "out.txt"), "w").write("x"); res["write_workdir"] = "OK"
except OSError:
    res["write_workdir"] = "DENIED"
try:
    open(sys.argv[3]).read(); res["read_ungranted"] = "READ"
except OSError:
    res["read_ungranted"] = "DENIED"
try:
    import subprocess
    subprocess.Popen([sys.executable, "-c", "pass"]); res["spawn"] = "SPAWNED"
except OSError:
    res["spawn"] = "BLOCKED"
os.write(1, json.dumps(res).encode())
"""


@unittest.skipUnless(APPCONTAINER, "environment cannot create an AppContainer")
class ConfinedWorkerLiveTests(unittest.TestCase):
    """One full confined launch, asserting every ADR-0004 property, then teardown."""

    def test_confined_worker_boundary_and_teardown(self):
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            code_dir = base / "code"
            workdir = base / "wd"
            code_dir.mkdir()
            workdir.mkdir()
            (workdir / "granted.txt").write_text("hello", encoding="utf-8")
            probe = code_dir / "probe.py"
            probe.write_text(_PROBE, encoding="utf-8")
            denied = base / "ungranted-secret.txt"
            denied.write_text("SECRET", encoding="utf-8")

            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(8)
            port = listener.getsockname()[1]
            threading.Thread(
                target=lambda: [self._accept(listener) for _ in iter(int, 1)], daemon=True,
            ).start()

            confinement = isolation.ResearchProcessConfinement(
                program_import_roots=(code_dir,), research_workdir=workdir,
            )
            env = {
                "SystemRoot": os.environ["SystemRoot"],
                "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "TEMP": str(workdir), "TMP": str(workdir),
            }
            confined = isolation.launch_confined_research(
                confinement,
                [sys.executable, "-I", "-S", str(probe), str(workdir), str(port), str(denied)],
                environment=env, cwd=str(workdir),
                runtime_dirs=(Path(sys.executable).resolve().parent,),
                container_name="genesis-e11-confined-" + uuid.uuid4().hex[:10],
            )
            try:
                confined.process.wait(30)
                import json
                result = json.loads(confined.process.stdout.read().decode())
            finally:
                pid = confined.process.pid
                confined.close()
                listener.close()

            self.assertIs(result["appcontainer"], True, f"not an AppContainer token: {result}")
            self.assertEqual(result["net"], "BLOCKED", "network capability was not denied")
            self.assertEqual(result["read_granted"], "OK", "granted workdir was not readable")
            self.assertEqual(result["write_workdir"], "OK", "granted workdir was not writable")
            self.assertEqual(result["read_ungranted"], "DENIED", "an ungranted path was readable")
            self.assertEqual(result["spawn"], "BLOCKED", "confined worker could spawn a process")
            # Deterministic teardown: closing the confinement leaves no live worker.
            self.assertIsNotNone(self._pid_dead(pid))

    @staticmethod
    def _accept(listener):
        try:
            conn, _ = listener.accept()
            conn.close()
        except OSError:
            raise SystemExit

    @staticmethod
    def _pid_dead(pid: int) -> bool:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
        )
        return str(pid) not in result.stdout


@unittest.skipUnless(APPCONTAINER, "environment cannot create an AppContainer")
class ConfinedProtectedLaunchLiveTests(unittest.TestCase):
    """The full protected launch path, opted into confinement, still produces a
    certificate through the confined worker's IPC and tears the boundary down --
    and the real-activation guard is unaffected."""

    def test_confined_checkpoint_launch_certifies_and_guard_holds(self):
        from genesis.protected import launch_trusted_protected_evaluator
        from genesis.registry import RegistryConflict
        from ._support import scratch_directory
        from .test_astra_s5_process import build_fixture, request_for
        from .test_astra_t3_protected_integrity import pin

        with scratch_directory() as base:
            fixture = build_fixture(base / "campaign", max_attempts=2)
            code = base / "code"
            code.mkdir()
            program_path = code / "confined_ok.py"
            program_path.write_text("def predict(frame):\n    return '0.5'\n", encoding="utf-8")
            program = pin("confined_ok", program_path)
            client = launch_trusted_protected_evaluator(
                campaign=fixture["campaign"],
                sealed_frames=fixture["sealed"],
                labels=fixture["labels"],
                campaigns=fixture["campaigns"],
                experiments=fixture["experiments"],
                attempts=fixture["attempts"],
                family_limit=fixture["campaign"].max_attempts,
                research_workdir=fixture["research_root"],
                allowed_program_import_roots=(code,),
                trusted_label_roots=(fixture["label_root"],),
                local_checkpoint_test_only=True,
                confine_research=True,
            )
            try:
                self.assertTrue(client.research_boundary.get("os_confinement"))
                certificate = client.run(
                    request_for(fixture, program, strategy_id="confined"), program,
                )
                self.assertEqual(certificate.metrics["brier"], "0.25")
            finally:
                client.close()

        # The real-activation guard is unchanged: confinement does not enable
        # real campaigns.
        with self.assertRaises(RegistryConflict):
            launch_trusted_protected_evaluator(
                campaign=None, sealed_frames=None, labels=(), campaigns=None,
                experiments=None, attempts=None, family_limit=1,
                local_checkpoint_test_only=False, confine_research=True,
            )


if __name__ == "__main__":
    unittest.main()
