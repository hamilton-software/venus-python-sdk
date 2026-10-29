"""Helpers for building a labware definition from scratch.

Produces the ``urn:hamilton:schemas:microlab:labware:v1`` JSON object that
:meth:`StarClient.labware_add_definition` sends as ``definition``. Covers labware
made of one uniform grid of liquid-holding wells -- plates and reservoirs -- and
single tubes (:func:`build_tube_definition`).

Example::

    definition = build_labware_definition(
        "My_96_DW",
        height=42.0,
        rows=8,
        columns=12,
        first_well_center=(14.0, 11.5),
        well=round_well(diameter=6.5, depth=40.0, bottom="round"),
    )
    star.labware_add_definition("My_96_DW", definition)

All lengths are millimetres. The result is a plain dict, so anything the helpers
do not cover can be set on it directly before it is sent.

Usage is two steps: describe one well with :func:`round_well` or
:func:`rectangular_well`, then wrap it with :func:`build_labware_definition`
(plate or reservoir) or :func:`build_tube_definition` (tube). See
``docs/examples/advanced/labware_builder.md`` for a full guide.

VENUS generates its own rack and container files from the definition, and reads
several values for them from Hamilton ``customAttributes`` (clearance, touch off,
cLLD mode, index parameters). The helpers always write those, mirroring the
definitions shipped with the SDK.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

SCHEMA_URN = "urn:hamilton:schemas:microlab:labware:v1"
SCHEMA_VERSION = "1.0.0-alpha.1"

WellBottom = Literal["flat", "round", "cone"]

# Footprint VENUS needs for labware that sits on a standard (SBS) carrier site.
SBS_WIDTH = 127.0
SBS_DEPTH = 86.0

# Clearance defaults to this far above the top of the labware (plate height or tube depth).
# Liquid seeking start height defaults to the clearance.
_CLEARANCE_MARGIN = 5.0
# Shipped tubes place their alignment feature this far below the top of the tube.
_TUBE_ALIGNMENT_DROP = 1.0

_TOUCH_OFF_DISABLED = {
    "enabled": False,
    "frontMm": 0.0,
    "backMm": 0.0,
    "leftMm": 0.0,
    "rightMm": 0.0,
    "baseMm": 0.0,
    "heightMm": 0.0,
}


def touch_off(distance: float, height: float, *, base: float = 0.0) -> dict[str, Any]:
    """Return enabled touch-off settings for a well helper's *touch_off* argument.

    Example::

        well = round_well(diameter=6.5, depth=40.0, touch_off=touch_off(2.9, 32.0))

    Args:
        distance: Distance in mm from the well centre toward the wall, used for
            all four sides (front, back, left, right).
        height: Touch-off height in mm, measured from the well floor.
        base: Touch-off base offset in mm. Shipped definitions use 0.0.

    Returns:
        The ``hamilton:touch_off`` attribute as a dict, with ``enabled`` set to True.
    """
    return {
        "enabled": True,
        "frontMm": distance,
        "backMm": distance,
        "leftMm": distance,
        "rightMm": distance,
        "baseMm": base,
        "heightMm": height,
    }


def body_segment(
    height: float,
    width: float,
    depth: float,
    *,
    top_width: float | None = None,
    top_depth: float | None = None,
) -> dict[str, float]:
    """Describe one slice of the outer shell of a plate or reservoir.

    A list of these, ordered from the top of the labware down, is passed as
    ``body_segments`` to :func:`build_labware_definition`. Together they give
    the real outer shape of the labware, which VENUS uses for its default grip
    parameters. Use the measured sizes here; the ``width`` and ``depth`` of
    :func:`build_labware_definition` stay at the carrier-site footprint.

    Example::

        # 11.9 mm tall upper body above a 2.5 mm skirt that narrows toward its top in X.
        body = [
            body_segment(height=11.9, width=124.0, depth=82.0),
            body_segment(height=2.5, width=127.76, depth=85.48, top_width=126.76),
        ]

    Args:
        height: Height of this slice in mm.
        width: Outer size along X (left to right) at the bottom of the slice.
        depth: Outer size along Y (front to back) at the bottom of the slice.
        top_width: Outer size along X at the top of the slice, for a slice with
            sloped sides. Defaults to ``width`` (straight sides).
        top_depth: Outer size along Y at the top of the slice. Defaults to
            ``depth`` (straight sides).

    Returns:
        The segment as a dict for the ``body_segments`` argument.
    """
    return {
        "height": height,
        "width": width,
        "depth": depth,
        "top_width": width if top_width is None else top_width,
        "top_depth": depth if top_depth is None else top_depth,
    }


def _body(
    segments: list[dict[str, float]], width: float, depth: float, height: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the ``hamilton:body_segments`` attribute and matching ``collisionShapes``."""
    if round(sum(segment["height"] for segment in segments), 6) > height:
        raise ValueError("the body segments are taller in total than the labware")

    segments_x = []
    segments_y = []
    shapes: dict[str, Any] = {}
    top = height
    for index, segment in enumerate(segments):
        segments_x.append(
            {"lowerWidthMm": segment["width"], "heightMm": segment["height"], "upperWidthMm": segment["top_width"]}
        )
        segments_y.append(
            {"lowerWidthMm": segment["depth"], "heightMm": segment["height"], "upperWidthMm": segment["top_depth"]}
        )
        if segment["width"] == segment["top_width"] and segment["depth"] == segment["top_depth"]:
            shape = {
                "type": "rectangular_prism",
                "height": segment["height"],
                "width": segment["width"],
                "depth": segment["depth"],
            }
        else:
            shape = {
                "type": "rectangular_frustum",
                "height": segment["height"],
                "widthBottom": segment["width"],
                "depthBottom": segment["depth"],
                "widthTop": segment["top_width"],
                "depthTop": segment["top_depth"],
            }
        top = round(top - segment["height"], 6)
        shapes[f"body_{index}"] = {"shape": shape, "origin": {"x": width / 2, "y": depth / 2, "z": top}}

    # VENUS writes its rack file's body segments from the attribute; collisionShapes carry the
    # same shape in schema terms, as in the shipped definitions.
    attribute = {"measuredFrom": "top", "segmentsX": segments_x, "segmentsY": segments_y}
    return attribute, shapes


