"""Turns a finished run's summary (``hamilton_workflow_framework.run_summary.summarize_run``)
into the ``UsageRow`` list ``ConsumablesLedger.record_run`` writes, once, when a run finishes.

Kept as its own small, pure function (no ledger/manager imports) so it is trivially unit
testable against summary fixtures, independent of sqlite or the run manager.
"""

from __future__ import annotations

from typing import Any

from hamilton_venus_mcp.script_runs.consumables_ledger import UsageRow


def usage_from_summary(summary: dict[str, Any]) -> list[UsageRow]:
    """Every item this run consumed, derived from ``summarize_run``'s own tallies.

    - Tips: one row per (kind, tip_type) from ``tips_by_type`` -- ``item_key`` is the tip type
      (rack/box/NTR labware definition, or "(unknown tip type)"), quantity in tips.
    - Reagents: one row per reservoir/tube actually drawn from, from ``reservoir_volumes`` --
      ``item_key`` is the labware id, quantity in uL.
    - Plates / lids: one row per labware definition added, from ``plates_by_type``/
      ``lids_by_type`` -- quantity in "each".

    Rows with a zero or missing quantity are dropped (nothing to record). Never raises: a
    summary missing a section is simply treated as contributing nothing from that section.
    """
    rows: list[UsageRow] = []

    for entry in summary.get("tips_by_type") or []:
        count = entry.get("count") or 0
        if count <= 0:
            continue
        tip_type = entry.get("tip_type") or "(unknown tip type)"
        rows.append(
            UsageRow(
                kind="tip",
                item_key=tip_type,
                item_label=f"{tip_type} ({entry.get('kind_label', entry.get('kind', ''))})",
                quantity=float(count),
                unit="tips",
                source=entry.get("kind"),
            )
        )

    for entry in summary.get("reservoir_volumes") or []:
        volume = entry.get("volume_ul") or 0.0
        if volume <= 0:
            continue
        labware = entry.get("labware") or "(unknown reservoir)"
        rows.append(UsageRow(kind="reagent", item_key=labware, item_label=labware, quantity=float(volume), unit="uL"))

    for entry in summary.get("plates_by_type") or []:
        count = entry.get("count") or 0
        if count <= 0:
            continue
        definition = entry.get("labware_definition") or "(unknown plate)"
        rows.append(UsageRow(kind="plate", item_key=definition, item_label=definition, quantity=float(count), unit="each"))

    for entry in summary.get("lids_by_type") or []:
        count = entry.get("count") or 0
        if count <= 0:
            continue
        definition = entry.get("labware_definition") or "(unknown lid)"
        rows.append(UsageRow(kind="lid", item_key=definition, item_label=definition, quantity=float(count), unit="each"))

    return rows
