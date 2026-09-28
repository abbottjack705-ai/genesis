"""TEST-ONLY AST scanners (FRZ-05, FRZ-06, FRZ-07, FRZ-08, FRZ-10, FRZ-11).

Each scanner takes ``(relative_path, source_text)`` and returns a list of violation
strings, so the tests can prove it both accepts clean code and flags planted
violations, and then run it over the real ``genesis_adapters`` package.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "genesis_adapters"
TRANSPORT_MODULE = "oddspapi/transport_http.py"
CLI_MODULE = "cli.py"

NETWORK_ROOTS = {"socket", "ssl", "requests", "httpx", "aiohttp"}
NETWORK_DOTTED = ("http", "urllib.request")


def package_files() -> list[tuple[str, str]]:
    result = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = path.relative_to(PACKAGE_DIR).as_posix()
        result.append((rel, path.read_text(encoding="utf-8")))
    return result


def _walk(tree: ast.AST):
    return ast.walk(tree)


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """local name -> dotted origin, for every import."""

    names: dict[str, str] = {}
    for node in _walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[(alias.asname or alias.name).split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


# -- FRZ-05 ---------------------------------------------------------------------------
def scan_frz05(rel: str, source: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    genesis_names = {local for local, origin in _imported_names(tree).items()
                     if origin == "genesis" or origin.startswith("genesis.")}
    for node in _walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "genesis" or node.module.startswith("genesis.")):
            for alias in node.names:
                if alias.name.startswith("_"):
                    problems.append(f"{rel}:{node.lineno}: private genesis import {alias.name}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(part.startswith("_") for part in alias.name.split(".")
                       ) and alias.name.startswith("genesis"):
                    problems.append(f"{rel}:{node.lineno}: private genesis import {alias.name}")
        # attribute assignment / deletion onto a genesis-imported object
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign,)):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        for target in targets:
            if isinstance(target, ast.Attribute):
                root = target
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in genesis_names:
                    problems.append(f"{rel}:{node.lineno}: assignment onto genesis object {root.id}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "setattr", "delattr"} and node.args:
            first = node.args[0]
            root = first
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in genesis_names:
                problems.append(f"{rel}:{node.lineno}: {node.func.id} on genesis object")
        # subclassing a frozen class and overriding a method
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                root = base
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in genesis_names:
                    if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                           for item in node.body):
                        problems.append(f"{rel}:{node.lineno}: subclass of frozen {ast.unparse(base)}"
                                        " defines methods")
        # private attribute access anywhere except on self/cls/dunder
        if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not (
                node.attr.startswith("__") and node.attr.endswith("__")):
            base = node.value
            if not (isinstance(base, ast.Name) and base.id in {"self", "cls"}):
                problems.append(f"{rel}:{node.lineno}: private attribute access .{node.attr}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" \
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str) and node.args[1].value.startswith("_") \
                and not node.args[1].value.startswith("__"):
            problems.append(f"{rel}:{node.lineno}: getattr of private name")
    return problems


# -- FRZ-06 ---------------------------------------------------------------------------
def _is_network_module(name: str) -> bool:
    root = name.split(".")[0]
    if root in NETWORK_ROOTS:
        return True
    return name == "http" or name.startswith("http.") or name == "urllib.request" \
        or name.startswith("urllib.request.")


def scan_frz06(rel: str, source: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    is_transport = rel == TRANSPORT_MODULE
    for node in _walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
            if node.module == "urllib":
                modules += [f"urllib.{alias.name}" for alias in node.names]
        for name in modules:
            if _is_network_module(name) and not is_transport:
                problems.append(f"{rel}:{node.lineno}: network import {name}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "reveal_for_transport" and not is_transport:
            problems.append(f"{rel}:{node.lineno}: reveal_for_transport outside transport")
    return problems


# -- FRZ-07 ---------------------------------------------------------------------------
_RESERVE_NAMES = {"QuotaReserveAuthorization", "grant_authorization", "revoke_authorization"}


def scan_frz07(rel: str, source: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    for node in _walk(tree):
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
            if node.attr == "RESERVE":
                base = node.value
                if isinstance(base, ast.Name) and base.id == "BudgetClass":
                    problems.append(f"{rel}:{node.lineno}: BudgetClass.RESERVE")
        elif isinstance(node, ast.alias):
            name = node.name.split(".")[-1]
        if name in _RESERVE_NAMES:
            problems.append(f"{rel}:{getattr(node, 'lineno', 0)}: reserve authority name {name}")
    return problems


# -- FRZ-08 ---------------------------------------------------------------------------
def scan_frz08(rel: str, source: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    for node in _walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in {"FixedClock", "FakeTransport"}:
            problems.append(f"{rel}:{node.lineno}: test-only class {node.name} defined in production")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name in {"FixedClock", "FakeTransport"}:
                    problems.append(f"{rel}:{node.lineno}: imports test-only {alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("adapter_tests"):
                problems.append(f"{rel}:{node.lineno}: production imports adapter_tests")
        if rel != CLI_MODULE:
            if isinstance(node, ast.Attribute) and node.attr == "READY":
                problems.append(f"{rel}:{node.lineno}: .READY referenced")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "OperationalStatus" and node.args \
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == "ready":
                problems.append(f"{rel}:{node.lineno}: OperationalStatus('ready')")
    return problems


# -- FRZ-11 ---------------------------------------------------------------------------
_PROCESS_CONTROL = {"BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"<bare>"}
    exprs = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names: set[str] = set()
    for expr in exprs:
        if isinstance(expr, ast.Name):
            names.add(expr.id)
        elif isinstance(expr, ast.Attribute):
            names.add(expr.attr)
    return names


def scan_frz11(rel: str, source: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    for node in _walk(tree):
        if isinstance(node, ast.ExceptHandler):
            names = _handler_names(node)
            if names & (_PROCESS_CONTROL | {"<bare>"}):
                allowed = rel == TRANSPORT_MODULE and names == {"BaseException"}
                if not allowed:
                    problems.append(f"{rel}:{node.lineno}: process-control handler {sorted(names)}")
                else:
                    for inner in ast.walk(node):
                        if isinstance(inner, (ast.Return, ast.Break, ast.Continue)):
                            problems.append(f"{rel}:{inner.lineno}: flow statement inside "
                                            "the BaseException clause")
        if isinstance(node, ast.Call):
            func = node.func
            target = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if target == "suppress":
                for arg in node.args:
                    label = arg.attr if isinstance(arg, ast.Attribute) else (
                        arg.id if isinstance(arg, ast.Name) else None)
                    if label in _PROCESS_CONTROL:
                        problems.append(f"{rel}:{node.lineno}: suppress({label})")
        if isinstance(node, ast.Try):
            for statement in node.finalbody:
                for inner in ast.walk(statement):
                    if isinstance(inner, (ast.Return, ast.Break, ast.Continue)):
                        problems.append(f"{rel}:{inner.lineno}: flow statement inside finally")
    if rel == TRANSPORT_MODULE:
        problems += _check_transport_reraise(rel, tree)
    return problems


def _check_transport_reraise(rel: str, tree: ast.AST) -> list[str]:
    """The single BaseException clause must be followed, after its try block, by a raise."""

    problems: list[str] = []
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for parent in ast.walk(node):
                if isinstance(parent, ast.Try):
                    for handler in parent.handlers:
                        if _handler_names(handler) == {"BaseException"}:
                            found = True
                            body = node.body
                            containing = [i for i, stmt in enumerate(body)
                                          if any(child is parent for child in ast.walk(stmt))]
                            if not containing:
                                problems.append(f"{rel}: cannot locate the BaseException try")
                                continue
                            following = body[containing[-1] + 1:]
                            if not any(any(isinstance(n, ast.Raise) for n in ast.walk(stmt))
                                       for stmt in following) and not any(
                                    any(isinstance(n, ast.Raise) for n in ast.walk(stmt))
                                    for stmt in parent.orelse):
                                problems.append(f"{rel}:{handler.lineno}: no re-raise after the "
                                                "BaseException clause")
    return problems


# -- FRZ-10 ---------------------------------------------------------------------------
_TIME_CALLS = {"settimeout", "setdefaulttimeout", "sleep", "timedelta", "wait", "join",
               "create_connection", "HTTPSConnection", "HTTPConnection"}
_NAME_PATTERN = re.compile(
    r"(_seconds|_ms|_micros|_minutes|_hours|_days|_bytes|_chars|_ttl|ttl_|timeout|deadline|"
    r"tolerance|threshold|_max|_min|max_|min_|limit|backoff|budget|ceiling|drift|skew|guard)",
    re.IGNORECASE)
_STRUCTURAL = {0, 1, -1}


def _numeric(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _numeric(node.operand)
        if inner is not None:
            return -inner if isinstance(node.op, ast.USub) else inner
    return None


def scan_frz10(rel: str, source: str, *, policy_values: frozenset = frozenset()) -> list[str]:
    """Flag numeric literals used as durations, bounds, thresholds or timeouts.

    Three complementary rules (all context based, so structural integers such as
    ``[:16]`` or ``range(3)`` are not flagged):

    * a numeric literal argument to a time/timeout call or a ``timeout=``-style keyword;
    * a numeric literal bound to a name that reads like a duration/bound/threshold;
    * any numeric literal equal to a large (>= 60) numeric value of the loaded policy.
    """

    tree = ast.parse(source)
    problems: list[str] = []
    big = {v for v in policy_values if isinstance(v, (int, float)) and abs(v) >= 60}

    def flag(node: ast.AST, why: str) -> None:
        problems.append(f"{rel}:{getattr(node, 'lineno', 0)}: {why}")

    for node in _walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            label = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if label in _TIME_CALLS:
                for arg in node.args:
                    value = _numeric(arg)
                    if value is not None and value not in _STRUCTURAL:
                        flag(arg, f"numeric literal {value!r} passed to {label}()")
            for keyword in node.keywords:
                value = _numeric(keyword.value)
                if value is not None and value not in _STRUCTURAL and keyword.arg and (
                        _NAME_PATTERN.search(keyword.arg) or label in _TIME_CALLS):
                    flag(keyword.value, f"numeric literal {value!r} for keyword {keyword.arg}=")
        targets: list[tuple[str, ast.AST | None]] = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append((target.id, node.value))
                elif isinstance(target, ast.Attribute):
                    targets.append((target.attr, node.value))
        elif isinstance(node, (ast.AnnAssign,)) and node.value is not None:
            if isinstance(node.target, ast.Name):
                targets.append((node.target.id, node.value))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            names = [a.arg for a in node.args.args][-len(node.args.defaults):] if node.args.defaults \
                else []
            names += [a.arg for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults) if d is not None]
            for name, default in zip(names, defaults):
                targets.append((name, default))
        for name, value_node in targets:
            value = _numeric(value_node) if value_node is not None else None
            if value is not None and value not in _STRUCTURAL and _NAME_PATTERN.search(name):
                flag(value_node, f"numeric literal {value!r} bound to {name}")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool) and node.value in big:
            flag(node, f"numeric literal {node.value!r} equals a policy value")
    return sorted(set(problems))


def scan_all(scanner, *, exclude: tuple[str, ...] = (), **kwargs) -> list[str]:
    problems: list[str] = []
    for rel, source in package_files():
        if rel in exclude:
            continue
        problems += scanner(rel, source, **kwargs)
    return problems
