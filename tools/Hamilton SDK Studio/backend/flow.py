"""The flow as a tree, and the interpreter that runs it.

A flow is a list of cards. Control cards are containers: `children` holds the cards inside them
(`else_children` as well for If). Order everywhere is *document order*: a container, then its
cards, then the next card (pre-order), which is also the order the cards are numbered on screen.

The interpreter runs a tree against a set of variable values. SDK cards are handed to a callback
(the MCP bridge in a real run, a recorder in a preview), so the same walk gives the run, the
"how many commands will this send" preview, and the Python that Generate Script writes.

Selecting part of a flow (this card, from here, up to here, a range) picks card ids in document
order. A container whose own id is picked loops normally; one that only has picked cards inside is
entered once ("one pass") with its loop variables at their first iteration, so a single card
inside a loop can be tried out without running the whole loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from backend import expr, returns as returns_mod, variables as variables_mod

REPEAT, FOR_PLATE, FOR_LIST, WHILE, IF = "flow_repeat", "flow_for_plate", "flow_for_list", "flow_while", "flow_if"
BREAK, CONTINUE, SET_VARIABLE, PROMPT, WAIT = "flow_break", "flow_continue", "flow_set_variable", "flow_prompt", "flow_wait"
# A call card is a leaf on screen. Before a run, preview or script, `expand` puts the called subflow's cards in its
# `children`, so from then on it is a container that runs its body once.
CALL = "flow_call"
CONTAINERS = {REPEAT, FOR_PLATE, FOR_LIST, WHILE, IF, CALL}
LOOPS = {REPEAT, FOR_PLATE, FOR_LIST, WHILE}
CONTROL = CONTAINERS | {BREAK, CONTINUE, SET_VARIABLE, PROMPT, WAIT}

PLATE_FORMATS = {"6": (2, 3), "12": (3, 4), "24": (4, 6), "48": (6, 8), "96": (8, 12), "384": (16, 24)}
MAX_ITERATIONS = 100_000
DEFAULT_WHILE_CAP = 1000
ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class FlowError(Exception):
    """The flow cannot run as written (bad expression, no iterations, loop cap exceeded)."""


class Stopped(Exception):
    """The user stopped the run."""


class StepFailed(Exception):
    def __init__(self, step_id: str, message: str) -> None:
        super().__init__(message)
        self.step_id, self.message = step_id, message


# -- tree helpers ----------------------------------------------------------------------------------


def lanes(step: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """The card lists inside a container (one, or two for If); empty for other cards."""
    if step.get("command") not in CONTAINERS:
        return []
    found = [step.setdefault("children", [])]
    if step.get("command") == IF:
        found.append(step.setdefault("else_children", []))
    return found


def walk(steps: list[dict[str, Any]], parents: tuple[dict[str, Any], ...] = ()) -> Iterator[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    """(card, ancestors) in document order."""
    for step in steps:
        yield step, parents
        for lane in lanes(step):
            yield from walk(lane, (*parents, step))


def flat(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [step for step, _ in walk(steps)]


def labels(steps: list[dict[str, Any]]) -> dict[str, str]:
    """card id -> its on-screen number: 1, 2, 2.1, 2.2 ... (an If's two lanes number on from each other)."""
    result: dict[str, str] = {}

    def visit(items: list[dict[str, Any]], prefix: str, start: int = 1) -> None:
        for number, step in enumerate(items, start=start):
            label = f"{prefix}{number}"
            result[step["id"]] = label
            offset = 1
            for lane in lanes(step):
                visit(lane, f"{label}.", offset)
                offset += len(lane)

    visit(steps, "")
    return result


def expand(steps: list[dict[str, Any]], subflows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """A copy of `steps` in which every Run Subflow card holds the cards of the subflow it names (and so on, for
    subflows that call subflows). Raises FlowError for a missing subflow or one that calls itself."""
    by_name = {str(s.get("name")): s for s in subflows or [] if s.get("name")}
    numbering = labels(steps)

    def visit(items: list[dict[str, Any]], trail: tuple[str, ...]) -> list[dict[str, Any]]:
        out = []
        for step in items:
            copy = dict(step)
            if step.get("command") == CALL:
                name = str(_param(step, "subflow", ""))
                where = f"Card {numbering[step['id']]}" if step["id"] in numbering and not trail else f"A card in subflow '{trail[-1] if trail else '?'}'"
                if step.get("enabled", True):
                    if not name:
                        raise FlowError(f"{where}: choose which subflow to run.")
                    if name not in by_name:
                        raise FlowError(f"{where}: there is no subflow named '{name}'.")
                    if name in trail:
                        raise FlowError(f"Subflow '{name}' runs itself ({' > '.join([*trail, name])}); a subflow cannot call itself.")
                    copy["children"] = visit(by_name[name].get("steps", []), (*trail, name))
                else:
                    copy["children"] = []
            else:
                for lane in ("children", "else_children"):
                    if lane in step:
                        copy[lane] = visit(step[lane], trail)
            out.append(copy)
        return out

    return visit(steps, ())


def names_elsewhere(main: list[dict[str, Any]] | None, subflows: list[dict[str, Any]] | None) -> set[str]:
    """Variable names the cards of the main flow and of every subflow make: a subflow run on its own may use what
    the flow that calls it sets."""
    found = provided_names(main or [])
    for sub in subflows or []:
        found |= provided_names(sub.get("steps", []))
    return found


def _subtree_ids(step: dict[str, Any]) -> list[str]:
    return [s["id"] for s, _ in walk([step])]


def select(steps: list[dict[str, Any]], mode: str, start_id: str | None, end_id: str | None) -> set[str] | None:
    """The card ids a run covers, or None for "everything". Raises FlowError for an unknown card."""
    if mode == "all":
        return None
    order = flat(steps)
    ids = [s["id"] for s in order]
    by_id = {s["id"]: s for s in order}

    def index(step_id: str | None, what: str) -> int:
        if step_id not in by_id:
            raise FlowError(f"The {what} card is not in the flow")
        return ids.index(step_id)

    if mode == "only":
        return set(_subtree_ids(by_id[ids[index(start_id, "selected")]]))
    first = 0 if mode == "to" else index(start_id, "starting" if mode == "from" else "start")
    last = len(ids) - 1 if mode == "from" else index(end_id, "ending" if mode == "to" else "end")
    if first > last:
        first, last = last, first
    picked = set(ids[first : last + 1])
    for edge in (ids[first], ids[last]):  # a container at either end brings its whole body
        picked.update(_subtree_ids(by_id[edge]))
    return picked


# -- loop variables ---------------------------------------------------------------------------------


def _param(step: dict[str, Any], name: str, default: Any = None) -> Any:
    value = step.get("params", {}).get(name)
    return default if value in (None, "") else value


def saves_of(step: dict[str, Any]) -> list[dict[str, str]]:
    """The values a card keeps from its result: [{name, field}]. An older flow's single `save` counts as one."""
    raw = step.get("saves")
    if raw is None and step.get("save"):
        raw = [step["save"]]
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            out.append({"name": str(item["name"]).strip(), "field": str(item.get("field") or "")})
    return out


def loop_variables(step: dict[str, Any]) -> list[str]:
    """Names a card makes available to the cards after/inside it (its loop variables, and the variable it
    keeps its result in)."""
    names = _own_variables(step)
    return [*names, *(s["name"] for s in saves_of(step))]


def _own_variables(step: dict[str, Any]) -> list[str]:
    command = step.get("command")
    if command == REPEAT:
        return [str(_param(step, "variable", "i"))]
    if command == FOR_LIST:
        return [str(_param(step, "variable", "item")), "index"]
    if command == FOR_PLATE:
        mode = _param(step, "iterate", "columns")
        main = str(_param(step, "variable", {"columns": "col", "rows": "row", "wells": "well"}.get(mode, "col")))
        names = [main, "index"]
        if mode == "wells":
            names += ["col", "row"]
        return names
    if command == SET_VARIABLE:
        return [str(_param(step, "name", ""))] if _param(step, "name") else []
    if command == PROMPT:
        return [str(_param(step, "store_in"))] if _param(step, "store_in") else []
    return []


def provided_names(steps: list[dict[str, Any]]) -> set[str]:
    return {name for step, _ in walk(steps) for name in loop_variables(step)}


def iteration_items(step: dict[str, Any], values: dict[str, Any]) -> list[dict[str, Any]]:
    """The variable bindings of each iteration of a Repeat / For each card."""
    params = variables_mod.resolve(dict(step.get("params", {})), values)
    command = step["command"]
    if command == REPEAT:
        try:
            count = int(params.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise FlowError(f"Repeat count {params.get('count')!r} is not a number.") from exc
        if count < 0 or count > MAX_ITERATIONS:
            raise FlowError(f"Repeat count must be between 0 and {MAX_ITERATIONS}.")
        name = loop_variables(step)[0]
        return [{name: n} for n in range(1, count + 1)]
    if command == FOR_LIST:
        raw = params.get("items", [])
        items = raw if isinstance(raw, list) else [variables_mod._number_or_text(p.strip()) for p in str(raw).split(",") if p.strip()]  # noqa: SLF001
        name = loop_variables(step)[0]
        return [{name: item, "index": k} for k, item in enumerate(items, start=1)]
    if command == FOR_PLATE:
        fmt = str(params.get("format", "96"))
        if fmt == "custom":
            try:
                rows, columns = int(params.get("rows", 8)), int(params.get("columns", 12))
            except (TypeError, ValueError) as exc:
                raise FlowError("Custom plate rows and columns must be numbers.") from exc
        elif fmt in PLATE_FORMATS:
            rows, columns = PLATE_FORMATS[fmt]
        else:
            raise FlowError(f"Unknown plate format {fmt!r}.")
        if not (1 <= rows <= len(ROW_LETTERS) and 1 <= columns <= 48):
            raise FlowError("The plate has to have between 1 and 26 rows and 1 and 48 columns.")
        mode = params.get("iterate", "columns")
        name = loop_variables(step)[0]
        letters = ROW_LETTERS[:rows]
        if mode == "columns":
            return [{name: c, "index": c} for c in range(1, columns + 1)]
        if mode == "rows":
            return [{name: letter, "index": k} for k, letter in enumerate(letters, start=1)]
        if mode == "wells":
            pairs = ([(r, c) for c in range(1, columns + 1) for r in letters] if params.get("order", "column-wise") != "row-wise"
                     else [(r, c) for r in letters for c in range(1, columns + 1)])
            return [{name: f"{r}{c}", "col": c, "row": r, "index": k} for k, (r, c) in enumerate(pairs, start=1)]
        raise FlowError(f"Unknown iterate mode {mode!r}.")
    raise FlowError(f"{command} does not loop over a list.")


# -- checks before a run ---------------------------------------------------------------------------------


def check(steps: list[dict[str, Any]], defined: set[str]) -> list[str]:
    return [message for _, message in problems(steps, defined)]


def problems(steps: list[dict[str, Any]], defined: set[str]) -> list[tuple[str, str]]:
    """(card id, message) for what stops the flow before it starts: bad expressions, unknown names, stray Break."""
    found: list[tuple[str, str]] = []
    known = defined | provided_names(steps) | {"last"}
    numbering = labels(steps)
    for step, ancestors in walk(steps):
        command, label = step.get("command"), f"Card {numbering.get(step['id'], '?')}"
        if not step.get("enabled", True):
            continue
        if command in (BREAK, CONTINUE) and not any(a.get("command") in LOOPS for a in ancestors):
            found.append((step["id"], f"{label}: {'Break' if command == BREAK else 'Continue'} must be inside a loop."))
        text = {WHILE: _param(step, "condition"), IF: _param(step, "condition"), SET_VARIABLE: _param(step, "expression")}.get(command)
        if command in (WHILE, IF, SET_VARIABLE):
            if text is None:
                found.append((step["id"], f"{label}: {'the expression is' if command == SET_VARIABLE else 'the condition is'} empty."))
                continue
            try:
                unknown = expr.names_in(str(text)) - known
            except expr.ExprError as exc:
                found.append((step["id"], f"{label}: {exc}"))
                continue
            if unknown:
                found.append((step["id"], f"{label}: unknown name(s) in the expression: {', '.join(sorted(unknown))}."))
        if any(not variables_mod.REF.fullmatch("{{" + s["name"] + "}}") for s in saves_of(step)):
            found.append((step["id"], f"{label}: the name to keep the result in is not valid (letters, digits and _)."))
        if command == SET_VARIABLE and not variables_mod.REF.fullmatch("{{" + str(_param(step, "name", "")) + "}}"):
            found.append((step["id"], f"{label}: the variable name is empty or not valid."))
    return found


# -- interpreter -------------------------------------------------------------------------------------------


@dataclass
class Hooks:
    """What the interpreter needs from its host (the real runner or a preview recorder)."""

    leaf: Callable[[dict[str, Any], dict[str, Any]], Any]
    event: Callable[[dict[str, Any]], None] = lambda e: None
    checkpoint: Callable[[], None] = lambda: None
    prompt: Callable[[dict[str, Any], str], str | None] = lambda step, message: None
    wait: Callable[[float], None] = time.sleep


@dataclass
class Interpreter:
    hooks: Hooks
    values: dict[str, Any]
    included: set[str] | None = None
    dry: bool = False
    notes: list[str] = field(default_factory=list)
    last: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._touched: set[str] | None = None
        self._unknown: set[str] = set()  # in a preview: variables whose value only a real run would give

    def run(self, steps: list[dict[str, Any]]) -> None:
        if self.included is not None:
            self._touched = set(self.included)
            for step, ancestors in walk(steps):
                if step["id"] in self.included:
                    self._touched.update(a["id"] for a in ancestors)
        signal = self._lane(steps)
        if signal:
            raise FlowError("Break / Continue used outside a loop.")

    # -- helpers --------------------------------------------------------------------------------------

    def _names(self) -> dict[str, Any]:
        return {**self.values, "last": self.last}

    def _wanted(self, step: dict[str, Any]) -> bool:
        return self._touched is None or step["id"] in self._touched

    def _looping(self, step: dict[str, Any]) -> bool:
        return self.included is None or step["id"] in self.included

    def _needs_a_result(self, text: str) -> bool:
        """In a preview: does the expression use something only a real run can know (a result)?"""
        if not self.dry:
            return False
        try:
            return bool(expr.names_in(text) & (self._unknown | {"last"}))
        except expr.ExprError:
            return False

    def _condition(self, step: dict[str, Any]) -> bool:
        text = str(_param(step, "condition", ""))
        try:
            return bool(expr.evaluate(text, self._names()))
        except expr.ExprError as exc:
            if self._needs_a_result(text):  # a preview has no results to test
                self.notes.append(f"'{text}' depends on a command's result, so the preview assumes it is false.")
                return False
            raise FlowError(f"Condition '{text}': {exc}") from exc

    # -- walking ----------------------------------------------------------------------------------------

    def _lane(self, nodes: list[dict[str, Any]]) -> str | None:
        for node in nodes:
            self.hooks.checkpoint()
            if not self._wanted(node):
                continue
            try:
                signal = self._node(node)
            except (Stopped, StepFailed, PreviewLimit):
                raise
            except Exception as exc:  # noqa: BLE001 - whatever went wrong belongs to this card, with its reason
                raise StepFailed(node["id"], str(exc) or type(exc).__name__) from exc
            if signal:
                return signal
        return None

    def _node(self, step: dict[str, Any]) -> str | None:
        sid, command = step["id"], step.get("command")
        if not step.get("enabled", True):
            self.hooks.event({"id": sid, "status": "skipped"})
            return None
        if command in CONTAINERS:
            return self._container(step)
        if command in (BREAK, CONTINUE):
            self.hooks.event({"id": sid, "status": "success"})
            return "break" if command == BREAK else "continue"
        self.hooks.event({"id": sid, "status": "running"})
        params = variables_mod.resolve(dict(step.get("params", {})), self.values)
        if command == SET_VARIABLE:
            name = str(_param(step, "name", ""))
            text = str(_param(step, "expression", ""))
            try:
                self.values[name] = expr.evaluate(text, self._names())
            except expr.ExprError as exc:
                if not self._needs_a_result(text):
                    raise StepFailed(sid, str(exc)) from exc
                self.notes.append(f"'{text}' depends on a command's result, so the preview leaves {name} unknown.")
                self.values[name] = None
                self._unknown.add(name)
            self.hooks.event({"id": sid, "status": "success", "response": {name: self.values[name]}})
        elif command == PROMPT:
            answer = None if self.dry else self.hooks.prompt(step, str(params.get("message", "")))
            name = _param(step, "store_in")
            if name and answer is not None:
                self.values[str(name)] = variables_mod._number_or_text(str(answer).strip())  # noqa: SLF001
            self.hooks.event({"id": sid, "status": "success", **({"response": {"answer": answer}} if answer is not None else {})})
        elif command == WAIT:
            try:
                seconds = float(params.get("seconds", 0))
            except (TypeError, ValueError) as exc:
                raise StepFailed(sid, f"Wait needs a number of seconds, not {params.get('seconds')!r}.") from exc
            if not self.dry:
                self.hooks.wait(max(0.0, seconds))
            self.hooks.event({"id": sid, "status": "success"})
        else:  # an SDK card or the Connect Instrument card
            self.last = self.hooks.leaf(step, params)
            self._save(step)
        return None

    def _save(self, step: dict[str, Any]) -> None:
        """Keep the part of the command's result the card names in a variable."""
        kept = []
        result = self.last.get("result") if isinstance(self.last, dict) else None
        for save in saves_of(step):
            name, path = save["name"], save["field"]
            try:
                value = returns_mod.pick(result, path)
            except KeyError:
                if not self.dry:
                    raise StepFailed(step["id"], f"This command's result has no '{path}' to keep in {name}.") from None
                value = None  # a preview has no real result
                self._unknown.add(name)
            self.values[name] = value
            kept.append({"name": name, "value": value})
        if kept:
            self.hooks.event({"id": step["id"], "saved": kept})

    def _container(self, step: dict[str, Any]) -> str | None:
        sid, command = step["id"], step["command"]
        looping = self._looping(step)
        body = step.setdefault("children", [])
        self.hooks.event({"id": sid, "status": "running"})
        if command == CALL:  # the subflow's cards, run once
            signal = self._lane(body)
            self.hooks.event({"id": sid, "status": "success"})
            return signal
        if command == IF:
            else_body = step.setdefault("else_children", [])
            if looping:
                chosen = body if self._condition(step) else else_body
            else:  # one pass: the lane that holds the picked cards
                chosen = body if any(self._wanted(n) for n in body) else else_body
            signal = self._lane(chosen)
            self.hooks.event({"id": sid, "status": "success"})
            return signal
        if command == WHILE:
            cap = int(_param(step, "max_iterations", DEFAULT_WHILE_CAP))
            count = 0
            while (self._condition(step) if looping else count == 0):
                count += 1
                if count > cap:
                    raise StepFailed(sid, f"The loop ran more than its limit of {cap} iterations. Raise the limit or fix the condition.")
                self.hooks.event({"id": sid, "status": "running", "iteration": count})
                signal = self._lane(body)
                if signal == "break":
                    break
            self.hooks.event({"id": sid, "status": "success", "iterations": count})
            return None
        try:
            items = iteration_items(step, self.values)
        except FlowError as exc:
            raise StepFailed(sid, str(exc)) from exc
        if not looping:
            if not items:
                raise StepFailed(sid, "This loop has no iterations, so there is nothing to try a single card on.")
            items = items[:1]
        done = 0
        for number, binding in enumerate(items, start=1):
            self.values.update(binding)
            self.hooks.event({"id": sid, "status": "running", "iteration": number, "total": len(items)})
            signal = self._lane(body)
            done = number
            if signal == "break":
                break
        self.hooks.event({"id": sid, "status": "success", "iterations": done, "total": len(items)})
        return None


# -- preview -------------------------------------------------------------------------------------------------


class PreviewLimit(Exception):
    pass


def preview(steps: list[dict[str, Any]], values: dict[str, Any], included: set[str] | None = None, limit: int = 5000, lines: int = 200) -> dict[str, Any]:  # steps already expanded
    """What a run would send, without running anything: the command count and the first commands
    with the loop variables they would see. Conditions that need a command's result are assumed
    false (noted)."""
    sent: list[dict[str, Any]] = []
    numbering = labels(steps)

    def leaf(step: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        if len(sent) >= limit:
            raise PreviewLimit
        sent.append({"id": step["id"], "label": numbering.get(step["id"], "?"), "command": step["command"], "params": params,
                     "vars": {k: v for k, v in interp.values.items() if k in loop_names}})
        return {}

    loop_names = provided_names(steps)
    interp = Interpreter(Hooks(leaf=leaf), dict(values), included, dry=True)
    truncated, error = False, None
    try:
        interp.run(steps)
    except PreviewLimit:
        truncated = True
    except (FlowError, StepFailed) as exc:  # what was computed before the problem is still useful
        error = exc.message if isinstance(exc, StepFailed) else str(exc)
    return {"commands": len(sent), "truncated": truncated, "error": error, "notes": sorted(set(interp.notes)), "lines": sent[:lines]}
