"""Generate Script: a flow -> a standalone, runnable Python script for the SDK.

The script follows the authoring template (`with StarClient(...) as star:` inside try/except
VenusError, real keyword arguments, `SIMULATE` and one constant per flow variable at the top).
Values are rendered from each parameter's *SDK annotation*, so an enum choice becomes
`WellOrder.COL_ASC` and a settings dict becomes `AspirateSettings(...)` -- the same objects the
script validator checks -- instead of loose strings and dicts. A field that references a variable
becomes the variable's constant (or an f-string when mixed with text).

Pure-Python device commands (hhc_*, odtc_*, ...) are not instrument methods: each gets its own
client in the same `with`, as in the SDK's common patterns. A disabled card is kept as a comment.
"""

from __future__ import annotations

import ast
import json
import keyword
import re
import types
import typing
from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend import expr, flow, variables as variables_mod
from backend.typeinfo import candidates
from backend.command_catalog import STUDIO_CONNECT

_INSTRUMENT_VAR = "star"
_WRAP_AT = 100


# -- annotation helpers ---------------------------------------------------------------------------


def _element_annotation(cands: list[Any]) -> Any:
    for candidate in cands:
        if typing.get_origin(candidate) in (list, tuple, set, frozenset):
            args = typing.get_args(candidate)
            return args[0] if args else None
    return None


def _enum_member(enum_cls: type[Enum], value: Any) -> Enum | None:
    text = str(value)
    for member in enum_cls:
        if member.value == value or str(member.value) == text or member.name.lower() == text.lower():
            return member
    return None


# -- the script being built ----------------------------------------------------------------------


class _Script:
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names  # variable name -> constant identifier
        self.text_names: set[str] = set()  # names known to hold text, which need no str() for a text parameter
        self.imports: dict[str, set[str]] = {}
        self.warnings: list[str] = []

    def import_class(self, cls: type) -> None:
        module = cls.__module__
        if issubclass(cls, Enum):
            module = "hamilton_venus.models.enums"
        else:
            import hamilton_venus.models as public

            if hasattr(public, cls.__name__):
                module = "hamilton_venus.models"
        self.imports.setdefault(module, set()).add(cls.__name__)

    # -- values -----------------------------------------------------------------------------------

    def reference(self, text: str) -> str:
        """Source for a string containing {{variables}}: the constant itself when the whole string is
        one reference, otherwise an f-string."""
        whole = variables_mod.REF.fullmatch(text.strip())
        if whole:
            const = self._const(whole.group(1), text)
            return _convert_source(const, whole.group(2)) if whole.group(1) in self.names else const
        pieces: list[str] = []
        position = 0
        for match in variables_mod.REF.finditer(text):
            pieces.append(_fstring_text(text[position : match.start()]))
            const = self._const(match.group(1), None)
            pieces.append("{" + _convert_source(const, match.group(2)) + "}" if const else _fstring_text(match.group(0)))
            position = match.end()
        pieces.append(_fstring_text(text[position:]))
        return 'f"' + "".join(pieces) + '"'

    def _const(self, name: str, fallback: str | None) -> str:
        if name in self.names:
            return self.names[name]
        self.warnings.append(f"Variable {{{{{name}}}}} is not defined; it is left as text in the script.")
        return py_literal(fallback) if fallback is not None else ""

    def value(self, value: Any, annotation: Any = None) -> str:
        if isinstance(value, str) and variables_mod.REF.search(value):
            source = self.reference(value)
            whole = variables_mod.REF.fullmatch(value.strip())
            cands = candidates(annotation)
            if whole and not whole.group(2) and whole.group(1) in self.names and whole.group(1) not in self.text_names and cands and all(c is str for c in cands):
                source = f"str({source})"  # the same fitting the run does: a number into a text-only parameter
            return source
        cands = candidates(annotation)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            for candidate in cands:
                if isinstance(candidate, type) and issubclass(candidate, Enum):
                    member = _enum_member(candidate, value)
                    if member is not None:
                        self.import_class(candidate)
                        return f"{candidate.__name__}.{member.name}"
        if isinstance(value, dict):
            for candidate in cands:
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    return self._model(candidate, value)
            return "{" + ", ".join(f"{py_literal(k)}: {self.value(v)}" for k, v in value.items()) + "}"
        if isinstance(value, (list, tuple)):
            inner = _element_annotation(cands)
            return "[" + ", ".join(self.value(item, inner) for item in value) + "]"
        return py_literal(value)

    def _model(self, model: type[BaseModel], data: dict[str, Any]) -> str:
        self.import_class(model)
        by_key = {(info.alias or name): (name, info.annotation) for name, info in model.model_fields.items()}
        by_key.update({name: (name, info.annotation) for name, info in model.model_fields.items()})
        parts = []
        for key, item in data.items():
            name, annotation = by_key.get(key, (key, None))
            parts.append(f"{name}={self.value(item, annotation)}")
        return f"{model.__name__}({', '.join(parts)})"


