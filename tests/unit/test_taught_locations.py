"""Unit tests for :mod:`hamilton_venus.taught_locations`."""

from __future__ import annotations

import json

import pytest

from hamilton_venus import taught_locations as tl


@pytest.fixture
def store(tmp_path):
    return tmp_path / "TaughtLocations.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_filename_matches_tracking_json_convention():
    assert tl.DEFAULT_FILENAME == "TaughtLocations.json"


class TestCarrierSiteKey:
    def test_stringifies_and_lowercases(self):
        assert tl.carrier_site_key("CAR_1", 3) == "car_1/3"
        assert tl.carrier_site_key("car_1", "3") == "car_1/3"
        assert tl.carrier_site_key("Car_A", "B1") == "car_a/b1"


class TestNormalization:
    def test_identifiers_are_stored_lowercase(self, store):
        offset = tl.register_taught_offset("CAR_A", "S1", dx=0.1, dy=0.2, dz=0.3, path=store)
        position = tl.register_taught_position("Plate1", "CAR_A", "S1", x=1.0, y=2.0, z=3.0, path=store)

        assert (offset.carrier, offset.site) == ("car_a", "s1")
        assert (position.labware, position.carrier, position.site) == ("plate1", "car_a", "s1")

        data = _load(store)
        assert list(data["carrierSiteOffsets"]) == ["car_a/s1"]
        assert list(data["labwarePositions"]) == ["plate1"]
        assert list(data["labwarePositions"]["plate1"]) == ["car_a/s1"]
        assert data["labwarePositions"]["plate1"]["car_a/s1"]["labware"] == "plate1"

    def test_lookups_are_case_insensitive(self, store):
        tl.register_taught_offset("car_a", "s1", dx=0.1, dy=0.2, dz=0.3, path=store)
        tl.register_taught_position("plate1", "car_a", "s1", x=1.0, y=2.0, z=3.0, path=store)

        assert tl.get_taught_offset("CAR_A", "S1", path=store) is not None
        assert tl.get_taught_position("PLATE1", "Car_A", "s1", path=store).x == 1.0
        assert set(tl.get_taught_positions("Plate1", path=store)) == {"car_a/s1"}
        assert tl.resolve_taught_location("PLATE1", "CAR_A", "S1", path=store) is not None
        assert tl.remove_taught_position("Plate1", "CAR_A", "S1", path=store) is True
        assert tl.remove_taught_offset("CAR_A", "S1", path=store) is True

    def test_reteaching_with_different_case_overwrites_same_entry(self, store):
        tl.register_taught_position("Plate1", "CarA", "1", x=1.0, y=1.0, z=1.0, path=store)
        tl.register_taught_position("plate1", "cara", "1", x=9.0, y=1.0, z=1.0, path=store)

        by_site = _load(store)["labwarePositions"]
        assert list(by_site) == ["plate1"]
        assert list(by_site["plate1"]) == ["cara/1"]
        assert by_site["plate1"]["cara/1"]["x"] == 9.0


