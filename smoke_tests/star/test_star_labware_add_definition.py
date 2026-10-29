"""Add one labware definition per ``LabwareDefinition``-supported category
(plate, reservoir, tube, tube_rack); tip racks are rejected by VENUS.

Definitions must be serialized with ``model_dump(exclude_unset=True)`` --
VENUS rejects the empty-but-present optional objects ``exclude_none`` leaves
behind.
"""

import contextlib

from hamilton_venus import StarClient, VenusCommandFailedError, VenusError, VenusTimeoutError
from hamilton_venus.models.labware_definition import (
    AlignmentFeature,
    ContainerGrid,
    LabwareDefinition,
    OpeningDimensions,
    Point3D,
    V1ContainerDefinition,
    VolumeModel,
    VolumeSegment,
)

SCHEMA_URN = "urn:hamilton:schemas:microlab:labware:v1"
SCHEMA_VERSION = "1.0.0-alpha.1"


def _dump(definition: LabwareDefinition) -> dict:
    """Serialize a definition, keeping only the fields it explicitly sets."""
    return definition.model_dump(by_alias=True, exclude_unset=True)


PLATE = LabwareDefinition(
    schema_=SCHEMA_URN,
    id="user:custom_plate_001",
    schema_version=SCHEMA_VERSION,
    display_name="Custom Plate 001",
    labware_class="plate",
    material="polystyrene",
    dimensions=Point3D(x=127.76, y=85.48, z=14.35),
    alignment_features=[AlignmentFeature(name="sbs_rim", offset=Point3D(z=0.0))],
    container_grids={
        "default": ContainerGrid(
            rows=8,
            columns=12,
            row_pitch=9.0,
            column_pitch=9.0,
            iteration_order="row_major",
            first_container_center=Point3D(x=14.0, y=11.5, z=3.6),
            container_definition=V1ContainerDefinition(
                opening_dimensions=OpeningDimensions(shape="circle", diameter=6.9),
                total_depth=10.9,
                bottom_wall_thickness=1.0,
                volume_model=VolumeModel(
                    segments=[VolumeSegment(type="cylinder", height=10.9, diameter=6.9)]
                ),
            ),
        )
    },
)

RESERVOIR = LabwareDefinition(
    schema_=SCHEMA_URN,
    id="user:custom_reservoir_001",
    schema_version=SCHEMA_VERSION,
    display_name="Custom Reservoir 001",
    labware_class="reservoir",
    material="polypropylene",
    dimensions=Point3D(x=127.76, y=85.48, z=42.0),
    alignment_features=[AlignmentFeature(name="sbs_rim", offset=Point3D(z=0.0))],
    container_grids={
        "default": ContainerGrid(
            rows=1,
            columns=1,
            row_pitch=0.0,
            column_pitch=0.0,
            iteration_order="row_major",
            first_container_center=Point3D(x=63.5, y=43.0, z=3.5),
            container_definition=V1ContainerDefinition(
                opening_dimensions=OpeningDimensions(shape="rectangle", width=108.0, depth=72.0),
                total_depth=38.0,
                bottom_wall_thickness=1.0,
                volume_model=VolumeModel(
                    segments=[
                        VolumeSegment(type="rectangular_prism", height=38.0, width=108.0, depth=72.0)
                    ]
                ),
            ),
        )
    },
)

TUBE = LabwareDefinition(
    schema_=SCHEMA_URN,
    id="user:custom_tube_001",
    schema_version=SCHEMA_VERSION,
    display_name="Custom Tube 001",
    labware_class="tube",
    material="polypropylene",
    dimensions=Point3D(x=14.3, y=14.3, z=73.8),
    alignment_features=[AlignmentFeature(name="tube_seat", offset=Point3D(z=0.0))],
    container_grids={
        "default": ContainerGrid(
            rows=1,
            columns=1,
            row_pitch=0.0,
            column_pitch=0.0,
            iteration_order="row_major",
            first_container_center=Point3D(x=7.15, y=7.15, z=73.8),
            container_definition=V1ContainerDefinition(
                opening_dimensions=OpeningDimensions(shape="circle", diameter=14.3),
                total_depth=73.8,
                bottom_wall_thickness=1.1,
                max_pipetting_depth=1.0,
                volume_model=VolumeModel(
                    segments=[VolumeSegment(type="cylinder", height=73.8, diameter=14.3)]
                ),
            ),
        )
    },
)

TUBE_RACK = LabwareDefinition(
    schema_=SCHEMA_URN,
    id="user:custom_tube_rack_001",
    schema_version=SCHEMA_VERSION,
    display_name="Custom Tube Rack 001",
    labware_class="tube_rack",
    material="polypropylene",
    dimensions=Point3D(x=127.76, y=85.48, z=60.0),
    alignment_features=[AlignmentFeature(name="sbs_rim", offset=Point3D(z=0.0))],
    container_grids={
        "default": ContainerGrid(
            rows=1,
            columns=1,
            row_pitch=0.0,
            column_pitch=0.0,
            iteration_order="row_major",
            first_container_center=Point3D(x=63.5, y=43.0, z=60.0),
            container_definition=V1ContainerDefinition(
                opening_dimensions=OpeningDimensions(shape="circle", diameter=14.5),
                total_depth=60.0,
                bottom_wall_thickness=1.0,
                volume_model=VolumeModel(
                    segments=[VolumeSegment(type="cylinder", height=60.0, diameter=14.5)]
                ),
            ),
        )
    },
)

LABWARE_DEFINITIONS = [
    ("CUSTOM_PLATE_001", PLATE),
    ("CUSTOM_RESERVOIR_001", RESERVOIR),
    ("CUSTOM_TUBE_001", TUBE),
    ("CUSTOM_TUBE_RACK_001", TUBE_RACK),
]

try:
    with StarClient(simulate=True) as star:
        print("Connected — method is running")

        # Make the test rerunnable: drop any leftovers from a previous run.
        for labware_name, _ in LABWARE_DEFINITIONS:
            with contextlib.suppress(VenusCommandFailedError):
                star.labware_delete_definition(labware_name)  # not present yet -- fine

        for labware_name, labware_definition in LABWARE_DEFINITIONS:
            print(f"\n--- Add Labware Definition: {labware_name} ---")
            response = star.labware_add_definition(
                labware_name=labware_name,
                labware_definition=_dump(labware_definition),
            )
            print(f"Add definition response: {response.model_dump(by_alias=True)}")

        print("\n--- Cleaning up added definitions ---")
        for labware_name, _ in LABWARE_DEFINITIONS:
            star.labware_delete_definition(labware_name)
            print(f"Deleted: {labware_name}")

        print("\nLabware Add Definition Smoke Test Complete - Disconnecting")
except VenusTimeoutError as e:
    print(f"Command timed out: {e}")
    raise SystemExit(1) from e
except VenusCommandFailedError as e:
    print(f"Command failed: {e}")
    print(f"  Return code: {e.response.return_code}")
    print(f"  Details: {e.response.return_parameters}")
    raise SystemExit(1) from e
except VenusError as e:
    print(f"Other SDK error: {e}")
    raise SystemExit(1) from e

print("Done")
