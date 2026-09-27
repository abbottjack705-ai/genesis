"""Outer OS-level confinement for the protected research process (ADR-0004).

DISABLED SCAFFOLD. This module defines the outer operating-system boundary that
``ADR-0004-s5-os-confinement-boundary.md`` requires before any real protected
activation, expressed as inspectable data plus a fail-closed applicator. It is
deliberately NOT wired into the local-checkpoint launch and grants no capability
of its own: :func:`apply_confinement` refuses to run, so real OS confinement
cannot be activated by this build.

It exists to reconcile ADR-0003 with the E11 finding that the in-process CPython
audit hook is *not* a sandbox. ADR-0003 grants the research process "explicit
filesystem access, no network, controlled native-code exposure"; the audit hook
only *asserts* those constraints inside a cooperating interpreter. The real
boundary is an OS confinement (Windows AppContainer + Job Object; a POSIX
unprivileged-uid + empty-network-namespace analog) created around the same
launch. This module states that boundary precisely; the primitives that install
it are implemented only after ADR-0004 is approved and independently re-audited.

Nothing here claims the audit hook is a sandbox. That hook remains defense in
depth. This is the OS boundary it is defence for.
"""

from __future__ import annotations

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
    """Install the OS confinement around the research process.

    FAIL-CLOSED. Real OS confinement is not approved for activation (ADR-0004 is
    proposed, not approved, and the AppContainer/Job-Object primitives are
    unimplemented), so this refuses regardless of arguments. No ``approval_token``
    value can enable it in this build; activation requires approved code that
    supplies the OS primitives and passes a fresh independent re-audit. Callers
    on the real-activation path therefore fail closed rather than run a research
    process under a boundary that does not yet exist.
    """

    # Validate the descriptor so an approved implementation inherits the checks,
    # then refuse: the boundary must never silently degrade to "no confinement".
    _ = plan_confinement(confinement)
    raise ResearchConfinementNotActivated(
        "OS-level research confinement (ADR-0004) is not approved for activation"
    )
