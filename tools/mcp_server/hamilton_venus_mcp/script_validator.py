"""Static feasibility check for scripts before they are imported or run.

Nothing here executes the script. It parses it (``ast``), resolves its ``hamilton_venus``
imports against the installed SDK, finds the ``StarClient``/``VantageClient`` objects it builds,
and checks every ``client.method(...)`` call against the same command catalog the spoke's
``call_sdk_command`` uses: the method must exist, its keyword names must be real, required
arguments must be present, and any argument whose value can be worked out statically (literals,
module constants, catalog/enum attributes, ``hamilton_venus.models`` constructors) is validated
with the pydantic type adapters ``coercion.coerce_kwargs`` uses. Arguments that cannot be
worked out statically are counted as "unverified", not treated as failures.

It also enforces the policy for scripts that run unattended on a spoke: no GUI dialogs or
``input()`` (there is no human at the console), and no obviously dangerous constructs
(subprocesses, sockets, ``eval``/``exec``, deleting files). Those rules are a guardrail, not a
sandbox.

Every finding has a stable rule id:

    V001 syntax error                       V020 unresolved hamilton_venus import
    V010 forbidden import                   V021 unknown client command
    V011 forbidden call                     V022 bad call signature / constructor argument
    V012 headless: GUI dialog / input()     V023 argument value fails validation
    V014 import not available here          V025 unknown catalog / enum attribute
    V026 empty channel list                 V027 position selector does not parse
    W030 labware id used but never added    W032 no instrument client found
    W033 hard-coded simulate=False          W034 value wrapped in literal quote characters
    V028 client for the other instrument family than this spoke's VENUS (StarClient on a Vantage)
    W035 tips picked up, tip counters never set up
    W036 aspirate / dispense without settings= (runs on the defaults)
    W037 aspirate with liquid following but no LLD
"""

from __future__ import annotations

import ast
import difflib
import importlib
import importlib.util
import inspect
import operator
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from hamilton_venus_mcp import instrument_guard
from hamilton_venus_mcp.scripts_store import sha256_of

# -- policy tables -------------------------------------------------------------------------

_GUI_MODULES = ("tkinter", "_tkinter", "turtle")
_FORBIDDEN_MODULES = (
    "subprocess",
    "socket",
    "socketserver",
    "ctypes",
    "multiprocessing",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "http.client",
    "http.server",
    "urllib.request",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "paramiko",
    "pexpect",
    "pty",
    "winreg",
    "webbrowser",
)
_FORBIDDEN_BUILTIN_CALLS = {"eval", "exec", "compile", "__import__"}
_FORBIDDEN_DOTTED_CALLS = (
    "os.system",
    "os.popen",
    "os.startfile",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.removedirs",
    "shutil.rmtree",
)
_FORBIDDEN_DOTTED_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn")

_CLIENT_CLASS_NAMES = ("StarClient", "VantageClient")
_SELECTOR_PARAMS = {"positions", "reagent_source", "dest_plate", "source_plate", "plate_id", "carrier_id"}
_ID_DEFINING_PARAMS = {"labware_id", "plate_id"}
# W035: a script that picks up tips sets up the tip counters first (reset in simulation, shown on
# the instrument), or the first pickup fails with "Rack transport is not possible".
_TIP_COUNTER_SETUP = ("tip_pool_reset_tip_counter", "tip_pool_show_tip_counter", "tip_pool_show_tip_counters",
                      "tip_pool_initialize_tip_counter", "tip_pool_set_tip_counter")

_SAFE_BUILTINS: dict[str, Any] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "list": list,
    "tuple": tuple,
    "dict": dict,
    "set": set,
    "len": len,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sorted": sorted,
}

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_MAX_EVAL_DEPTH = 40


class _Unresolved(Exception):
    """A value that cannot be worked out without running the script."""


# -- report --------------------------------------------------------------------------------


@dataclass
class Issue:
    rule: str
    severity: str  # "error" | "warning"
    message: str
    line: int | None = None
    col: int | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"rule": self.rule, "severity": self.severity, "message": self.message}
        if self.line is not None:
            data["line"] = self.line
        if self.col is not None:
            data["col"] = self.col
        if self.suggestion:
            data["suggestion"] = self.suggestion
        return data