def _convert_source(source: str, kind: str | None) -> str:
    """The Python for a {{name|kind}} conversion of an already-written value."""
    if kind is None or not source:
        return source
    if kind in ("str", "text"):
        return f"str({source})"
    if kind in ("int", "float", "bool"):
        return f"{kind}({source})"
    return f"list({source}) if isinstance({source}, (list, tuple)) else [{source}]"  # list


def py_literal(value: Any) -> str:
    """repr() with double-quoted strings, like the SDK's own scripts; lists and dicts recurse."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(py_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{py_literal(k)}: {py_literal(v)}" for k, v in value.items()) + "}"
    return repr(value)


def _fstring_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("{", "{{").replace("}", "}}").replace("\n", "\\n")


# -- rendering ---------------------------------------------------------------------------------------


def _spec_for(command: str, instrument_type: str) -> Any:
    from hamilton_venus.models import InstrumentType
    from hamilton_venus_mcp.catalog import CATALOG_BY_INSTRUMENT

    return CATALOG_BY_INSTRUMENT[InstrumentType(instrument_type)].get(command)


def _call_source(script: _Script, client: str, step: dict[str, Any], spec: Any) -> str:
    params = step.get("params", {})
    annotation_of = {p.name: p.annotation for p in spec.params} if spec is not None else {}
    order = [p.name for p in spec.params] if spec is not None else list(params)
    names = [n for n in order if n in params] + [n for n in params if n not in order]
    args = [f"{name}={script.value(params[name], annotation_of.get(name))}" for name in names]
    one_line = f"{client}.{step['command']}({', '.join(args)})"
    if len(one_line) <= _WRAP_AT or not args:
        return one_line
    return f"{client}.{step['command']}(\n" + "".join(f"    {arg},\n" for arg in args) + ")"


_RESERVED = {"star", "response", "time", "print", "range", "len", "min", "max", "abs", "round", "int", "float", "str", "bool", "sum",
             "VenusError", "SIMULATE", "hhc", "odtc", "tec", "tilt", "media_fill", "enumerate"}


def py_name(name: str) -> str:
    """A valid Python name for a loop or Set Variable name (kept as the person wrote it)."""
    base = re.sub(r"\W", "_", name) or "v"
    if base[0].isdigit():
        base = f"_{base}"
    return f"{base}_" if keyword.iskeyword(base) or base in _RESERVED else base


def _has_code(lines: list[str]) -> bool:
    return any(line.strip() and not line.strip().startswith("#") for line in lines)


class _Emitter:
    """Turns the card tree into indented source lines."""

    def __init__(self, script: _Script, steps: list[dict[str, Any]], instrument_type: str, command_label: Any, subflows: list[dict[str, Any]] | None = None) -> None:
        from hamilton_venus.standalone_devices import find_standalone_device

        self.script, self.instrument_type, self.command_label = script, instrument_type, command_label
        self.find_device = find_standalone_device
        self.subflow_list = subflows or []
        self.subflows = {str(s["name"]): s for s in self.subflow_list}
        self.numbers = flow.labels(steps)
        for sub in self.subflow_list:  # a subflow's cards are numbered as on its own tab
            self.numbers.update(flow.labels(sub.get("steps", [])))
        self.defs: dict[str, dict[str, Any]] = {}  # subflow name -> {"name": function name, "lines": body, "assigned": names}
        self._function_names: dict[str, str] = {}
        self._unsafe_memo: dict[str, bool] = {}
        everything = [*steps, *(s for sub in self.subflow_list for s in sub.get("steps", []))]
        self.needs_instrument = False
        self.devices: list[Any] = []
        self.uses_time = False
        self.uses_last = False
        self.loop_counters = 0
        self.prompt_names: list[str] = []
        refs = set().union(*(variables_mod.find_refs(s.get("params", {})) for s in flow.flat(everything))) if everything else set()
        for step in flow.flat(everything):
            text = step.get("params", {}).get("condition") or step.get("params", {}).get("expression")
            if text:
                try:
                    refs |= expr.names_in(str(text))
                except expr.ExprError:
                    pass
        self.uses_index = "index" in refs

    # -- subflows -------------------------------------------------------------------------------------

    def _unsafe(self, name: str) -> bool:
        """A subflow whose Break / Continue can leave it (they sit outside any loop of its own): in the app that
        ends the loop that called it, which a Python function cannot do, so such a subflow is written inline."""
        if name in self._unsafe_memo:
            return self._unsafe_memo[name]
        self._unsafe_memo[name] = False  # a loop of calls cannot happen (the flow is checked first); this just stops recursion

        def scan(items: list[dict[str, Any]], in_loop: bool) -> bool:
            for step in items:
                if not step.get("enabled", True):
                    continue
                command = step.get("command")
                if command in (flow.BREAK, flow.CONTINUE) and not in_loop:
                    return True
                if command == flow.CALL and not in_loop and str(step.get("params", {}).get("subflow", "")) in self.subflows \
                        and self._unsafe(str(step["params"]["subflow"])):
                    return True
                if command in flow.CONTAINERS and command != flow.CALL:
                    inside = in_loop or command in flow.LOOPS
                    if any(scan(lane, inside) for lane in flow.lanes(step)):
                        return True
            return False

        self._unsafe_memo[name] = scan(self.subflows[name].get("steps", []), False)
        return self._unsafe_memo[name]

    def _assigned(self, items: list[dict[str, Any]]) -> set[str]:
        """Script names the cards write (loop counters, Set Variable, kept results): a function declares them global."""
        found: set[str] = set()
        for step in flow.flat(items):
            found.update(self.script.names[n] for n in flow.loop_variables(step) if n in self.script.names)
            target = str(step.get("params", {}).get("subflow", "")) if step.get("command") == flow.CALL and step.get("enabled", True) else ""
            if target in self.subflows and self._unsafe(target):  # written inline here
                found |= self._assigned(self.subflows[target].get("steps", []))
        return found

    def _function(self, name: str) -> str:
        """The function a subflow is written as (defined once, however often it is called)."""
        if name in self._function_names:
            return self._function_names[name]
        taken = {*self.script.names.values(), *self._function_names.values(), "star", "response", "time", "SIMULATE"}
        base = py_name(re.sub(r"\W+", "_", name.strip().lower()).strip("_") or "subflow")
        function = base
        while function in taken:
            function += "_"
        self._function_names[name] = function
        steps = self.subflows[name].get("steps", [])
        lines = self.block(steps)  # callees register (and are stored) before this one
        self.defs[name] = {"name": function, "lines": lines, "assigned": self._assigned(steps)}
        return function

    # -- helpers --------------------------------------------------------------------------------------

    def title(self, step: dict[str, Any]) -> str:
        return (self.command_label(step["command"]) if self.command_label else None) or step["command"]

    def expression(self, text: Any) -> str:
        names = self.script.names

        class Rename(ast.NodeTransformer):
            def visit_Name(inner, node: ast.Name) -> ast.AST:  # noqa: N805
                if node.id == "last":
                    self.uses_last = True
                    return ast.copy_location(ast.Name(id="response", ctx=ast.Load()), node)
                if node.id in names:
                    return ast.copy_location(ast.Name(id=names[node.id], ctx=ast.Load()), node)
                self.script.warnings.append(f"The expression '{text}' uses {node.id}, which is not a variable or loop name.")
                return node

        try:
            return ast.unparse(Rename().visit(expr.parse(str(text))).body)
        except expr.ExprError as exc:
            self.script.warnings.append(f"Expression '{text}': {exc}")
            return "False"

    def count_source(self, value: Any) -> str:
        if isinstance(value, str) and variables_mod.REF.search(value):
            return f"range(1, {self.script.reference(value)} + 1)"
        try:
            return f"range(1, {int(value) + 1})"
        except (TypeError, ValueError):
            self.script.warnings.append(f"Repeat count {value!r} is not a number; using 1.")
            return "range(1, 2)"

    def indent(self, lines: list[str]) -> list[str]:
        while lines and not lines[-1]:  # a block's trailing blank line belongs after the block, not inside it
            lines = lines[:-1]
        if not _has_code(lines):  # only comments (every card disabled): Python still needs a statement
            lines = [*lines, "pass"]
        return [("    " + line) if line else line for line in lines] or ["    pass"]

    # -- cards ----------------------------------------------------------------------------------------

    def block(self, nodes: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for node in nodes:
            card = self.card(node)
            if not node.get("enabled", True):
                card = card[:1] + [f"# (skipped) {line}" if line else line for line in card[1:]]
            lines += card + [""]
        return lines

    def card(self, step: dict[str, Any]) -> list[str]:
        command, number = step["command"], self.numbers.get(step["id"], "?")
        header = f"# {number}. {self.title(step)}"
        params = step.get("params", {})
        enabled = step.get("enabled", True)
        names = self.script.names

        if command == STUDIO_CONNECT:
            self.needs_instrument = self.needs_instrument or enabled
            return [f"{header}: the client connects when the `with` block opens, so nothing to call here."]
        if command == flow.BREAK:
            return [header, "break"]
        if command == flow.CONTINUE:
            return [header, "continue"]
        if command == flow.SET_VARIABLE:
            return [header, f"{names[str(params.get('name', ''))]} = {self.expression(params.get('expression', ''))}"]
        if command == flow.WAIT:
            self.uses_time = True
            return [header, f"time.sleep({self.script.value(params.get('seconds', 0))})"]
        if command == flow.PROMPT:
            message = self.script.value(params.get("message", ""))
            store = params.get("store_in")
            note = f"{header}: a script cannot ask a person" + (f"; give {names[store]} its value in the constants at the top." if store else ".")
            if store and store not in self.prompt_names:
                self.prompt_names.append(store)
            return [note, f"print(\"PROMPT:\", {message})"]
        if command == flow.REPEAT:
            variable = names[flow.loop_variables(step)[0]]
            return [header, f"for {variable} in {self.count_source(params.get('count', 1))}:", *self.indent(self.block(step.get("children", [])))]
        if command == flow.FOR_LIST:
            return [header, *self._for_list(step)]
        if command == flow.FOR_PLATE:
            return [header, *self._for_plate(step)]
        if command == flow.WHILE:
            self.loop_counters += 1
            counter = f"_loops_{self.loop_counters}"
            cap = int(params.get("max_iterations") or flow.DEFAULT_WHILE_CAP)
            guard = [f"{counter} += 1", f"if {counter} > {cap}:", f'    raise RuntimeError("The loop on card {number} ran more than {cap} times")']
            body = self.block(step.get("children", []))
            return [header, f"{counter} = 0", f"while {self.expression(params.get('condition', 'False'))}:", *self.indent(guard + body)]
        if command == flow.CALL:
            name = str(params.get("subflow", ""))
            if name not in self.subflows:
                self.script.warnings.append(f"Card {number}: there is no subflow named '{name}'.")
                return [f"{header}: subflow '{' '.join(name.split())}' does not exist", "pass"]
            if self._unsafe(name):  # a Break / Continue inside it ends the caller's loop: written out here instead
                inner = flow.expand([step], self.subflow_list)[0].get("children", [])
                return [f"{header}: subflow '{' '.join(name.split())}' (written out here because it breaks out of the loop that calls it)", *self.block(inner)]
            return [f"{header}: subflow '{' '.join(name.split())}'", f"{self._function(name)}()"]
        if command == flow.IF:
            lines = [header, f"if {self.expression(params.get('condition', 'False'))}:", *self.indent(self.block(step.get("children", [])))]
            if step.get("else_children"):
                lines += ["else:", *self.indent(self.block(step["else_children"]))]
            return lines
        return [header, *self._sdk_call(step, enabled)]

    def _sdk_call(self, step: dict[str, Any], enabled: bool) -> list[str]:
        command = step["command"]
        device = self.find_device(command)
        client = device.prefix.rstrip("_") if device else _INSTRUMENT_VAR
        spec = _spec_for(command, self.instrument_type)
        if spec is None:
            self.script.warnings.append(f"Card {self.numbers.get(step['id'], '?')} ({command}) is not an SDK command on this instrument; left as a comment.")
            return [f"# (not available) {line}" for line in f"response = {_call_source(self.script, client, step, spec)}".splitlines()]
        if enabled:
            if device is None:
                self.needs_instrument = True
            elif device not in self.devices:
                self.devices.append(device)
        lines = f"response = {_call_source(self.script, client, step, spec)}".splitlines() + [f"print({py_literal(command)}, response)"]
        if enabled:
            from backend import returns as returns_mod

            for save in flow.saves_of(step):
                source = returns_mod.python_for(returns_mod.describe(spec.return_annotation), save["field"])
                if source is None:
                    self.script.warnings.append(f"Card {self.numbers.get(step['id'], '?')}: cannot tell how a script reads '{save['field']}' from {command}'s result; not kept.")
                else:
                    lines.append(f"{self.script.names[save['name']]} = {source}")
        return lines

    def _loop_header(self, target: str, iterable: str) -> str:
        if self.uses_index:
            return f"for {self.script.names.get('index', 'index')}, {target} in enumerate({iterable}, start=1):"
        return f"for {target} in {iterable}:"

    def _for_list(self, step: dict[str, Any]) -> list[str]:
        raw = step.get("params", {}).get("items", "")
        if isinstance(raw, str) and variables_mod.REF.fullmatch(raw.strip()):
            source = self.script.reference(raw)
        else:
            source = py_literal(variables_mod.coerce({"name": "items", "type": "list", "value": raw}))
        target = self.script.names[flow.loop_variables(step)[0]]
        return [self._loop_header(target, source), *self.indent(self.block(step.get("children", [])))]

    def _for_plate(self, step: dict[str, Any]) -> list[str]:
        params = step.get("params", {})
        fmt = str(params.get("format") or "96")
        try:
            rows, columns = (int(params.get("rows") or 8), int(params.get("columns") or 12)) if fmt == "custom" else flow.PLATE_FORMATS[fmt]
        except (ValueError, KeyError):
            self.script.warnings.append(f"Plate format {fmt!r} is not valid; using 96 wells.")
            rows, columns = flow.PLATE_FORMATS["96"]
        letters = flow.ROW_LETTERS[:rows]
        mode = params.get("iterate") or "columns"
        names = self.script.names
        target = names[flow.loop_variables(step)[0]]
        extra: list[str] = []
        if mode == "columns":
            iterable = f"range(1, {columns + 1})"
        elif mode == "rows":
            iterable = py_literal(letters)
        else:
            pair = f'for c in range(1, {columns + 1}) for r in {py_literal(letters)}' if params.get("order") != "row-wise" else f'for r in {py_literal(letters)} for c in range(1, {columns + 1})'
            iterable = f'[f"{{r}}{{c}}" {pair}]'
            if names.get("row") and names["row"] != target:
                extra.append(f"{names['row']} = {target}[0]")
            if names.get("col") and names["col"] != target:
                extra.append(f"{names['col']} = int({target}[1:])")
        return [self._loop_header(target, iterable), *self.indent(extra + self.block(step.get("children", [])))]


def render_script(
    steps: list[dict[str, Any]],
    variables: list[dict[str, Any]],
    *,
    instrument_type: str,
    simulate: bool,
    flow_name: str = "",
    command_label: Any = None,
    subflows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """{"source": str, "warnings": [str]}. `command_label(name)` gives a card's title for comments. Each subflow
    a Run Subflow card calls is written as a function."""
    taken: set[str] = {"SIMULATE"}
    names = {v["name"]: variables_mod.identifier(v["name"], taken) for v in variables}
    everything = [*steps, *(s for sub in subflows or [] for s in sub.get("steps", []))]
    for provided in sorted(flow.provided_names(everything)):  # names a loop / Set Variable card makes
        names.setdefault(provided, py_name(provided))
    script = _Script(names)
    script.text_names = {v["name"] for v in variables if v.get("type", "string") in variables_mod.TEXT_TYPES}
    for step in flow.flat(everything):  # plate loops: row letters and well names are text, columns and the index are numbers
        if step.get("command") == flow.FOR_PLATE:
            mode = (step.get("params") or {}).get("iterate") or "columns"
            if mode in ("rows", "wells"):
                script.text_names.add(flow.loop_variables(step)[0])
            if mode == "wells":
                script.text_names.add("row")

    constants = [f"SIMULATE = {simulate!r}"]
    for variable in variables:
        try:
            typed = variables_mod.coerce(variable)
        except variables_mod.VariableError as exc:
            script.warnings.append(str(exc))
            continue
        note = "  # asked before each run in Studio" if variable.get("prompt") else ""
        constants.append(f"{names[variable['name']]} = {py_literal(typed)}{note}")

    emitter = _Emitter(script, steps, instrument_type, command_label, subflows)
    body = emitter.block(steps)
    functions: list[str] = []
    for tab, definition in emitter.defs.items():  # callees first, so each reads top to bottom
        declared = sorted(definition["assigned"] | ({"response"} if emitter.uses_last else set()))
        inside = ([f"global {', '.join(declared)}"] if declared else []) + definition["lines"]
        functions += [f"# Subflow: {' '.join(str(tab).split())}", f"def {definition['name']}():", *emitter.indent(inside), ""]
    defined = {v["name"] for v in variables}
    for name in emitter.prompt_names:
        if name not in defined:
            script.warnings.append(f"The Ask card keeping its answer in {name} cannot ask in a script; set a value for {names[name]} at the top.")
            constants.append(f'{names[name]} = ""  # a script cannot ask: set this value')
    if emitter.uses_last:
        body = ["response = None", ""] + body

    client_cls = "StarClient" if instrument_type == "STAR" else "VantageClient"
    needs_instrument = emitter.needs_instrument or not emitter.devices
    targets = ([f"{client_cls}(simulate=SIMULATE) as {_INSTRUMENT_VAR}"] if needs_instrument else []) + [
        f"{d.client_cls.__name__}(simulate=SIMULATE) as {d.prefix.rstrip('_')}" for d in emitter.devices
    ]
    clients = ([client_cls] if needs_instrument else []) + [d.client_cls.__name__ for d in emitter.devices]

    title = flow_name.strip() or "Untitled flow"
    lines = [f'"""{title.replace(chr(34) * 3, chr(39) * 3)}', "", "Generated by Hamilton SDK Studio.", '"""', ""]
    if emitter.uses_time:
        lines.append("import time")
    lines.append(f"from hamilton_venus import {', '.join(clients)}, VenusError")
    for module in sorted(script.imports):
        lines.append(f"from {module} import {', '.join(sorted(script.imports[module]))}")
    lines += ["", *constants, "", "try:", f"    with {', '.join(targets)}:"]
    inner = [*functions, *body]
    if not _has_code(inner):
        inner = [*inner, "pass"]
    lines += [("        " + line) if line else "" for line in inner]
    lines += ["except VenusError as e:", '    print(f"SDK error: {e}")', "    raise SystemExit(1) from e", "", 'print("Done")', ""]
    return {"source": "\n".join(lines), "warnings": script.warnings}
