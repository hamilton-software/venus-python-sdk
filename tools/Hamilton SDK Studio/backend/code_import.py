"""Import Script: an SDK script -> cards and variables (the reverse of Generate Script).

Reads the script's syntax tree; nothing is executed. `<client>.<command>(...)` calls become cards,
simple module-level constants (`VOLUME = 50`) become variables, and a later use of a constant
becomes a `{{variable}}` reference. Enum members and `hamilton_venus.models` constructors
(`AspirateSettings(...)`) become the plain values the cards store.

Control flow becomes cards too: `for x in range(1, n + 1)` is Repeat, `for x in [..]` is For Each in
List, `while` and `if` / `else` are While and If, `break` / `continue`, `x = <expression>` is Set
Variable and `time.sleep(n)` is Wait. Anything that cannot be worked out without running code
(computed values, unknown commands, loops over anything else) is skipped or inlined with a warning,
never guessed.
"""

from __future__ import annotations

import ast
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend import expr, flow, returns as returns_mod, variables as variables_mod

_RESERVED_CONSTANTS = {"SIMULATE"}
_LOOP_GUARD_PREFIX = "_loops_"  # the counter Generate Script adds to every While


class _Unresolved:
    """An argument expression we cannot (or will not) work out statically."""


UNRESOLVED = _Unresolved()


def _safe_namespace() -> dict[str, Any]:
    """Names a script may use in values: the labware/liquid-class catalogs, enums and models."""
    import hamilton_venus.models as models
    from hamilton_venus.catalog import LABWARE, LIQUID_CLASSES
    from hamilton_venus.models import enums

    names: dict[str, Any] = {"LABWARE": LABWARE, "LIQUID_CLASSES": LIQUID_CLASSES}
    names.update({n: getattr(enums, n) for n in getattr(enums, "__all__", [])})
    names.update({n: getattr(models, n) for n in dir(models) if isinstance(getattr(models, n), type) and issubclass(getattr(models, n), BaseModel)})
    return names


def _known_commands() -> set[str]:
    from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT

    return {name for catalog in CATALOG_BY_INSTRUMENT.values() for name in catalog}


def _param_order(command: str) -> list[str]:
    from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT

    for catalog in CATALOG_BY_INSTRUMENT.values():
        if command in catalog:
            return [p.name for p in catalog[command].params]
    return []