@dataclass
class ValidationReport:
    sha256: str
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "sha256": self.sha256,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "info": self.info,
        }


# -- helpers -------------------------------------------------------------------------------


def _suggest(word: str, candidates: Any) -> str | None:
    matches = difflib.get_close_matches(word, list(candidates), n=3, cutoff=0.6)
    return "did you mean " + " / ".join(repr(m) for m in matches) + "?" if matches else None


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _module_matches(module: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return None


def _first_pydantic_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    first = errors[0]
    where = ".".join(str(part) for part in first.get("loc", ()))
    text = first.get("msg", "invalid value")
    text = f"{where}: {text}" if where else text
    return text + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else "")


class _Validator:
    def __init__(self, source: str, filename: str) -> None:
        self.source = source
        self.filename = filename
        self.report = ValidationReport(sha256=sha256_of(source.encode("utf-8")))
        self.namespace: dict[str, Any] = {}  # imported hamilton_venus names -> real objects
        self.aliases: dict[str, str] = {}  # local name -> dotted import path (for policy checks)
        self.defined_names: set[str] = set()  # every name the script itself defines or assigns
        self.const_nodes: dict[str, ast.expr] = {}
        self.const_cache: dict[str, Any] = {}
        self._const_in_progress: set[str] = set()
        self.client_vars: dict[str, type] = {}
        self._reported: set[tuple[str, int | None, int | None]] = set()
        self.checked_args = 0
        self.unverified_args = 0
        self.commands_used: dict[str, list[int]] = {}
        self.unchecked_commands: set[str] = set()
        self.clients: list[dict[str, Any]] = []
        self.added_labware: set[str] = set()
        self.used_labware: dict[str, int] = {}
        self.adds_without_id = 0
        self.loads_deck = False
        self.imports: set[str] = set()

    # -- reporting -----------------------------------------------------------------------

    def _add(self, severity: str, rule: str, message: str, node: ast.AST | None = None, suggestion: str | None = None) -> None:
        line = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", None)
        key = (rule + message, line, col)
        if key in self._reported:
            return
        self._reported.add(key)
        issue = Issue(rule, severity, message, line, col, suggestion)
        (self.report.errors if severity == "error" else self.report.warnings).append(issue)

    def error(self, rule: str, message: str, node: ast.AST | None = None, suggestion: str | None = None) -> None:
        self._add("error", rule, message, node, suggestion)

    def warning(self, rule: str, message: str, node: ast.AST | None = None, suggestion: str | None = None) -> None:
        self._add("warning", rule, message, node, suggestion)

    # -- driver --------------------------------------------------------------------------

    def run(self) -> ValidationReport:
        try:
            tree = ast.parse(self.source, filename=self.filename)
        except SyntaxError as exc:
            self.report.errors.append(
                Issue("V001", "error", f"Syntax error: {exc.msg}", exc.lineno, exc.offset)
            )
            return self.report

        self._collect_constants(tree)
        self._check_imports_and_policy(tree)
        self._find_clients(tree)
        self._check_calls(tree)
        self._finish()
        return self.report

    # -- imports and policy --------------------------------------------------------------

    def _check_imports_and_policy(self, tree: ast.Module) -> None:
        nodes = list(ast.walk(tree))
        # All imports first, so a call's alias lookup never depends on where the import sits.
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._handle_import(node, alias.name, alias.asname)
            elif isinstance(node, ast.ImportFrom):
                self._handle_import_from(node)
        for node in nodes:
            if isinstance(node, ast.Call):
                self._check_call_policy(node)

    def _policy_check_module(self, node: ast.AST, module: str) -> bool:
        """True when *module* is refused outright (so no further import checks are needed)."""
        gui = _module_matches(module, _GUI_MODULES)
        if gui:
            self.error("V012", f"'{module}' is not allowed: scripts run headless, with no one to answer a dialog.", node)
            return True
        forbidden = _module_matches(module, _FORBIDDEN_MODULES)
        if forbidden:
            self.error("V010", f"Import of '{module}' is not allowed in scripts run through the MCP server.", node)
            return True
        return False

    def _handle_import(self, node: ast.Import, module: str, asname: str | None) -> None:
        self.imports.add(module)
        local = asname or module.split(".")[0]
        self.aliases[local] = module if asname else module.split(".")[0]
        if self._policy_check_module(node, module):
            return
        top = module.split(".")[0]
        if top == "hamilton_venus":
            try:
                imported = importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001 - any import failure is a finding
                self.error("V020", f"Cannot import '{module}': {exc}", node)
                return
            self.namespace[local] = imported if asname else importlib.import_module(top)
        else:
            self._check_importable(node, module)

    def _handle_import_from(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.error("V014", "Relative imports are not available: a script must be self-contained.", node)
            return
        module = node.module or ""
        self.imports.add(module)
        if self._policy_check_module(node, module):
            return
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = f"{module}.{alias.name}"
        top = module.split(".")[0]
        if top != "hamilton_venus":
            self._check_importable(node, module)
            return
        try:
            imported = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001
            self.error("V020", f"Cannot import '{module}': {exc}", node)
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            if hasattr(imported, alias.name):
                self.namespace[local] = getattr(imported, alias.name)
                continue
            try:
                self.namespace[local] = importlib.import_module(f"{module}.{alias.name}")
            except Exception:  # noqa: BLE001
                public = [n for n in dir(imported) if not n.startswith("_")]
                self.error(
                    "V020",
                    f"'{module}' has no name '{alias.name}'.",
                    node,
                    _suggest(alias.name, public),
                )

    def _check_importable(self, node: ast.AST, module: str) -> None:
        top = module.split(".")[0]
        if not top or top in sys.stdlib_module_names or top in sys.builtin_module_names:
            return
        try:
            found = importlib.util.find_spec(top) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            self.error("V014", f"Module '{top}' is not installed in the spoke's environment.", node)

    def _check_call_policy(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            shadowed = func.id in self.aliases or func.id in self.defined_names
            if func.id in _FORBIDDEN_BUILTIN_CALLS and not shadowed:
                self.error("V011", f"Call to '{func.id}()' is not allowed.", node)
                return
            if func.id == "input" and not shadowed:
                self.error("V012", "input() is not allowed: scripts run headless, with no one at the console.", node)
                return
        dotted = _dotted_name(func)
        if dotted is None:
            return
        head, _, rest = dotted.partition(".")
        resolved = self.aliases.get(head, head) + ("." + rest if rest else "")
        if resolved in _FORBIDDEN_DOTTED_CALLS or resolved.startswith(_FORBIDDEN_DOTTED_PREFIXES):
            self.error("V011", f"Call to '{resolved}()' is not allowed.", node)

    # -- static values -------------------------------------------------------------------

    def _collect_constants(self, tree: ast.Module) -> None:
        store_counts: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                store_counts[node.id] = store_counts.get(node.id, 0) + 1
            elif isinstance(node, ast.Global):
                for name in node.names:
                    store_counts[name] = store_counts.get(name, 0) + 2
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                store_counts[node.name] = store_counts.get(node.name, 0) + 1
            elif isinstance(node, ast.arg):
                store_counts[node.arg] = store_counts.get(node.arg, 0) + 1
        self.defined_names = set(store_counts)
        for node in tree.body:
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            if isinstance(target, ast.Name) and value is not None and store_counts.get(target.id, 0) == 1:
                self.const_nodes[target.id] = value

    def _const(self, name: str) -> Any:
        if name in self.const_cache:
            return self.const_cache[name]
        if name not in self.const_nodes or name in self._const_in_progress:
            raise _Unresolved(name)
        self._const_in_progress.add(name)
        try:
            value = self._eval(self.const_nodes[name], 0)
        finally:
            self._const_in_progress.discard(name)
        self.const_cache[name] = value
        return value

    def _eval(self, node: ast.AST, depth: int) -> Any:
        if depth > _MAX_EVAL_DEPTH:
            raise _Unresolved("too deep")
        nxt = depth + 1
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.const_nodes:
                return self._const(node.id)
            if node.id in self.namespace:
                return self.namespace[node.id]
            raise _Unresolved(node.id)
        if isinstance(node, ast.Attribute):
            return self._eval_attribute(node, nxt)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            items = [self._eval(el, nxt) for el in node.elts]
            return items if isinstance(node, ast.List) else tuple(items) if isinstance(node, ast.Tuple) else set(items)
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise _Unresolved("dict unpack")
            return {self._eval(k, nxt): self._eval(v, nxt) for k, v in zip(node.keys, node.values, strict=True)}
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, nxt)
            if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)):
                return -operand
            if isinstance(node.op, ast.UAdd) and isinstance(operand, (int, float)):
                return +operand
            if isinstance(node.op, ast.Not):
                return not operand
            raise _Unresolved("unary")
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node, nxt)
        if isinstance(node, ast.JoinedStr):
            return self._eval_fstring(node, nxt)
        if isinstance(node, ast.Call):
            return self._eval_call(node, nxt)
        raise _Unresolved(type(node).__name__)

    def _eval_attribute(self, node: ast.Attribute, depth: int) -> Any:
        base = self._eval(node.value, depth)
        if isinstance(base, (str, int, float, list, tuple, dict, set)) or base is None:
            raise _Unresolved("attribute of plain value")
        if not hasattr(base, node.attr):
            public = [n for n in dir(base) if not n.startswith("_")]
            dotted = _dotted_name(node) or node.attr
            self.error(
                "V025",
                f"'{dotted}' does not exist in the SDK.",
                node,
                _suggest(node.attr, public),
            )
            raise _Unresolved(dotted)
        return getattr(base, node.attr)

    def _eval_binop(self, node: ast.BinOp, depth: int) -> Any:
        op = _BINARY_OPERATORS.get(type(node.op))
        if op is None:
            raise _Unresolved("operator")
        left = self._eval(node.left, depth)
        right = self._eval(node.right, depth)
        numbers = (int, float)
        if isinstance(left, numbers) and isinstance(right, numbers) and not isinstance(left, bool):
            if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1e6):
                raise _Unresolved("large power")
            try:
                return op(left, right)
            except (ArithmeticError, ValueError) as exc:
                raise _Unresolved("arithmetic") from exc
        if isinstance(node.op, ast.Add) and type(left) is type(right) and isinstance(left, (str, list, tuple)):
            return left + right
        raise _Unresolved("operands")

    def _eval_fstring(self, node: ast.JoinedStr, depth: int) -> str:
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue) and piece.format_spec is None and piece.conversion == -1:
                value = self._eval(piece.value, depth)
                if isinstance(value, (str, int, float, Enum)):
                    parts.append(str(value.value if isinstance(value, Enum) else value))
                else:
                    raise _Unresolved("fstring value")
            else:
                raise _Unresolved("fstring")
        return "".join(parts)

    def _eval_call(self, node: ast.Call, depth: int) -> Any:
        if isinstance(node.func, ast.Name) and node.func.id == "range" and node.func.id not in self.namespace:
            args = [self._eval(a, depth) for a in node.args]
            if node.keywords or not args or not all(isinstance(a, int) for a in args):
                raise _Unresolved("range")
            return list(range(*args))
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_BUILTINS and node.func.id not in self.namespace:
            if node.func.id in self.const_nodes:
                raise _Unresolved("shadowed builtin")
            args = [self._eval(a, depth) for a in node.args]
            kwargs = {kw.arg: self._eval(kw.value, depth) for kw in node.keywords if kw.arg}
            if len(kwargs) != len(node.keywords):
                raise _Unresolved("kwargs unpack")
            try:
                return _SAFE_BUILTINS[node.func.id](*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                raise _Unresolved("builtin call") from exc
        callee = self._eval(node.func, depth)
        if not (
            isinstance(callee, type)
            and (issubclass(callee, BaseModel) or issubclass(callee, Enum))
            and getattr(callee, "__module__", "").startswith("hamilton_venus")
        ):
            raise _Unresolved("call")
        args = [self._eval(a, depth) for a in node.args]
        kwargs = {kw.arg: self._eval(kw.value, depth) for kw in node.keywords if kw.arg}
        if len(kwargs) != len(node.keywords):
            raise _Unresolved("kwargs unpack")
        try:
            return callee(*args, **kwargs)
        except ValidationError as exc:
            self.error("V023", f"Invalid {callee.__name__}(...): {_first_pydantic_message(exc)}", node)
        except (TypeError, ValueError) as exc:
            self.error("V023", f"Invalid {callee.__name__}(...): {exc}", node)
        raise _Unresolved(callee.__name__)

    def _try_eval(self, node: ast.AST) -> tuple[bool, Any]:
        try:
            return True, self._eval(node, 0)
        except _Unresolved:
            return False, None
        except Exception:  # noqa: BLE001 - anything odd while evaluating means "cannot tell", not a finding
            return False, None

    # -- clients -------------------------------------------------------------------------

    def _client_class_for(self, node: ast.AST) -> type | None:
        """The client class *node* (the callee of a call, or an annotation) refers to."""
        if isinstance(node, (ast.Name, ast.Attribute)):
            ok, value = self._try_eval(node)
            if ok and isinstance(value, type) and value.__name__ in _CLIENT_CLASS_NAMES:
                return value
        return None

    def _find_clients(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            call: ast.Call | None = None
            var: str | None = None
            if isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
                call = node.context_expr
                if isinstance(node.optional_vars, ast.Name):
                    var = node.optional_vars.id
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and len(node.targets) == 1:
                call = node.value
                if isinstance(node.targets[0], ast.Name):
                    var = node.targets[0].id
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    cls = self._client_class_for(arg.annotation) if arg.annotation is not None else None
                    if cls is not None:
                        self.client_vars[arg.arg] = cls
            if call is None:
                continue
            cls = self._client_class_for(call.func)
            if cls is None:
                continue
            if var:
                self.client_vars[var] = cls
            self._check_constructor(call, cls, var)

    def _check_constructor(self, call: ast.Call, cls: type, var: str | None) -> None:
        signature = inspect.signature(cls.__init__)
        params = {name: p for name, p in signature.parameters.items() if name != "self"}
        accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        simulate_literal: bool | None = None
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            if keyword.arg not in params and not accepts_kwargs:
                self.error(
                    "V022",
                    f"{cls.__name__}() has no parameter '{keyword.arg}'.",
                    keyword.value,
                    _suggest(keyword.arg, params),
                )
                continue
            if keyword.arg == "simulate":
                ok, value = self._try_eval(keyword.value)
                if ok and isinstance(value, bool):
                    simulate_literal = value
                    if value is False:
                        self.warning(
                            "W033",
                            "simulate=False is hard-coded; the run's simulate setting overrides it when the script is run.",
                            keyword.value,
                        )
            if keyword.arg in ("deck_name",):
                self.loads_deck = True
        refused = instrument_guard.wrong_client_message(cls.__name__)
        if refused:
            self.error("V028", refused, call)
        self.clients.append(
            {
                "variable": var,
                "class": cls.__name__,
                "line": call.lineno,
                "simulate_literal": simulate_literal,
            }
        )

    # -- calls ---------------------------------------------------------------------------

    def _catalog_for(self, cls: type) -> dict[str, Any]:
        from hamilton_venus.models import InstrumentType

        from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT

        key = InstrumentType.Vantage if cls.__name__ == "VantageClient" else InstrumentType.STAR
        return CATALOG_BY_INSTRUMENT[key]

    def _check_calls(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in self.client_vars:
                self._check_client_call(node, self.client_vars[base.id], node.func.attr)

    def _check_client_call(self, call: ast.Call, cls: type, method: str) -> None:
        catalog = self._catalog_for(cls)
        spec = catalog.get(method)
        if spec is None:
            if hasattr(cls, method):
                self.unchecked_commands.add(method)
                self._note_deck_loading(method)
                return
            candidates = [*catalog, *(n for n in dir(cls) if not n.startswith("_"))]
            self.error(
                "V021",
                f"{cls.__name__} has no command '{method}'.",
                call,
                _suggest(method, candidates),
            )
            return

        self.commands_used.setdefault(method, []).append(call.lineno)
        self._note_deck_loading(method)
        params = spec.params
        names = [p.name for p in params]
        has_star = any(isinstance(a, ast.Starred) for a in call.args) or any(kw.arg is None for kw in call.keywords)

        provided: dict[str, ast.expr] = {}
        if len(call.args) > len(params) and not any(isinstance(a, ast.Starred) for a in call.args):
            self.error(
                "V022",
                f"{method}() takes at most {len(params)} argument(s) but {len(call.args)} were given.",
                call,
            )
        for arg_node, param in zip(call.args, params, strict=False):
            if not isinstance(arg_node, ast.Starred):
                provided[param.name] = arg_node
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            if keyword.arg not in names:
                self.error(
                    "V022",
                    f"{method}() has no parameter '{keyword.arg}'.",
                    keyword.value,
                    _suggest(keyword.arg, names) or f"valid parameters: {', '.join(names)}",
                )
                continue
            if keyword.arg in provided:
                self.error("V022", f"{method}() got multiple values for '{keyword.arg}'.", keyword.value)
            provided[keyword.arg] = keyword.value

        if not has_star:
            missing = [p.name for p in params if p.required and p.name not in provided]
            if missing:
                self.error("V022", f"{method}() is missing required argument(s): {', '.join(missing)}.", call)
            if method.startswith("aspirate") and "settings" in provided:
                ok, value = self._try_eval(provided["settings"])
                if ok:
                    self._check_aspirate_settings(method, value, call)
            if method.startswith(("aspirate", "dispense")) and "settings" in names and "settings" not in provided:
                self.warning(
                    "W036",
                    f"{method}() has no settings=, so it runs on the default settings (LLD off, fixed height, "
                    "no mixing). Build the settings for this liquid and labware and pass them.",
                    call,
                )

        # Commands that put a labware type on the deck take a labware_definition; add_reagent and
        # other compound commands that merely start with "add_" do not.
        add_call = "labware_definition" in names
        defines_id = False
        for name, arg_node in provided.items():
            param = next(p for p in params if p.name == name)
            ok, value = self._try_eval(arg_node)
            if not ok:
                self.unverified_args += 1
                continue
            self.checked_args += 1
            if name == "channels" and isinstance(value, (list, tuple)) and len(value) == 0:
                self.error(
                    "V026",
                    "channels must not be empty: omit 'channels' to use the default channels.",
                    arg_node,
                )
                continue
            self._validate_value(method, param, value, arg_node)
            self._check_string_shape(method, name, value, arg_node)
            if add_call and name in _ID_DEFINING_PARAMS and isinstance(value, str):
                self.added_labware.add(value)
                defines_id = True
            if name in _SELECTOR_PARAMS and not (add_call and name in _ID_DEFINING_PARAMS):
                self._note_used_labware(value, arg_node)
        if add_call and not defines_id:
            # VENUS names this labware itself, so later references to it cannot be checked.
            self.adds_without_id += 1

    def _check_aspirate_settings(self, method: str, settings: Any, node: ast.AST) -> None:
        """Liquid following without LLD starts at the fixed height and then follows further
        down, so it runs into the bottom: VENUS stops with an insufficient liquid level error."""
        following = getattr(settings, "liquid_following", False)
        lld = [getattr(settings, name, None) for name in ("capacitive_lld", "pressure_lld")]

        def on(value: Any) -> bool:
            values = value if isinstance(value, (list, tuple)) else [value]
            return any(v is not None and int(getattr(v, "value", v)) != 0 for v in values)

        if on(following) and not any(on(v) for v in lld):
            self.warning(
                "W037",
                f"{method}(): liquid_following is on but LLD is off, so the tip follows down from the "
                "fixed height and hits the bottom (insufficient liquid level). From a trough or a "
                "container with an unknown level use capacitive_lld with submerge_depth and liquid "
                "following; at a fixed height turn liquid_following off.",
                node,
            )

    def _validate_value(self, method: str, param: Any, value: Any, node: ast.AST) -> None:
        if param.annotation is inspect.Signature.empty:
            return
        try:
            adapter = param.type_adapter or TypeAdapter(param.annotation)
            adapter.validate_python(value)
        except ValidationError as exc:
            self.error("V023", f"{method}(): invalid value for '{param.name}': {_first_pydantic_message(exc)}", node)
        except Exception:  # noqa: BLE001 - an adapter that cannot be built is not the script's fault
            return

    def _check_string_shape(self, method: str, name: str, value: Any, node: ast.AST) -> None:
        """Catch text that is well-formed Python but almost certainly not what was meant: a
        value wrapped in its own literal quote characters, and position selectors that do not
        parse. Well/row/column *ranges* are not checked here: the labware's real size is only
        known once it is on the deck."""
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if not isinstance(item, str):
                continue
            if len(item) >= 2 and item[0] == item[-1] and item[0] in "\"'":
                self.warning(
                    "W034",
                    f"{method}(): '{name}' contains literal quote characters ({item!r}); "
                    "they are sent to VENUS as part of the value.",
                    node,
                )
            if name in _SELECTOR_PARAMS and "@" in item:
                try:
                    from hamilton_venus.models import LabwareLayoutSpec, normalize_positions

                    normalize_positions(item, get_spec=lambda _labware: LabwareLayoutSpec(rows=32, cols=48))
                except ValueError as exc:
                    self.error("V027", f"{method}(): invalid position selector {item!r}: {exc}", node)
                except Exception:  # noqa: BLE001 - only a clear ValueError is the script's fault
                    continue

    def _note_deck_loading(self, method: str) -> None:
        if "load" in method and "deck" in method:
            self.loads_deck = True

    def _note_used_labware(self, value: Any, node: ast.AST) -> None:
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if isinstance(item, str) and item.strip():
                labware = item.partition("@")[0].strip()
                if labware:
                    self.used_labware.setdefault(labware, getattr(node, "lineno", 0))

    # -- wrap-up -------------------------------------------------------------------------

    def _finish(self) -> None:
        if not self.clients:
            self.warning("W032", "No StarClient/VantageClient is created in this script, so it will not drive an instrument.")
        pickups = sorted(line for name, lines in self.commands_used.items() if name.startswith("tip_pick") for line in lines)
        if pickups and not any(name in self.commands_used for name in _TIP_COUNTER_SETUP):
            self.warning(
                "W035",
                "Tips are picked up but the tip counters are never set up: after adding the tip racks, call "
                "tip_pool_reset_tip_counter in simulation and tip_pool_show_tip_counters on the instrument "
                "(if star.simulate: ... else: ...).",
                ast.Pass(lineno=pickups[0], col_offset=0),
            )
        if not self.loads_deck and self.adds_without_id == 0:
            for labware, line in sorted(self.used_labware.items(), key=lambda kv: kv[1]):
                if labware not in self.added_labware:
                    self.report.warnings.append(
                        Issue(
                            "W030",
                            "warning",
                            f"Labware '{labware}' is used but no add_* call in this script defines it.",
                            line,
                            None,
                            _suggest(labware, self.added_labware) if self.added_labware else None,
                        )
                    )
        self.report.errors.sort(key=lambda i: (i.line or 0, i.col or 0))
        self.report.warnings.sort(key=lambda i: (i.line or 0, i.col or 0))
        self.report.info = {
            "clients": self.clients,
            "commands_used": {name: lines for name, lines in sorted(self.commands_used.items())},
            "unchecked_commands": sorted(self.unchecked_commands),
            "labware": {"added": sorted(self.added_labware), "used": sorted(self.used_labware)},
            "arguments": {"checked": self.checked_args, "unverified": self.unverified_args},
            "imports": sorted(self.imports),
        }


def validate_source(source: str, filename: str = "<script>") -> ValidationReport:
    """Statically validate a script's text. Never runs it."""
    return _Validator(source, filename).run()


def validate_bytes(data: bytes, filename: str = "<script>") -> ValidationReport:
    """Validate a script as stored on disk. The report's ``sha256`` is of these exact bytes (a
    UTF-8 BOM included), which is what the script store compares to decide whether a validation
    is still current."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        report = ValidationReport(sha256=sha256_of(data))
        report.errors.append(Issue("V001", "error", f"Not valid UTF-8 text: {exc.reason}", None, None))
        return report
    report = _Validator(text, filename).run()
    report.sha256 = sha256_of(data)
    return report
