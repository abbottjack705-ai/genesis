"""Strict JSON decoding (design sections 9.1, 15 F-13, MKT-07).

Exact ``Decimal`` numbers (never ``float``), duplicate-key rejection at every depth, no NaN/Infinity, no BOM, strict
UTF-8 and a hard byte cap. Errors carry a stable ``code`` and never any payload text.

Hostile audit RA5-001: syntactically valid JSON is still provider-controlled content, and no later stage may be handed
content it cannot process. So the decoder also refuses, with a stable code and before anything is derived:

* ``TOO_DEEP`` - nesting deeper than ``max_depth`` containers. The recursion limit is no bound: where ``RecursionError``
  strikes depends on the caller's stack, so the same bytes could derive in one call and fault in another;
* ``NUMBER_OUT_OF_RANGE`` - a numeric literal whose decimal exponent (its adjusted exponent, in either direction)
  exceeds ``max_exponent``, or one too large for ``Decimal`` to represent at all (which raised an uncaught
  ``InvalidOperation`` out of this very function);
* ``INVALID_UTF8`` - a string, key or value, that is not encodable text: a lone surrogate from a ``\\ud800`` escape is
  valid JSON syntax but has no UTF-8 form, and every canonical serialization of it raises.

Both bounds are policy fields and are passed in explicitly: there is no default, so no caller can forget them
(FRZ-10 forbids a literal here).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

# every code a StrictJsonError can carry; ``errors.JSON_FAILURE`` maps each one to its taxonomy outcome
CODES = frozenset({"OVERSIZE", "INVALID_UTF8", "EMPTY", "NOT_JSON", "DUPLICATE_KEYS", "NONFINITE_NUMBER", "TOO_DEEP",
                   "NUMBER_OUT_OF_RANGE"})
_SURROGATE = re.compile("[\ud800-\udfff]")


class StrictJsonError(ValueError):
    """A body that is not acceptable strict JSON. ``code`` is one of :data:`CODES`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Duplicate(Exception):
    pass


class _NonFinite(Exception):
    pass


class _OutOfRange(Exception):
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


def _decimal_literal(max_exponent: int):
    def parse(text: str) -> Decimal:
        try:
            value = Decimal(text)
        except ArithmeticError:                  # an exponent beyond what a Decimal can represent at all
            raise _OutOfRange() from None
        if abs(value.adjusted()) > max_exponent:
            raise _OutOfRange()
        return value

    return parse


def _int_literal(max_exponent: int):
    def parse(text: str) -> int:
        digits = len(text) - 1 if text.startswith("-") else len(text)
        if digits - 1 > max_exponent:            # the same measure as a decimal's adjusted exponent
            raise _OutOfRange()
        return int(text)

    return parse


def _check_structure(root: Any, max_depth: int) -> None:
    """Nesting depth and encodable text, walked iteratively (a recursive walk would be the very hazard it guards
    against). The root container is depth 1; a container entered with ``max_depth`` already open is too deep."""

    stack: list = []                              # one iterator per open container: memory is O(depth)
    node = root
    while True:
        if type(node) is str:
            if not node.isascii() and _SURROGATE.search(node):
                raise StrictJsonError("INVALID_UTF8")
        elif type(node) is dict:
            if len(stack) >= max_depth:
                raise StrictJsonError("TOO_DEEP")
            for key in node:
                if not key.isascii() and _SURROGATE.search(key):
                    raise StrictJsonError("INVALID_UTF8")
            stack.append(iter(node.values()))
        elif type(node) is list:
            if len(stack) >= max_depth:
                raise StrictJsonError("TOO_DEEP")
            stack.append(iter(node))
        while stack:
            try:
                node = next(stack[-1])
                break
            except StopIteration:
                stack.pop()
        else:
            return


def loads_strict(data: bytes, *, max_bytes: int, max_depth: int, max_exponent: int):
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
        value = json.loads(text, parse_float=_decimal_literal(max_exponent), parse_int=_int_literal(max_exponent),
                           parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except _Duplicate:
        raise StrictJsonError("DUPLICATE_KEYS") from None
    except _NonFinite:
        raise StrictJsonError("NONFINITE_NUMBER") from None
    except _OutOfRange:
        raise StrictJsonError("NUMBER_OUT_OF_RANGE") from None
    except RecursionError:                        # the decoder's own recursion limit: nesting far beyond any bound
        raise StrictJsonError("TOO_DEEP") from None
    except ValueError:
        raise StrictJsonError("NOT_JSON") from None
    _check_structure(value, max_depth)
    return value