def _well(
    opening: dict[str, Any],
    segments: list[dict[str, Any]],
    depth: float,
    bottom_wall_thickness: float,
    max_pipetting_depth: float,
    supports_lld: bool,
    liquid_seeking_start_height: float | None,
    clearance: float | None,
    clld_mode: int | None,
    touch_off: dict[str, Any] | None,
) -> dict[str, Any]:
    liquid_detection: dict[str, Any] = {"supportsLLD": supports_lld}
    if liquid_seeking_start_height is not None:
        liquid_detection["liquidSeekingStartHeight"] = liquid_seeking_start_height

    # clearance is filled in by build_labware_definition when it is not given here.
    custom_attributes: dict[str, Any] = {}
    if clld_mode is not None:
        custom_attributes["hamilton:clld_mode"] = {"mode": clld_mode}
    if clearance is not None:
        custom_attributes["hamilton:clearance"] = {"clearanceMm": clearance}
    custom_attributes["hamilton:touch_off"] = dict(touch_off or _TOUCH_OFF_DISABLED)

    return {
        "openingDimensions": opening,
        "totalDepth": depth,
        "maxPipettingDepth": max_pipetting_depth,
        "bottomWallThickness": bottom_wall_thickness,
        "volumeModel": {"segments": segments},
        "liquidDetection": liquid_detection,
        "customAttributes": custom_attributes,
    }


def _apply_height_defaults(well: dict[str, Any], top: float) -> None:
    """Fill in the clearance and liquid seeking start height that were not set on *well*."""
    clearance = well["customAttributes"].setdefault("hamilton:clearance", {"clearanceMm": top + _CLEARANCE_MARGIN})
    liquid_detection = well["liquidDetection"]
    if liquid_detection["supportsLLD"]:
        liquid_detection.setdefault("liquidSeekingStartHeight", clearance["clearanceMm"])