class TestRegister:
    def test_register_taught_offset_creates_file(self, store):
        record = tl.register_taught_offset("car_1", 3, dx=0.4, dy=-0.2, dz=0.1, path=store)

        assert record.site == "3"
        data = _load(store)
        assert data["schemaVersion"] == tl.SCHEMA_VERSION
        assert data["labwarePositions"] == {}
        entry = data["carrierSiteOffsets"]["car_1/3"]
        assert entry["dx"] == 0.4
        assert entry["dAngle"] == 0.0
        assert entry["recordedUtc"].endswith("Z")

    def test_register_taught_position_is_nested_by_carrier_site(self, store):
        tl.register_taught_position("plate_01", "car_1", 3, x=123.4, y=210.9, z=95.2, path=store)

        entry = _load(store)["labwarePositions"]["plate_01"]["car_1/3"]
        assert entry["labware"] == "plate_01"
        assert entry["carrier"] == "car_1"
        assert entry["site"] == "3"
        assert (entry["x"], entry["y"], entry["z"], entry["angle"]) == (123.4, 210.9, 95.2, 0.0)

    def test_same_plate_can_hold_positions_for_several_sites(self, store):
        tl.register_taught_position("plate_01", "car_a", 1, x=1.0, y=1.0, z=1.0, path=store)
        tl.register_taught_position("plate_01", "car_a", 2, x=2.0, y=2.0, z=2.0, path=store)

        by_site = _load(store)["labwarePositions"]["plate_01"]
        assert set(by_site) == {"car_a/1", "car_a/2"}
        assert by_site["car_a/1"]["x"] == 1.0
        assert by_site["car_a/2"]["x"] == 2.0

    def test_latest_write_wins_for_same_plate_and_site(self, store):
        tl.register_taught_position("plate_01", "car_1", 3, x=1.0, y=2.0, z=3.0, path=store)
        tl.register_taught_position("plate_01", "car_1", 3, x=9.0, y=2.0, z=3.0, path=store)

        by_site = _load(store)["labwarePositions"]["plate_01"]
        assert list(by_site) == ["car_1/3"]
        assert by_site["car_1/3"]["x"] == 9.0

    def test_parent_directory_is_created(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist" / "TaughtLocations.json"
        tl.register_taught_offset("car_1", 1, dx=0.0, dy=0.0, dz=0.0, path=nested)
        assert nested.is_file()


class TestLookups:
    def test_get_taught_locations_missing_file_is_empty(self, store):
        doc = tl.get_taught_locations(path=store)
        assert doc.labware_positions == {}
        assert doc.carrier_site_offsets == {}
        assert not store.exists()

    def test_direct_getters_hit_and_miss(self, store):
        tl.register_taught_offset("car_1", 3, dx=0.4, dy=-0.2, dz=0.1, path=store)
        tl.register_taught_position("plate_01", "car_1", 3, x=1.0, y=2.0, z=3.0, path=store)

        assert tl.get_taught_offset("car_1", 3, path=store).dz == 0.1
        assert tl.get_taught_offset("car_9", 9, path=store) is None
        assert tl.get_taught_position("plate_01", "car_1", "3", path=store).x == 1.0
        assert tl.get_taught_position("plate_01", "car_1", 9, path=store) is None
        assert tl.get_taught_position("nope", "car_1", 3, path=store) is None

    def test_get_taught_positions_returns_inner_map(self, store):
        tl.register_taught_position("plate_01", "car_a", 1, x=1.0, y=1.0, z=1.0, path=store)
        tl.register_taught_position("plate_01", "car_a", 2, x=2.0, y=2.0, z=2.0, path=store)

        positions = tl.get_taught_positions("plate_01", path=store)
        assert set(positions) == {"car_a/1", "car_a/2"}
        assert tl.get_taught_positions("unknown", path=store) == {}

    def test_resolve_prefers_labware_at_site_then_falls_back(self, store):
        tl.register_taught_offset("car_1", 3, dx=0.4, dy=-0.2, dz=0.1, path=store)
        tl.register_taught_position("plate_01", "car_1", 3, x=1.0, y=2.0, z=3.0, path=store)

        assert isinstance(
            tl.resolve_taught_location("plate_01", "car_1", 3, path=store), tl.LabwarePosition
        )
        # right plate, wrong site: no car_1/9 record of either kind
        assert tl.resolve_taught_location("plate_01", "car_1", 9, path=store) is None
        # unknown plate at a taught site: falls back to the carrier/site offset
        assert isinstance(
            tl.resolve_taught_location("other", "car_1", 3, path=store), tl.CarrierSiteOffset
        )
        assert tl.resolve_taught_location("other", "car_9", 9, path=store) is None


class TestRemoveAndClear:
    def test_remove_taught_offset(self, store):
        tl.register_taught_offset("car_1", 3, dx=0.4, dy=-0.2, dz=0.1, path=store)
        assert tl.remove_taught_offset("car_1", 3, path=store) is True
        assert tl.remove_taught_offset("car_1", 3, path=store) is False
        assert _load(store)["carrierSiteOffsets"] == {}

    def test_remove_one_plate_site_combo(self, store):
        tl.register_taught_position("plate_01", "car_a", 1, x=1.0, y=1.0, z=1.0, path=store)
        tl.register_taught_position("plate_01", "car_a", 2, x=2.0, y=2.0, z=2.0, path=store)

        assert tl.remove_taught_position("plate_01", "car_a", 1, path=store) is True
        assert tl.remove_taught_position("plate_01", "car_a", 1, path=store) is False
        assert set(_load(store)["labwarePositions"]["plate_01"]) == {"car_a/2"}

    def test_remove_last_combo_drops_the_plate_key(self, store):
        tl.register_taught_position("plate_01", "car_a", 1, x=1.0, y=1.0, z=1.0, path=store)
        assert tl.remove_taught_position("plate_01", "car_a", 1, path=store) is True
        assert _load(store)["labwarePositions"] == {}

    def test_remove_all_positions_for_a_plate(self, store):
        tl.register_taught_position("plate_01", "car_a", 1, x=1.0, y=1.0, z=1.0, path=store)
        tl.register_taught_position("plate_01", "car_a", 2, x=2.0, y=2.0, z=2.0, path=store)

        assert tl.remove_taught_position("plate_01", path=store) is True
        assert tl.remove_taught_position("plate_01", path=store) is False
        assert _load(store)["labwarePositions"] == {}

    def test_remove_taught_position_rejects_partial_key(self, store):
        with pytest.raises(ValueError, match="both 'carrier' and 'site'"):
            tl.remove_taught_position("plate_01", "car_a", path=store)

    def test_clear_empties_both_maps_but_keeps_schema(self, store):
        tl.register_taught_offset("car_1", 3, dx=0.4, dy=-0.2, dz=0.1, path=store)
        tl.register_taught_position("plate_01", "car_1", 3, x=1.0, y=2.0, z=3.0, path=store)

        tl.clear_taught_locations(path=store)

        data = _load(store)
        assert data == {"schemaVersion": tl.SCHEMA_VERSION, "labwarePositions": {}, "carrierSiteOffsets": {}}


class TestCorruptFile:
    def test_invalid_json_raises_value_error_naming_path(self, store):
        store.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match=str(store).replace("\\", "\\\\")):
            tl.get_taught_locations(path=store)

    def test_wrong_shape_raises_and_does_not_clobber(self, store):
        store.write_text(
            '{"labwarePositions": {"plate_01": {"car_1/3": {"x": "oops"}}}}', encoding="utf-8"
        )
        with pytest.raises(ValueError):
            tl.register_taught_position("plate_02", "car_1", 3, x=1.0, y=2.0, z=3.0, path=store)
        assert "oops" in store.read_text(encoding="utf-8")

    def test_json_array_rejected(self, store):
        store.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a JSON object"):
            tl.get_taught_locations(path=store)

    def test_blank_file_reads_as_empty(self, store):
        store.write_text("   \n", encoding="utf-8")
        assert tl.get_taught_locations(path=store).labware_positions == {}
