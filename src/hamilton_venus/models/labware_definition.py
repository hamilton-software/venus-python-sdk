"""Pydantic models for VENUS labware definition payloads.

Covers the ``urn:hamilton:schemas:microlab:labware:v1`` JSON structure
(``labwareClass`` / ``containerGrids`` / ``volumeModel``) used by all
labware in the current library.  :class:`LabwareDefinition` can be passed
directly to
:meth:`~hamilton_venus.models.position.LabwareLayoutSpec.from_definition`
to extract grid dimensions and well spacing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _V1Model(BaseModel):
    """Base for ``labware:v1`` models: camelCase wire aliases, immutable."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class Point3D(_V1Model):
    """A point or offset in labware coordinates; omitted axes default to 0."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class LabwareSource(_V1Model):
    """Provenance recorded by the legacy-to-v1 labware converter."""

    system: str = ""
    original_id: str = ""
    original_file: str = ""
    converted_date: str = ""
    converted_by: str = ""
    notes: str = ""


class NamingConvention(_V1Model):
    """How container addresses are composed, e.g. ``A1`` vs ``1``."""

    row_style: str = "alpha"
    column_style: str = "numeric"
    format: str = "[row][col]"


class OpeningDimensions(_V1Model):
    """Container opening: ``diameter`` for circles, ``width``/``depth`` for rectangles."""

    shape: str = ""
    diameter: float | None = None
    width: float | None = None
    depth: float | None = None


class VolumeSegment(_V1Model):
    """One geometric segment of a container's volume profile.

    ``type`` selects which of the fields below apply:
    ``cylinder`` (diameter), ``rectangular_prism`` (width, depth),
    ``conical_frustum`` (diameter_bottom, diameter_top),
    ``rectangular_frustum`` (width/depth_bottom, width/depth_top), and
    ``spherical_cap`` (diameter, of the cap's flat base).
    """

    type: str = ""
    height: float = 0.0
    diameter: float | None = None
    diameter_bottom: float | None = None
    diameter_top: float | None = None
    width: float | None = None
    depth: float | None = None
    width_bottom: float | None = None
    width_top: float | None = None
    depth_bottom: float | None = None
    depth_top: float | None = None


class VolumeModel(_V1Model):
    """Stacked segments describing container volume as a function of height."""

    segments: list[VolumeSegment] = Field(default_factory=list)


class LiquidDetection(_V1Model):
    """Liquid-level detection capability for a container."""

    supports_lld: bool = Field(default=False, alias="supportsLLD")
    liquid_seeking_start_height: float = 0.0


class AlignmentFeature(_V1Model):
    """A named alignment/mating feature and its offset."""

    name: str = ""
    offset: Point3D = Field(default_factory=Point3D)


class V1ContainerDefinition(_V1Model):
    """Geometry and pipetting properties of the container in a grid."""

    opening_dimensions: OpeningDimensions = Field(default_factory=OpeningDimensions)
    total_depth: float = 0.0
    max_pipetting_depth: float = 0.0
    bottom_wall_thickness: float = 0.0
    volume_model: VolumeModel = Field(default_factory=VolumeModel)
    liquid_detection: LiquidDetection = Field(default_factory=LiquidDetection)
    contents_ref: str | None = None
    alignment_receptacles: list[AlignmentFeature] = Field(default_factory=list)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)


class ContainerGrid(_V1Model):
    """A uniform-pitch grid of identical containers.

    Irregular labware is expressed as several grids rather than the legacy
    ``irregular_wells`` list.
    """

    rows: int = 0
    columns: int = 0
    row_pitch: float = 0.0
    column_pitch: float = 0.0
    iteration_order: str = "column_major"
    first_container_center: Point3D = Field(default_factory=Point3D)
    naming_convention: NamingConvention = Field(default_factory=NamingConvention)
    container_definition: V1ContainerDefinition = Field(default_factory=V1ContainerDefinition)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)


class ConnectedContainerGroup(_V1Model):
    """Grids whose containers share one physical cavity, e.g. a trough."""

    containers: list[str] = Field(default_factory=list)
    connection_topology: str = ""


class CollisionShape(_V1Model):
    """One solid body used for collision checking."""

    shape: dict[str, Any] = Field(default_factory=dict)
    origin: Point3D = Field(default_factory=Point3D)


class SelfStack(_V1Model):
    """Height added per unit when this labware is stacked on itself."""

    height: float = 0.0


class TipRackInfo(_V1Model):
    """Tip-rack-specific attributes."""

    style: str = ""


class VisualModel(_V1Model):
    """Rendering hints: colour, opacity, and 3D model references."""

    color: str = ""
    opacity: float = 0.0
    preview_image_ref: str | None = None
    model_ref: str | None = None
    model_format: str | None = None
    # Named reference corner, e.g. "left_front_bottom".
    model_origin: str | None = None
    model_offset: Point3D | None = None


class LabwareDefinition(BaseModel):
    """Typed model for a ``urn:hamilton:schemas:microlab:labware:v1`` payload.

    Covers container-bearing labware: plates, reservoirs, tip racks, tubes,
    and tube racks.  Carriers, adapters, and lids use a different structure
    and are **not** represented by this model.
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )

    schema_: str = Field(default="", alias="$schema")
    id: str = ""
    schema_version: str = ""
    display_name: str = ""
    description: str = ""
    labware_class: str = ""
    source: LabwareSource = Field(default_factory=LabwareSource)
    material: str = ""
    dimensions: Point3D = Field(default_factory=Point3D)
    container_grids: dict[str, ContainerGrid] = Field(default_factory=dict)
    connected_container_groups: dict[str, ConnectedContainerGroup] = Field(default_factory=dict)
    alignment_features: list[AlignmentFeature] = Field(default_factory=list)
    collision_shapes: dict[str, CollisionShape] = Field(default_factory=dict)
    self_stack: SelfStack | None = None
    tip_rack: TipRackInfo | None = None
    visual_model: VisualModel | None = None
    custom_attributes: dict[str, Any] = Field(default_factory=dict)


def dump_labware_definition(definition: LabwareDefinition | dict[str, Any]) -> dict[str, Any]:
    """Serialize a labware definition to the JSON shape VENUS expects."""
    if isinstance(definition, LabwareDefinition):
        # Unset optional blocks are dropped rather than sent as nulls, which VENUS rejects.
        return definition.model_dump(by_alias=True, exclude_none=True)
    return definition


