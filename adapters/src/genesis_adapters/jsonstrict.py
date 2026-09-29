"""Strict JSON decoding (design sections 9.1, 15 F-13, MKT-07).

Exact ``Decimal`` numbers (never ``float``), duplicate-key rejection at every depth, no
NaN/Infinity, no BOM, strict UTF-8 and a hard byte cap. Errors carry a stable ``code`` and
never any payload text.
"""

from __future__ import annotations

import json
from decimal import Decimal


class StrictJsonError(ValueError):
    """A body that is not acceptable strict JSON. ``code`` is one of the F-13 detail codes."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Duplicate(Exception):
    pass


class _NonFinite(Exception):
    pass


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _Duplicate()
        seen[key] = value
    return seen


def _reject_constant(_name):
    raise _NonFinite()


def loads_strict(data: bytes, *, max_bytes: int):
    """Decode ``data`` or raise :class:`StrictJsonError` (``OVERSIZE`` is checked first)."""

    if not isinstance(data, (bytes, bytearray)):
        raise StrictJsonError("NOT_JSON")
    if len(data) > max_bytes:
        raise StrictJsonError("OVERSIZE")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise StrictJsonError("INVALID_UTF8") from None
    if not text.strip(" \t\n\r"):
        raise StrictJsonError("EMPTY")
    try:
        return json.loads(text, parse_float=Decimal, parse_int=int,
                          parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except _Duplicate:
        raise StrictJsonError("DUPLICATE_KEYS") from None
    except _NonFinite:
        raise StrictJsonError("NONFINITE_NUMBER") from None
    except (ValueError, RecursionError):
        raise StrictJsonError("NOT_JSON") from None