def _step(command: str, params: dict[str, Any], children: list[dict[str, Any]] | None = None, else_children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {"id": "s" + uuid.uuid4().hex[:10], "kind": "command", "command": command, "params": params, "enabled": True}
    if children is not None:
        card["children"] = children
    if else_children is not None:
        card["else_children"] = else_children
    return card


class _Importer:
    def __init__(self) -> None:
        self.names = _safe_namespace()
        self.commands = _known_commands()
        self.client_vars: set[str] = {"star", "hhc", "odtc", "tec", "tilt", "media_fill"}
        self.constants: dict[str, Any] = {}  # script constant -> typed value (becomes a variable)
        self.models: dict[str, Any] = {}  # script variable holding a settings object -> its dict
        self.warnings: list[str] = []
        self.caps: list[list[int]] = []  # While guard limits seen while importing each loop body
        self.runtime_names: set[str] = set()  # loop variables and Set Variable targets seen so far

    def warn(self, node: ast.AST, text: str) -> None:
        self.warnings.append(f"Line {getattr(node, 'lineno', '?')}: {text}")

    # -- values -----------------------------------------------------------------------------------

    def value(self, node: ast.expr) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, SyntaxError, TypeError):
            pass
        if isinstance(node, ast.Name):
            if node.id in self.constants or node.id in self.runtime_names:
                return "{{" + node.id + "}}"
            if node.id in self.models:
                return self.models[node.id]
            return UNRESOLVED
        if isinstance(node, ast.JoinedStr):
            return self._fstring(node)
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [self.value(e) for e in node.elts]
            return UNRESOLVED if any(i is UNRESOLVED for i in items) else items
        if isinstance(node, ast.Dict) and all(k is not None for k in node.keys):
            pairs = [(self.value(k), self.value(v)) for k, v in zip(node.keys, node.values)]
            return UNRESOLVED if any(UNRESOLVED in (k, v) for k, v in pairs) else dict(pairs)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("str", "int", "float", "bool"):
            inner = self.value(node.args[0]) if len(node.args) == 1 and not node.keywords else UNRESOLVED
            if isinstance(inner, str) and variables_mod.REF.fullmatch(inner) and "|" not in inner:  # str(X) is a {{X|str}} conversion
                return inner[:-2] + "|" + node.func.id + "}}"
            return UNRESOLVED
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.names:
            return self._model(node)
        if _is_dotted_name(node):
            return self._lookup(node)
        return UNRESOLVED

    def _lookup(self, node: ast.expr) -> Any:
        try:
            found = eval(compile(ast.Expression(body=node), "<import>", "eval"), {"__builtins__": {}}, self.names)  # noqa: S307 - dotted names only
        except Exception:  # noqa: BLE001
            return UNRESOLVED
        return found.value if isinstance(found, Enum) else found if isinstance(found, (str, int, float, bool)) else UNRESOLVED

    def _model(self, node: ast.Call) -> Any:
        if node.args:
            return UNRESOLVED
        data: dict[str, Any] = {}
        for keyword in node.keywords:
            item = self.value(keyword.value) if keyword.arg else UNRESOLVED
            if item is UNRESOLVED:
                return UNRESOLVED
            data[keyword.arg] = item
        return data

    def _fstring(self, node: ast.JoinedStr) -> Any:
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name) and piece.format_spec is None and (
                    piece.value.id in self.constants or piece.value.id in self.runtime_names):
                parts.append("{{" + piece.value.id + "}}")
            else:
                return UNRESOLVED
        return "".join(parts)

    def expression(self, node: ast.expr, where: ast.AST) -> str:
        """Source text of a condition / value for a card; `response` (the previous command's result) is `last`."""
        class Rename(ast.NodeTransformer):
            def visit_Name(inner, name: ast.Name) -> ast.AST:  # noqa: N805
                if name.id == "response" and "response" not in self.constants:
                    return ast.copy_location(ast.Name(id="last", ctx=ast.Load()), name)
                return name

        text = ast.unparse(Rename().visit(ast.parse(ast.unparse(node), mode="eval")).body)
        try:
            expr.parse(text)
        except expr.ExprError as exc:
            self.warn(where, f"'{text}' is outside the condition language ({exc}); fix it on the card.")
        return text

    # -- statements ---------------------------------------------------------------------------------

    def collect(self, node: ast.Assign) -> bool:
        """Register a module-level constant or settings object; True when the statement was one."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = _literal_or_unresolved(node.value)
            if (node.col_offset == 0 and name not in _RESERVED_CONSTANTS and value is not UNRESOLVED and _is_variable_value(value)
                    and variables_mod.REF.fullmatch("{{" + name + "}}")):
                self.constants[name] = value
                return True
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in self.names:
                modeled = self._model(node.value)
                if modeled is not UNRESOLVED:
                    self.models[name] = modeled
                    return True
        return False

    def block(self, body: list[ast.stmt]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for statement in body:
            kept = _response_assignment(statement)  # x = response.return_parameters.attr: keep that result in a variable
            if kept and cards and cards[-1]["command"] not in flow.CONTROL:
                name, attributes = kept
                path = returns_mod.path_for(_returns_of(cards[-1]["command"]), attributes)
                if path is not None:
                    cards[-1].setdefault("saves", []).append({"name": name, "field": path})
                    self.runtime_names.add(name)
                else:
                    self.warn(statement, f"could not match response.{'.'.join(attributes)} to a value {cards[-1]['command']} returns; skipped.")
                continue
            cards += self.statement(statement)
        return cards

    def statement(self, node: ast.stmt) -> list[dict[str, Any]]:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            return self.call(node.value)
        if isinstance(node, ast.Assign):
            return self.assign(node)
        if isinstance(node, ast.AugAssign):
            return self.augassign(node)
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    self.client_vars.add(item.optional_vars.id)
            return self.block(node.body)
        if isinstance(node, ast.Try):
            return self.block(node.body) + self.block(node.finalbody)
        if isinstance(node, ast.For):
            return self.for_loop(node)
        if isinstance(node, ast.While):
            return self.while_loop(node)
        if isinstance(node, ast.If):
            return self.if_block(node)
        if isinstance(node, ast.Break):
            return [_step(flow.BREAK, {})]
        if isinstance(node, ast.Continue):
            return [_step(flow.CONTINUE, {})]
        return []

    def call(self, node: ast.Call) -> list[dict[str, Any]]:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in self.client_vars:
                return self._command(func.attr, node)
            if func.value.id == "time" and func.attr == "sleep" and len(node.args) == 1:
                seconds = self.value(node.args[0])
                if seconds is UNRESOLVED:
                    self.warn(node, "could not work out the number of seconds in time.sleep(...); skipped.")
                    return []
                return [_step(flow.WAIT, {"seconds": seconds})]
        return []

    def assign(self, node: ast.Assign) -> list[dict[str, Any]]:
        if self.collect(node):
            return []
        target = node.targets[0] if len(node.targets) == 1 else None
        if not isinstance(target, ast.Name):
            return []
        if target.id in _RESERVED_CONSTANTS or target.id.startswith(_LOOP_GUARD_PREFIX) or target.id == "response" and isinstance(node.value, ast.Constant):
            return []
        if isinstance(node.value, ast.Call):  # response = star.command(...)
            cards = self.call(node.value)
            if cards or (isinstance(node.value.func, ast.Attribute) and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id in self.client_vars):
                return cards
            return []
        if target.id == "response":
            return []
        if not variables_mod.REF.fullmatch("{{" + target.id + "}}"):
            return []
        self.runtime_names.add(target.id)
        return [_step(flow.SET_VARIABLE, {"name": target.id, "expression": self.expression(node.value, node)})]

    def augassign(self, node: ast.AugAssign) -> list[dict[str, Any]]:
        if not isinstance(node.target, ast.Name) or node.target.id.startswith(_LOOP_GUARD_PREFIX):
            return []
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            self.warn(node, "this operator is not supported in a Set Variable card; skipped.")
            return []
        self.runtime_names.add(node.target.id)
        combined = ast.BinOp(left=ast.Name(id=node.target.id, ctx=ast.Load()), op=node.op, right=node.value)
        return [_step(flow.SET_VARIABLE, {"name": node.target.id, "expression": self.expression(combined, node)})]

    def if_block(self, node: ast.If) -> list[dict[str, Any]]:
        guard = _loop_guard_cap(node)
        if guard is not None:  # Generate Script's loop limit, which the While card's own limit replaces
            if self.caps:
                self.caps[-1].append(guard)
            return []
        return [_step(flow.IF, {"condition": self.expression(node.test, node)}, self.block(node.body), self.block(node.orelse))]

    def while_loop(self, node: ast.While) -> list[dict[str, Any]]:
        self.caps.append([])
        children = self.block(node.body)
        caps = self.caps.pop()
        params: dict[str, Any] = {"condition": self.expression(node.test, node)}
        if caps:
            params["max_iterations"] = caps[0]
        return [_step(flow.WHILE, params, children)]

    def for_loop(self, node: ast.For) -> list[dict[str, Any]]:
        target, source = node.target, node.iter
        index_name = None
        if isinstance(source, ast.Call) and isinstance(source.func, ast.Name) and source.func.id == "enumerate" and isinstance(target, ast.Tuple) and len(target.elts) == 2:
            if isinstance(target.elts[0], ast.Name) and isinstance(target.elts[1], ast.Name) and source.args:
                index_name, target, source = target.elts[0].id, target.elts[1], source.args[0]
        if not isinstance(target, ast.Name):
            return self._inline(node, "this loop's variable is not a plain name")
        name = target.id
        self.runtime_names.update({name, index_name} if index_name else {name})
        body = self.block(node.body)
        if isinstance(source, ast.Call) and isinstance(source.func, ast.Name) and source.func.id == "range":
            count = self._range_count(source, node)
            if count is None:
                return self._inline(node, "only range(n) and range(1, n + 1) loops become Repeat cards", body)
            if index_name:
                self.warn(node, f"the enumerate index {index_name} is not available in a Repeat card; use the counter {name}.")
            return [_step(flow.REPEAT, {"count": count, "variable": name}, body)]
        items = self.value(source) if not isinstance(source, ast.Constant) else list(str(source.value))
        if items is UNRESOLVED or not isinstance(items, (list, str)):
            return self._inline(node, "this loop iterates over something that cannot be worked out without running the script", body)
        if index_name and index_name != "index":
            self.warn(node, f"the loop index is always called 'index' in a For Each card, not {index_name}.")
        return [_step(flow.FOR_LIST, {"items": items, "variable": name}, body)]

    def _range_count(self, call: ast.Call, node: ast.AST) -> Any:
        args = call.args
        if len(args) == 1:  # range(n): the script counts from 0, a Repeat card from 1
            count = self.value(args[0])
            if count is UNRESOLVED:
                return None
            self.warn(node, "range(n) counts from 0 but a Repeat card counts from 1; adjust the expressions that use the counter.")
            return count
        if len(args) == 2 and isinstance(args[0], ast.Constant) and args[0].value == 1:
            stop = args[1]
            if isinstance(stop, ast.BinOp) and isinstance(stop.op, ast.Add) and isinstance(stop.right, ast.Constant) and stop.right.value == 1:
                count = self.value(stop.left)
                return None if count is UNRESOLVED else count
            if isinstance(stop, ast.Constant) and isinstance(stop.value, int):
                return stop.value - 1
        return None

    def _inline(self, node: ast.AST, why: str, body: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        self.warn(node, f"{why}, so the cards inside are imported once, outside any loop.")
        return body if body is not None else self.block(node.body)  # type: ignore[attr-defined]

    def _command(self, method: str, node: ast.Call) -> list[dict[str, Any]]:
        if method not in self.commands:
            self.warn(node, f"{method}(...) is not an SDK command here; skipped.")
            return []
        order = _param_order(method)
        params: dict[str, Any] = {}
        for index, arg in enumerate(node.args):
            if index >= len(order):
                self.warn(node, f"too many positional arguments to {method}(...); extra ignored.")
                break
            self._param(params, order[index], arg, method, node)
        for keyword in node.keywords:
            if keyword.arg is None:
                self.warn(node, f"**kwargs in {method}(...) cannot be imported; skipped.")
                continue
            self._param(params, keyword.arg, keyword.value, method, node)
        return [_step(method, params)]

    def _param(self, params: dict[str, Any], name: str, expr_node: ast.expr, method: str, node: ast.Call) -> None:
        value = self.value(expr_node)
        if value is UNRESOLVED:
            self.warn(node, f"could not work out '{name}' of {method}(...) without running the script; left unset.")
            return
        params[name] = value


def _response_assignment(node: ast.stmt) -> tuple[str, list[str]] | None:
    """(variable, attributes after `response`) for `x = response.a.b`, else None."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
        return None
    attributes: list[str] = []
    value = node.value
    while isinstance(value, ast.Attribute):
        attributes.insert(0, value.attr)
        value = value.value
    if isinstance(value, ast.Name) and value.id == "response" and node.targets[0].id != "response":
        return node.targets[0].id, attributes
    return None