def round_well(
    diameter: float,
    depth: float,
    *,
    bottom: WellBottom = "flat",
    bottom_height: float | None = None,
    bottom_wall_thickness: float = 1.0,
    max_pipetting_depth: float = 0.0,
    supports_lld: bool = True,
    liquid_seeking_start_height: float | None = None,
    clearance: float | None = None,
    clld_mode: int | None = None,
    touch_off: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe one well (or tube) with a circular opening.

    The result is passed as ``well`` to :func:`build_labware_definition` or as
    ``tube`` to :func:`build_tube_definition`. The well is a straight cylinder
    with an optional shaped bottom; its volume-versus-height curve is derived
    from that shape. All lengths are millimetres.

    Example::

        flat = round_well(diameter=6.9, depth=11.3)
        deep = round_well(diameter=6.5, depth=40.0, bottom="round", bottom_height=2.5)
        pcr = round_well(diameter=6.0, depth=20.5, bottom="cone", bottom_height=12.0)

    Args:
        diameter: Inside diameter of the well opening.
        depth: Full depth of the well, from the opening down to its lowest point.
        bottom: Shape of the bottom of the well. ``"flat"`` is a plain cylinder,
            ``"round"`` ends in a spherical cap, and ``"cone"`` tapers to a point.
        bottom_height: Height of the shaped bottom section; the cylinder above
            it makes up the rest of ``depth``. For ``"round"`` it defaults to
            the well radius (a full hemisphere) and cannot exceed it. Required
            for ``"cone"``. Must not be given for ``"flat"``.
        bottom_wall_thickness: Thickness of the plastic under the well, from the
            inside floor down to the outside bottom. Written to the VENUS
            container file as its base height. Defaults to 1.0.
        max_pipetting_depth: Maximum safe pipetting depth, written to the VENUS
            container file as its max depth. Most shipped plates use 0.0 (the
            default); most shipped tubes use 1.0.
        supports_lld: Whether liquid level detection can be used in this well.
            When False, no liquid seeking start height is written.
        liquid_seeking_start_height: Height above the labware base at which the
            channel starts searching for the liquid surface. When omitted it is
            set to the clearance once the well is passed to a ``build_*``
            function.
        clearance: Height above the labware base that the tip must reach to
            move clear of this well. When omitted it is set to 5 mm above the
            top of the labware (plate height or tube height) once the well is
            passed to a ``build_*`` function.
        clld_mode: VENUS capacitive LLD setting for the container, written as
            ``hamilton:clld_mode``. Shipped plates use 1, 2 or 3 and shipped
            reservoirs use 4. Left out when omitted, which VENUS writes as 0.
        touch_off: Touch-off settings from :func:`touch_off`. Touch off is
            written as disabled when omitted.

    Returns:
        The ``containerDefinition`` section of a labware definition, as a dict.

    Raises:
        ValueError: If ``bottom`` is not a known shape, or ``bottom_height`` is
            missing, not allowed, or larger than the shape or ``depth`` permits.
    """
    if bottom == "flat":
        if bottom_height is not None:
            raise ValueError("bottom_height does not apply to a flat bottom")
        bottom_height = 0.0
    elif bottom == "round":
        if bottom_height is None:
            bottom_height = diameter / 2
        if bottom_height > diameter / 2:
            raise ValueError("a round bottom cannot be taller than the well radius")
    elif bottom == "cone":
        if bottom_height is None:
            raise ValueError("bottom_height is required for a cone bottom")
    else:
        raise ValueError(f"unknown bottom {bottom!r}; expected 'flat', 'round' or 'cone'")
    if not 0 <= bottom_height <= depth:
        raise ValueError("bottom_height must be between 0 and depth")

    # Segments are ordered bottom-to-top.
    segments: list[dict[str, Any]] = []
    if bottom == "round":
        segments.append({"type": "spherical_cap", "height": bottom_height, "diameter": diameter})
    elif bottom == "cone":
        segments.append(
            {"type": "conical_frustum", "height": bottom_height, "diameterBottom": 0.0, "diameterTop": diameter}
        )
    if depth > bottom_height:
        segments.append({"type": "cylinder", "height": depth - bottom_height, "diameter": diameter})

    return _well(
        {"shape": "circle", "diameter": diameter},
        segments,
        depth,
        bottom_wall_thickness,
        max_pipetting_depth,
        supports_lld,
        liquid_seeking_start_height,
        clearance,
        clld_mode,
        touch_off,
    )


def rectangular_well(
    width: float,
    length: float,
    depth: float,
    *,
    bottom_wall_thickness: float = 1.0,
    max_pipetting_depth: float = 0.0,
    supports_lld: bool = True,
    liquid_seeking_start_height: float | None = None,
    clearance: float | None = None,
    clld_mode: int | None = None,
    touch_off: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe one flat-bottomed well or trough with a rectangular opening.

    The result is passed as ``well`` to :func:`build_labware_definition`. All
    lengths are millimetres.

    Example::

        trough = rectangular_well(width=108.0, length=72.0, depth=38.0, clld_mode=4)

    Args:
        width: Inside size of the opening along X (left to right).
        length: Inside size of the opening along Y (front to back).
        depth: Full depth of the well, from the opening down to the floor.
        bottom_wall_thickness: Thickness of the plastic under the well, from the
            inside floor down to the outside bottom. Written to the VENUS
            container file as its base height. Defaults to 1.0.
        max_pipetting_depth: Maximum safe pipetting depth, written to the VENUS
            container file as its max depth. Most shipped plates use 0.0 (the
            default); most shipped tubes use 1.0.
        supports_lld: Whether liquid level detection can be used in this well.
            When False, no liquid seeking start height is written.
        liquid_seeking_start_height: Height above the labware base at which the
            channel starts searching for the liquid surface. When omitted it is
            set to the clearance once the well is passed to a ``build_*``
            function.
        clearance: Height above the labware base that the tip must reach to
            move clear of this well. When omitted it is set to 5 mm above the
            top of the labware (plate height or tube height) once the well is
            passed to a ``build_*`` function.
        clld_mode: VENUS capacitive LLD setting for the container, written as
            ``hamilton:clld_mode``. Shipped plates use 1, 2 or 3 and shipped
            reservoirs use 4. Left out when omitted, which VENUS writes as 0.
        touch_off: Touch-off settings from :func:`touch_off`. Touch off is
            written as disabled when omitted.

    Returns:
        The ``containerDefinition`` section of a labware definition, as a dict.
    """
    return _well(
        {"shape": "rectangle", "width": width, "depth": length},
        [{"type": "rectangular_prism", "height": depth, "width": width, "depth": length}],
        depth,
        bottom_wall_thickness,
        max_pipetting_depth,
        supports_lld,
        liquid_seeking_start_height,
        clearance,
        clld_mode,
        touch_off,
    )


def build_labware_definition(
    name: str,
    *,
    height: float,
    rows: int,
    columns: int,
    first_well_center: tuple[float, float],
    well: dict[str, Any],
    width: float = SBS_WIDTH,
    depth: float = SBS_DEPTH,
    body_segments: list[dict[str, float]] | None = None,
    labware_class: str = "plate",
    row_pitch: float = 9.0,
    column_pitch: float = 9.0,
    well_floor_height: float | None = None,
    iteration_order: Literal["column_major", "row_major"] | None = None,
    stack_height: float = 0.0,
    description: str | None = None,
    publisher: str = "user",
) -> dict[str, Any]:
    """Build a complete definition for a plate or reservoir.

    The labware is one rectangular grid of identical wells. The returned dict is
    what :meth:`StarClient.labware_add_definition` takes as ``labware_definition``.
    All lengths are millimetres.

    Example::

        definition = build_labware_definition(
            "My_96_DW",
            height=42.0,
            rows=8,
            columns=12,
            first_well_center=(14.0, 11.5),
            well=round_well(diameter=6.5, depth=40.0, bottom="round"),
            body_segments=[
                body_segment(height=36.0, width=124.0, depth=82.0),
                body_segment(height=6.0, width=127.76, depth=85.48),
            ],
        )
        star.labware_add_definition("My_96_DW", definition)

    Args:
        name: Name of the labware. Used as the display name and, prefixed with
            ``publisher``, as the ``id``, so it may only contain letters,
            digits, ``_`` and ``-``. Pass the same name to
            ``labware_add_definition``; it must not already exist.
        height: Outer height of the labware, from its base to its top.
        rows: Number of well rows (along Y). 8 for a 96-well plate.
        columns: Number of well columns (along X). 12 for a 96-well plate.
        first_well_center: ``(x, y)`` centre of the first well (A1), inside the
            ``width`` x ``depth`` footprint. X is measured from the left edge
            and Y from the edge the first row sits against (the back edge).
            14.0 / 11.5 for a 96-well plate on the default 127 x 86 footprint.
        well: The well shared by every position, from :func:`round_well` or
            :func:`rectangular_well`. It is copied, not modified.
        width: Footprint of the labware along X (left to right). Leave at the
            default 127.0 for anything placed on a standard (SBS) carrier site:
            VENUS rejects the placement ("Invalid placement of labware") when
            the footprint does not match the site. Put the measured outer size
            in ``body_segments`` instead.
        depth: Footprint of the labware along Y (front to back). Leave at the
            default 86.0 for a standard carrier site, as for ``width``.
        body_segments: Real outer shape of the labware as a list of
            :func:`body_segment`, ordered from the top down. VENUS uses it for
            its default grip parameters. Their heights may add up to at most
            ``height``. When omitted, no body shape is written.
        labware_class: ``"plate"`` or ``"reservoir"``. VENUS uses it to decide
            which folder and file type the definition is written to.
        row_pitch: Centre-to-centre spacing between rows (along Y). 9.0 for a
            96-well plate, 4.5 for a 384-well plate.
        column_pitch: Centre-to-centre spacing between columns (along X).
        well_floor_height: Height of the inside floor of the wells above the
            labware base. When omitted it is ``height`` minus the well depth,
            i.e. the well opening is flush with the top of the labware.
        iteration_order: How wells are numbered 1..N: ``"row_major"`` or
            ``"column_major"``. When omitted it follows the shipped
            definitions: ``"row_major"`` for plates, ``"column_major"`` otherwise.
        stack_height: Height added per plate when this labware is stacked on
            itself. Defaults to 0.0, as in the shipped definitions.
        description: Optional free-text description stored in the definition.
        publisher: Prefix of the ``id`` (``"<publisher>:<name>"``). Lowercase
            letters, digits, ``_`` and ``-``, starting with a letter.

    Returns:
        The complete labware definition as a dict, including the Hamilton
        ``customAttributes`` VENUS needs to generate its own labware files.

    Raises:
        ValueError: If ``rows`` or ``columns`` is less than 1, the well is
            deeper than the labware is tall, or the body segments are taller
            in total than the labware.
    """
    if rows < 1 or columns < 1:
        raise ValueError("rows and columns must be at least 1")
    if well_floor_height is None:
        well_floor_height = round(height - well["totalDepth"], 6)
    if well_floor_height < 0:
        raise ValueError("the well is deeper than the labware is tall; pass well_floor_height or check the sizes")

    if iteration_order is None:
        iteration_order = "row_major" if labware_class == "plate" else "column_major"

    well = copy.deepcopy(well)
    _apply_height_defaults(well, height)

    x, y = first_well_center
    definition: dict[str, Any] = {
        "$schema": SCHEMA_URN,
        "id": f"{publisher}:{name}",
        "schemaVersion": SCHEMA_VERSION,
        "displayName": name,
    }
    if description:
        definition["description"] = description
    definition.update(
        {
            "labwareClass": labware_class,
            "source": {"system": "manual"},
            "dimensions": {"x": width, "y": depth, "z": height},
            "containerGrids": {
                "default": {
                    "columns": columns,
                    "rows": rows,
                    "columnPitch": column_pitch,
                    "rowPitch": row_pitch,
                    "iterationOrder": iteration_order,
                    "firstContainerCenter": {"x": x, "y": y, "z": well_floor_height},
                    "namingConvention": {"rowStyle": "alpha", "columnStyle": "numeric", "format": "[row][col]"},
                    "containerDefinition": well,
                    "customAttributes": {"hamilton:ix_params": {"first": 1, "startingCorner": "back_left"}},
                }
            },
            "alignmentFeatures": [{"name": "sbs_rim", "offset": {"z": 0.0}}],
            "selfStack": {"height": stack_height},
            "visualModel": {"color": "#FFFFFF", "opacity": 0},
            "customAttributes": {"hamilton:is_user_defined": {"value": True}},
        }
    )
    if body_segments:
        attribute, shapes = _body(body_segments, width, depth, height)
        definition["collisionShapes"] = shapes
        definition["customAttributes"]["hamilton:body_segments"] = attribute
    return definition


def build_tube_definition(
    name: str,
    *,
    tube: dict[str, Any],
    material: str = "polypropylene",
    description: str | None = None,
    publisher: str = "user",
) -> dict[str, Any]:
    """Build a complete definition for a single sample tube.

    The returned dict is what :meth:`StarClient.labware_add_definition` takes as
    ``labware_definition``. Once added, the tube is placed on a tube carrier by
    name with ``add_tubes_to_carrier``. All lengths are millimetres.

    Example::

        definition = build_tube_definition(
            "My_Tube_17x75",
            tube=round_well(
                diameter=14.3,
                depth=73.8,
                bottom="round",
                bottom_wall_thickness=1.1,
                max_pipetting_depth=1.0,
            ),
        )
        star.labware_add_definition("My_Tube_17x75", definition)
        star.add_tubes_to_carrier("TubeCarrier", [{"position": "1", "tube": "My_Tube_17x75"}])

    Args:
        name: Name of the tube. Used as the display name and, prefixed with
            ``publisher``, as the ``id``, so it may only contain letters,
            digits, ``_`` and ``-``. Pass the same name to
            ``labware_add_definition``; it must not already exist.
        tube: The tube body, from :func:`round_well`. Its ``diameter`` is the
            diameter at the top of the tube, its ``depth`` the full height of
            the tube, and its ``bottom_wall_thickness`` the height of the inside
            floor above the outside bottom. Unless set there, clearance is 5 mm
            above the top of the tube and liquid seeking starts at the
            clearance. It is copied, not modified.
        material: Tube material, as a lowercase identifier. Every shipped tube
            uses ``"polypropylene"``.
        description: Optional free-text description stored in the definition.
        publisher: Prefix of the ``id`` (``"<publisher>:<name>"``). Lowercase
            letters, digits, ``_`` and ``-``, starting with a letter.

    Returns:
        The complete labware definition as a dict, including the Hamilton
        ``customAttributes`` VENUS needs to generate its own container file.

    Raises:
        ValueError: If ``tube`` does not have a circular opening.
    """
    opening = tube["openingDimensions"]
    if opening["shape"] != "circle":
        raise ValueError("a tube needs a circular opening; build it with round_well")
    diameter = opening["diameter"]
    height = tube["totalDepth"]

    tube = copy.deepcopy(tube)
    _apply_height_defaults(tube, height)

    definition: dict[str, Any] = {
        "$schema": SCHEMA_URN,
        "id": f"{publisher}:{name}",
        "schemaVersion": SCHEMA_VERSION,
        "displayName": name,
    }
    if description:
        definition["description"] = description
    definition.update(
        {
            "labwareClass": "tube",
            "source": {"system": "manual"},
            "dimensions": {"x": diameter, "y": diameter, "z": height},
            "material": material,
            "containerGrids": {
                "default": {
                    "columns": 1,
                    "rows": 1,
                    "columnPitch": diameter,
                    "rowPitch": diameter,
                    "iterationOrder": "row_major",
                    "firstContainerCenter": {
                        "x": diameter / 2,
                        "y": diameter / 2,
                        "z": tube["bottomWallThickness"],
                    },
                    "containerDefinition": tube,
                }
            },
            # Tubes mate with a rack position by their diameter rounded to a whole millimetre.
            "alignmentFeatures": [
                {"name": f"tube_{int(diameter + 0.5)}", "offset": {"z": height - _TUBE_ALIGNMENT_DROP}}
            ],
            "visualModel": {"opacity": 0},
            "customAttributes": {"hamilton:is_user_defined": {"value": True}},
        }
    )
    return definition
