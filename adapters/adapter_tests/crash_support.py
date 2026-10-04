"""TEST-ONLY: deterministic cuts at the persistence layer (a crash, or an I/O error, at one exact write).

A cut wraps ONE append method of a ledger class. The first matching append is either never performed (``where="before"``:
nothing is durable, the process dies or the write fails) or performed and then followed by the process's death
(``where="after"``: the row IS durable, nothing after it ran). It fires once and then lets every later append through, so
a test restarts "the process" over the same root exactly as an operator would. Because the cut sits on the persistence
layer rather than on a named checkpoint of production code, the same test drives any version of the code under test.
"""

from __future__ import annotations

import contextlib
from unittest import mock

from .support import Crash


@contextlib.contextmanager
def cut(owner, hit, *, where: str, error: BaseException | None = None, name: str = "append"):
    """Arm one cut on ``owner.<name>``. ``hit(args, kwargs)`` says which call it is; the yielded dict counts firings."""

    if where not in ("before", "after"):
        raise ValueError(where)
    state = {"fired": 0}
    real = getattr(owner, name)

    def wrapper(this, *args, **kwargs):
        if state["fired"] or not hit(args, kwargs):
            return real(this, *args, **kwargs)
        state["fired"] += 1
        if where == "before":
            raise error if error is not None else Crash()
        real(this, *args, **kwargs)                          # durable ...
        raise Crash()                                       # ... and the process dies before the call returns

    with mock.patch.object(owner, name, wrapper):
        yield state
