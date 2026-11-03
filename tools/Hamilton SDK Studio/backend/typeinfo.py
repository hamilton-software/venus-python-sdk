"""Reading SDK type annotations: the concrete types inside Optional/Union/list, and enum choices.

Shared by the command catalog (named choices for dropdowns, so a colour is Green rather than 2)
and Generate Script (writing `LightColor.GREEN` rather than a number).
"""

from __future__ import annotations

import types
import typing
from enum import Enum
from typing import Any

from pydantic import BaseModel

_ACRONYMS = {
    "adc": "ADC", "mad": "MAD", "lld": "LLD", "qcg": "QCG", "ipg": "IPG", "tadm": "TADM", "odtc": "ODTC", "hhc": "HHC",
    "tec": "TEC", "csv": "CSV", "id": "ID", "mph96": "MPH96", "iswap": "iSWAP", "cor": "CO-RE", "led": "LED", "rgt": "RGT",
    "plc": "PLC", "usb": "USB", "pwm": "PWM", "hsl": "HSL", "rck": "RCK", "ml": "mL", "ul": "µL",
}


def title_words(name: str) -> str:
    """snake_case or UPPER_SNAKE -> 'Title Words', keeping the acronyms this domain uses (ADC, LLD, iSWAP, ...)."""
    return " ".join(_ACRONYMS.get(word.lower(), word.capitalize()) for word in name.replace("_", " ").split())


def candidates(annotation: Any) -> list[Any]:
    """The concrete types inside an annotation: Optional/Union/Annotated unwrapped, None dropped."""
    if annotation is None or annotation is typing.Any:
        return []
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return candidates(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        return [c for arg in typing.get_args(annotation) for c in candidates(arg)]
    return [] if annotation is type(None) else [annotation]


def _element_types(annotation: Any) -> list[Any]:
    """Types of the items of any list/tuple/set in the annotation (one level)."""
    out: list[Any] = []
    for candidate in candidates(annotation):
        if typing.get_origin(candidate) in (list, tuple, set, frozenset):
            for arg in typing.get_args(candidate):
                out += candidates(arg)
    return out


def enum_class(annotation: Any) -> type[Enum] | None:
    """The Enum an annotation chooses from (directly, or as a list of them), if any."""
    for candidate in [*candidates(annotation), *_element_types(annotation)]:
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            return candidate
    return None


def enum_choices(enum_cls: type[Enum]) -> list[dict[str, Any]]:
    return [{"value": member.value, "label": title_words(member.name)} for member in enum_cls]


def collect_enums(annotation: Any, found: dict[str, list[dict[str, Any]]], depth: int = 0) -> None:
    """Add every enum reachable from the annotation (including inside settings models) to `found`,
    by class name -- the name a JSON schema's $defs uses for it."""
    if depth > 4:
        return
    enum_cls = enum_class(annotation)
    if enum_cls is not None:
        found.setdefault(enum_cls.__name__, enum_choices(enum_cls))
    for candidate in [*candidates(annotation), *_element_types(annotation)]:
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            for info in candidate.model_fields.values():
                collect_enums(info.annotation, found, depth + 1)