def _returns_of(command: str) -> dict[str, Any] | None:
    from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT

    for catalog in CATALOG_BY_INSTRUMENT.values():
        if command in catalog:
            return returns_mod.describe(catalog[command].return_annotation)
    return None


def _loop_guard_cap(node: ast.If) -> int | None:
    """The limit in Generate Script's `if _loops_n > cap: raise ...` guard, else None."""
    test = node.test
    if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id.startswith(_LOOP_GUARD_PREFIX)
            and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant) and isinstance(test.comparators[0].value, int)
            and len(node.body) == 1 and isinstance(node.body[0], ast.Raise)):
        return test.comparators[0].value
    return None


def _is_dotted_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) or (isinstance(node, ast.Attribute) and _is_dotted_name(node.value))


def _literal_or_unresolved(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return UNRESOLVED


def _is_variable_value(value: Any) -> bool:
    if isinstance(value, (bool, int, float, str)):
        return True
    return isinstance(value, (list, tuple)) and all(isinstance(v, (bool, int, float, str)) for v in value)


def _variable_for(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"name": name, "type": "bool", "value": value, "prompt": False}
    if isinstance(value, (int, float)):
        return {"name": name, "type": "number", "value": value, "prompt": False}
    if isinstance(value, (list, tuple)):
        return {"name": name, "type": "list", "value": list(value), "prompt": False}
    return {"name": name, "type": "string", "value": value, "prompt": False}


def parse_script(source: str) -> dict[str, Any]:
    """{"steps": [...], "variables": [...], "warnings": [...]} for the script text."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"steps": [], "variables": [], "warnings": [f"Could not parse the script: {exc}"]}
    importer = _Importer()
    # Constants and settings objects first, so a call can use one however the file is ordered.
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            importer.collect(statement)
    steps = importer.block(tree.body)

    used: set[str] = set()
    for step, _ in flow.walk(steps):
        used |= variables_mod.find_refs(step["params"])
        used |= {n for key in ("condition", "expression") if (text := step["params"].get(key)) for n in _safe_names(str(text))}
    variables = [_variable_for(n, v) for n, v in importer.constants.items()]
    unused = [v["name"] for v in variables if v["name"] not in used]
    warnings = list(importer.warnings)
    if not steps:
        warnings.append("No SDK command calls (star.<command>(...), hhc.<command>(...)) were found in this script.")
    if unused:
        warnings.append("Constants not used by any card were imported as variables anyway: " + ", ".join(unused) + ".")
    return {"steps": steps, "variables": variables, "warnings": warnings}


def _safe_names(text: str) -> set[str]:
    try:
        return expr.names_in(text)
    except expr.ExprError:
        return set()
