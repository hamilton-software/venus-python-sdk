"""WS message types for run monitoring. Opt-in: an app concatenates these into
its own ClientMessage union (see hamilton_workflow_framework.ws_protocol)
alongside the base tuple, only if it wires up sample tracking at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SetSampleMap(BaseModel):
    """Declares (or re-declares) the sample->well mapping for a run -- ground
    truth the operator enters (e.g. from the app's Setup tab), since there is
    no instrument query for "which sample is logically at this well."
    """

    type: Literal["set_sample_map"] = "set_sample_map"
    sample_id: str
    plate_id: str
    well: str


MONITORING_CLIENT_MESSAGES: tuple[type[BaseModel], ...] = (SetSampleMap,)
