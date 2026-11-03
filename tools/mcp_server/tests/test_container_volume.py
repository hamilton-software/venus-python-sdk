"""Tests for script_runs.container_volume: shape-volume math, pooled-vs-per-well capacity, and
the reservoir/definition cache. Built entirely against the real hamilton_venus pydantic models
(no fakes), so a schema drift in VolumeSegment/LabwareDefinition breaks these tests directly.
"""

from __future__ import annotations

import math
import unittest

from hamilton_venus.models.labware_definition import (
    ContainerGrid,
    LabwareDefinition,
    V1ContainerDefinition,
    VolumeModel,
    VolumeSegment,
)

from hamilton_venus_mcp.script_runs.container_volume import (
    LabwareGeometryCache,
    container_max_volume_ul,
    is_reservoir,
    segment_volume_ul,
)


def definition(labware_class: str, *, rows: int = 1, columns: int = 1, segments=(), pitch: float = 9.0) -> LabwareDefinition:
    grid = ContainerGrid(
        rows=rows,
        columns=columns,
        row_pitch=pitch,
        column_pitch=pitch,
        container_definition=V1ContainerDefinition(volume_model=VolumeModel(segments=list(segments))),
    )
    return LabwareDefinition(labware_class=labware_class, container_grids={"default": grid})


class SegmentVolumeTests(unittest.TestCase):
    def test_cylinder(self):
        vol = segment_volume_ul(VolumeSegment(type="cylinder", height=10.0, diameter=6.0))
        self.assertAlmostEqual(vol, math.pi * 3.0 * 3.0 * 10.0, places=6)

    def test_rectangular_prism(self):
        vol = segment_volume_ul(VolumeSegment(type="rectangular_prism", height=5.0, width=4.0, depth=3.0))
        self.assertAlmostEqual(vol, 4.0 * 3.0 * 5.0, places=6)

    def test_conical_frustum(self):
        vol = segment_volume_ul(VolumeSegment(type="conical_frustum", height=12.0, diameter_bottom=0.0, diameter_top=10.0))
        # A frustum tapering to a point (bottom diameter 0) is a cone: V = (pi/3) r^2 h.
        self.assertAlmostEqual(vol, (math.pi / 3.0) * 5.0 * 5.0 * 12.0, places=4)

    def test_rectangular_frustum(self):
        vol = segment_volume_ul(
            VolumeSegment(type="rectangular_frustum", height=6.0, width_bottom=2.0, depth_bottom=2.0, width_top=4.0, depth_top=4.0)
        )
        a1, a2 = 4.0, 16.0
        self.assertAlmostEqual(vol, (6.0 / 3.0) * (a1 + a2 + math.sqrt(a1 * a2)), places=6)

    def test_spherical_cap(self):
        vol = segment_volume_ul(VolumeSegment(type="spherical_cap", height=2.0, diameter=8.0))
        a = 4.0
        self.assertAlmostEqual(vol, (math.pi * 2.0 / 6.0) * (3 * a * a + 2.0 * 2.0), places=6)

    def test_unknown_shape_is_zero_not_an_error(self):
        self.assertEqual(segment_volume_ul(VolumeSegment(type="a_future_shape", height=5.0, diameter=1.0)), 0.0)

    def test_zero_or_missing_height_is_zero(self):
        self.assertEqual(segment_volume_ul(VolumeSegment(type="cylinder", height=0.0, diameter=6.0)), 0.0)
        self.assertEqual(segment_volume_ul(VolumeSegment(type="cylinder", diameter=6.0)), 0.0)

    def test_missing_shape_fields_degrade_to_zero_not_a_crash(self):
        # A cylinder with no diameter at all -- treated as radius 0, not a TypeError.
        self.assertEqual(segment_volume_ul(VolumeSegment(type="cylinder", height=5.0)), 0.0)


class IsReservoirTests(unittest.TestCase):
    def test_reservoir_class_is_true(self):
        self.assertTrue(is_reservoir(definition("reservoir")))
        self.assertTrue(is_reservoir(definition("Reservoir")))  # case-insensitive
        self.assertTrue(is_reservoir(definition("  reservoir  ")))  # tolerant of whitespace

    def test_other_classes_are_false(self):
        for kind in ("plate", "tube_rack", "tip_rack", ""):
            with self.subTest(kind=kind):
                self.assertFalse(is_reservoir(definition(kind)))

    def test_none_definition_is_false(self):
        self.assertFalse(is_reservoir(None))


