"""A small, safe expression language for conditions and Set Variable cards.

Examples: `volume > 50 and plates_done < 3`, `col % 2 == 0`, `max(a, b) * 2`, `len(wells) > 0`,
`last["status"] == "success"`. Variables are plain names (no braces).

Allowed: numbers, strings, True/False/None, variable names, + - * / // % **, comparisons (including
chains, `in`, `not in`), `and` / `or` / `not`, `x if cond else y`, list/tuple literals, indexing and
slicing, and the functions len, min, max, abs, round, int, float, str, bool, sum. Nothing else:
no attributes, no other calls, no comprehensions or lambdas. The expression is evaluated by walking
its syntax tree here, never with eval(), so it cannot reach Python itself.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

FUNCTIONS: dict[str, Any] = {
    "len": len, "min": min, "max": max, "abs": abs, "round": round, "int": int, "float": float,
    "str": str, "bool": bool, "sum": sum,
}
MAX_SEQUENCE = 100_000
MAX_POWER = 1000

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


class ExprError(ValueError):
    """The expression is not allowed, or could not be evaluated; the message is safe to show."""


def parse(text: str) -> ast.Expression:
    """The checked syntax tree of `text`. Raises ExprError for anything outside the language."""
    if not isinstance(text, str) or not text.strip():
        raise ExprError("The expression is empty.")
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"Not a valid expression: {exc.msg}") from exc
    for node in ast.walk(tree):
        _check(node)
    return tree


def _check(node: ast.AST) -> None:
    allowed = (
        ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
        ast.Subscript, ast.Slice, ast.List, ast.Tuple, ast.Call, ast.And, ast.Or,
        *_BINARY, *_UNARY, *_COMPARE,
    )
    if not isinstance(node, allowed):
        raise ExprError(f"{type(node).__name__} is not allowed in an expression.")
    if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
        raise ExprError("Only numbers, text, True/False and None can be written in an expression.")
    if isinstance(node, ast.Name) and node.id.startswith("__"):
        raise ExprError(f"The name {node.id} is not allowed.")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError("Only these functions can be called: " + ", ".join(FUNCTIONS) + ".")
        if node.keywords:
            raise ExprError("Functions take positional arguments only.")


def names_in(text: str) -> set[str]:
    """Variable names an expression reads (function names excluded)."""
    tree = parse(text)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - called


def evaluate(text: str, names: dict[str, Any]) -> Any:
    """The value of `text` with `names` as its variables."""
    try:
        return _eval(parse(text).body, names)
    except ExprError:
        raise
    except ZeroDivisionError as exc:
        raise ExprError("Division by zero.") from exc
    except (TypeError, ValueError, KeyError, IndexError, OverflowError) as exc:
        raise ExprError(f"Could not evaluate {text.strip()!r}: {exc}") from exc


def _guard(value: Any) -> Any:
    if isinstance(value, (str, list, tuple)) and len(value) > MAX_SEQUENCE:
        raise ExprError("The result is too large.")
    return value


def _eval(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ExprError(f"Unknown name {node.id!r}. Define it as a variable, or use a loop or Set Variable card that provides it.")
        return names[node.id]
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, names), _eval(node.right, names)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > MAX_POWER:
            raise ExprError("That exponent is too large.")
        return _guard(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval(node.operand, names))
    if isinstance(node, ast.BoolOp):
        result: Any = None
        for value in node.values:
            result = _eval(value, names)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, names)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, names)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, names) else node.orelse, names)
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_eval(e, names) for e in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.Subscript):
        index = node.slice
        key = slice(*(None if part is None else _eval(part, names) for part in (index.lower, index.upper, index.step))) if isinstance(index, ast.Slice) else _eval(index, names)
        return _eval(node.value, names)[key]
    if isinstance(node, ast.Call):
        return _guard(FUNCTIONS[node.func.id](*[_eval(a, names) for a in node.args]))
    raise ExprError(f"{type(node).__name__} is not allowed in an expression.")
