"""Outer OS-level confinement for the protected research process (ADR-0004).

Policy layer + orchestrator. This module reconciles ADR-0003 with the E11
finding that the in-process CPython audit hook is *not* a sandbox: ADR-0003
grants the research process "explicit filesystem access, no network, controlled
native-code exposure", but the audit hook only *asserts* those constraints
inside a cooperating interpreter. The real boundary is an OS confinement (Windows
AppContainer + Job Object; a POSIX unprivileged-uid + empty-network-namespace
analog) created around the same launch.

The Windows primitives are now IMPLEMENTED in ``protected_confinement_win`` and
orchestrated here by :class:`ConfinedResearchProcess` / :func:`launch_confined_research`:
a capability-less AppContainer (no network), a Job Object (one process, memory
cap, kill-on-close), explicit filesystem ACLs, a restricted inherited-handle set,
and a suspended launch assigned to the job before it runs. They are wired into
the local checkpoint/test path only, behind an explicit opt-in
(``confine_research=True``), and they fail closed.

Real protected-campaign activation stays DISABLED: the launcher guard still
blocks any non-test launch, :data:`ACTIVATION_ENABLED` is ``False``, and
:func:`apply_confinement` (the real-activation entry) still refuses, because
ADR-0004 is PROPOSED, not approved. Nothing here claims the audit hook is a
sandbox; that hook remains defense in depth. This is the OS boundary it is
defence for.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ResearchConfinementNotActivated(RuntimeError):
    """Raised when real OS confinement is requested while activation is disabled."""


# ADR-0004 is PROPOSED, not approved, and the OS primitives are unimplemented, so
# real activation is off.  This flag is documentation and a single, greppable
# gate; no value passed to `apply_confinement` can turn activation on in this
# build (see that function).
ACTIVATION_ENABLED = False


def _resolved(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_absolute():
        raise ValueError("research confinement paths must be absolute")
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


@dataclass(frozen=True)
class ResearchProcessConfinement:
    """The exact outer boundary required by ADR-0004 for one research launch.

    Data only: constructing it grants no capability. The three non-path fields
    are fixed invariants, not tunable knobs -- the checkpoint boundary always
    denies the network and child processes and always kills on teardown -- so a
    request to relax any of them fails closed at construction.
    """

    program_import_roots: tuple[Path, ...]
    research_workdir: Path
    denied_label_roots: tuple[Path, ...] = ()
    allow_network: bool = False
    allow_child_processes: bool = False
    kill_on_teardown: bool = True

    def __post_init__(self) -> None:
        if self.allow_network:
            raise ValueError("research confinement must deny all network access")
        if self.allow_child_processes:
            raise ValueError("research confinement must deny child-process creation")
        if not self.kill_on_teardown:
            raise ValueError("research confinement must kill the process tree on teardown")
        roots = tuple(_resolved(root) for root in self.program_import_roots)
        workdir = _resolved(self.research_workdir)
        labels = tuple(_resolved(root) for root in self.denied_label_roots)
        if not roots:
            raise ValueError("research confinement requires at least one import root")
        # ADR-0003 already requires research and trusted-label paths disjoint; the
        # OS boundary must not grant filesystem access that overlaps a label root.
        for label_root in labels:
            if _overlap(workdir, label_root) or any(_overlap(root, label_root) for root in roots):
                raise ValueError("granted research paths must be disjoint from label roots")
        object.__setattr__(self, "program_import_roots", roots)
        object.__setattr__(self, "research_workdir", workdir)
        object.__setattr__(self, "denied_label_roots", labels)


def plan_confinement(confinement: ResearchProcessConfinement) -> dict[str, Any]:
    """Return the concrete OS mechanism :func:`apply_confinement` *would* install.

    Pure, inspectable data; it installs nothing and is safe to call. The plan is
    the four ADR-0004 properties made explicit for the local Windows development
    target (with the POSIX analog named), so the boundary can be reviewed and
    tested without being activated.
    """

    return {
        "adr": "ADR-0004",
        "principal": "windows_appcontainer_per_launch_capability_sid",
        # No internetClient / internetClientServer / privateNetworkClientServer
        # capability is granted, so the process cannot reach any network endpoint.
        "network_capabilities_granted": (),
        "network_reachable": False,
        # Default-deny filesystem: the low-privilege principal has no access to
        # the user's files except these explicit grants.
        "filesystem_grants": {
            "read_execute": tuple(str(root) for root in confinement.program_import_roots),
            "read_write": (str(confinement.research_workdir),),
        },
        "filesystem_denied_roots": tuple(str(root) for root in confinement.denied_label_roots),
        # Job Object: no escaping child processes, killed as one tree on teardown.
        "job_object": {
            "active_process_limit": 1,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "kill_on_job_close": True,
        },
        "posix_analog": (
            "dedicated unprivileged uid/gid + empty network namespace + "
            "bind-mounted read-only import roots and read-write workdir"
        ),
    }


def apply_confinement(
    confinement: ResearchProcessConfinement,
    *,
    approval_token: object = None,
) -> None:
    """Real-activation entry point -- still FAIL-CLOSED.

    The OS primitives now exist (see :func:`launch_confined_research` and
    ``protected_confinement_win``), but ADR-0004 remains PROPOSED, so *real
    protected-campaign* activation of the boundary is not authorised. This entry
    point, used by the real-activation path, therefore still refuses regardless
    of arguments; the boundary is exercised only by the local checkpoint/test
    path via :func:`launch_confined_research`. Real activation requires operator
    approval of ADR-0004 and a fresh independent re-audit.
    """

    _ = plan_confinement(confinement)
    raise ResearchConfinementNotActivated(
        "OS-level research confinement (ADR-0004) is not approved for real activation"
    )


class ConfinedResearchProcess:
    """A confined research worker: a ``subprocess.Popen``-compatible process
    running inside an AppContainer (no network capability) and a Job Object
    (one process, memory cap, kill-on-close), with an explicit inherited-handle
    set and filesystem access only to the granted paths.

    Construction performs the whole sequence and **fails closed**: if any step
    (profile, ACL grant, job, suspended launch, job assignment, resume) fails,
    every partial resource is released and no worker is left running. ``close``
    tears the boundary down deterministically: closing the job kills the tree,
    then the granted ACLs are revoked and the container profile deleted.

    It is created only by the local checkpoint/test path; real protected-campaign
    activation stays disabled at the launcher guard.
    """

    def __init__(
        self,
        confinement: "ResearchProcessConfinement",
        argv: list[str],
        *,
        environment: dict[str, str],
        cwd: str,
        runtime_dirs: tuple[Path, ...],
        container_name: str,
    ):
        if sys.platform != "win32":
            raise ResearchConfinementNotActivated("OS confinement requires Windows")
        # Imported lazily so the module imports cleanly off-Windows and in tests
        # that only exercise the policy layer.
        from genesis import protected_confinement_win as win

        self._win = win
        self._profile = None
        self._job = None
        self._granted: list[tuple[Path, bool]] = []  # (path, recursive) to revoke
        self._sid = ""
        self.process = None
        try:
            self._profile = win.AppContainerProfile(container_name)
            self._sid = self._profile.sid_string()
            self._job = win.ConfinementJob(
                memory_limit_bytes=_MEMORY_LIMIT_BYTES, active_process_limit=1,
            )
            # Explicit filesystem grants: read/execute on the runtime and import
            # roots (recursive, materialised over pre-existing files), read/write
            # on the dedicated per-launch workdir. Everything else stays denied.
            for runtime_dir in runtime_dirs:
                self._grant(runtime_dir, write=False, recursive=True)
            for root in confinement.program_import_roots:
                self._grant(root, write=False, recursive=True)
            self._grant(confinement.research_workdir, write=True, recursive=True)
            self.process = win.launch_confined_worker(
                argv,
                environment=environment,
                cwd=cwd,
                job=self._job,
                security_capabilities=self._profile.security_capabilities(),
            )
        except BaseException:
            self.close()
            raise

    def _grant(self, path: Path, *, write: bool, recursive: bool) -> None:
        self._win.grant_container_access(path, self._sid, write=write, recursive=recursive)
        self._granted.append((path, recursive))

    def close(self) -> None:
        # Kill the tree first (job close), then release the ACLs and the profile.
        if self._job is not None:
            self._job.close()
            self._job = None
        if self.process is not None:
            self.process._close_handles()
        while self._granted:
            path, recursive = self._granted.pop()
            try:
                self._win.revoke_container_access(path, self._sid, recursive=recursive)
            except Exception:
                pass
        if self._profile is not None:
            self._profile.close()
            self._profile = None


# Per-launch committed-memory cap for the confined worker (512 MiB): generous for
# pure prediction, hard enough that a runaway allocation fails closed.
_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


def launch_confined_research(
    confinement: ResearchProcessConfinement,
    argv: list[str],
    *,
    environment: dict[str, str],
    cwd: str,
    runtime_dirs: tuple[Path, ...],
    container_name: str,
) -> ConfinedResearchProcess:
    """Launch the research worker under the full ADR-0004 OS confinement.

    Used only by the local checkpoint/test path. Fails closed on any error.
    """

    return ConfinedResearchProcess(
        confinement, argv, environment=environment, cwd=cwd,
        runtime_dirs=runtime_dirs, container_name=container_name,
    )