class ContainerMaxVolumeTests(unittest.TestCase):
    def test_none_definition_is_none(self):
        self.assertIsNone(container_max_volume_ul(None))

    def test_no_segments_is_none(self):
        self.assertIsNone(container_max_volume_ul(definition("plate", segments=[])))

    def test_per_well_labware_uses_one_cell_only(self):
        cylinder = VolumeSegment(type="cylinder", height=10.0, diameter=6.0)
        cell = segment_volume_ul(cylinder)
        d = definition("plate", rows=8, columns=12, segments=[cylinder])
        # A plate has 96 wells, but a non-reservoir is tracked per well: capacity == one cell.
        self.assertAlmostEqual(container_max_volume_ul(d), cell, places=6)

    def test_reservoir_sums_every_cell_in_the_grid(self):
        cylinder = VolumeSegment(type="cylinder", height=10.0, diameter=6.0)
        cell = segment_volume_ul(cylinder)
        d = definition("reservoir", rows=1, columns=8, segments=[cylinder])
        self.assertAlmostEqual(container_max_volume_ul(d), cell * 8, places=6)

    def test_stacked_segments_within_one_cell_are_summed(self):
        # A tube: a conical bottom plus a cylindrical body -- both segments belong to the SAME
        # well, so their volumes add, unlike separate grid cells.
        cone = VolumeSegment(type="conical_frustum", height=12.0, diameter_bottom=0.0, diameter_top=10.0)
        cyl = VolumeSegment(type="cylinder", height=20.0, diameter=10.0)
        d = definition("tube", rows=1, columns=1, segments=[cone, cyl])
        self.assertAlmostEqual(container_max_volume_ul(d), segment_volume_ul(cone) + segment_volume_ul(cyl), places=4)

    def test_a_grid_whose_segments_sum_to_zero_is_none(self):
        d = definition("plate", segments=[VolumeSegment(type="cylinder", height=0.0)])
        self.assertIsNone(container_max_volume_ul(d))

    def test_multiple_grids_only_the_first_nonzero_wins_for_per_well(self):
        # Multi-grid (irregular) labware: a per-well labware still returns one cell's volume,
        # not a sum across grids -- mirrors the reference implementation's "break on first hit".
        cyl = VolumeSegment(type="cylinder", height=10.0, diameter=6.0)
        grid_a = ContainerGrid(rows=1, columns=1, container_definition=V1ContainerDefinition(volume_model=VolumeModel(segments=[cyl])))
        grid_b = ContainerGrid(rows=1, columns=1, container_definition=V1ContainerDefinition(volume_model=VolumeModel(segments=[])))
        d = LabwareDefinition(labware_class="tube_rack", container_grids={"a": grid_a, "b": grid_b})
        self.assertAlmostEqual(container_max_volume_ul(d), segment_volume_ul(cyl), places=6)


class LabwareGeometryCacheTests(unittest.TestCase):
    def test_definition_is_fetched_once_per_labware_id(self):
        calls = []

        def get_definition(labware_id):
            calls.append(labware_id)
            return definition("reservoir", rows=1, columns=4, segments=[VolumeSegment(type="cylinder", height=10.0, diameter=6.0)])

        cache = LabwareGeometryCache(get_definition)
        for _ in range(3):
            cache.definition("Trough1")
            cache.is_reservoir("Trough1")
            cache.max_volume_ul("Trough1")
        self.assertEqual(calls, ["Trough1"])

    def test_different_labware_ids_are_cached_independently(self):
        def get_definition(labware_id):
            return definition("reservoir" if labware_id == "Trough1" else "plate")

        cache = LabwareGeometryCache(get_definition)
        self.assertTrue(cache.is_reservoir("Trough1"))
        self.assertFalse(cache.is_reservoir("Plate1"))

    def test_a_lookup_failure_is_cached_as_unknown_not_retried_forever(self):
        calls = []

        def get_definition(labware_id):
            calls.append(labware_id)
            raise RuntimeError("VENUS unreachable")

        cache = LabwareGeometryCache(get_definition)
        for _ in range(3):
            self.assertIsNone(cache.definition("X"))
            self.assertFalse(cache.is_reservoir("X"))
            self.assertIsNone(cache.max_volume_ul("X"))
        self.assertEqual(calls, ["X"])

    def test_none_returned_from_lookup_is_a_normal_miss(self):
        cache = LabwareGeometryCache(lambda _labware_id: None)
        self.assertIsNone(cache.definition("X"))
        self.assertFalse(cache.is_reservoir("X"))
        self.assertIsNone(cache.max_volume_ul("X"))


if __name__ == "__main__":
    unittest.main()
