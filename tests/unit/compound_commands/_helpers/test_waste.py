"""Unit tests for ``resolve_waste_position`` in ``compound_commands._helpers._waste``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hamilton_venus.compound_commands._helpers._waste import resolve_waste_position
from hamilton_venus.exceptions import VenusCommandFailedError
from hamilton_venus.models.position import LabwareLayoutSpec, Position


def _make_client(*, labware_cmd_fails: bool = False) -> MagicMock:
    client = MagicMock()
    if labware_cmd_fails:
        _mock_resp = MagicMock(
            action_name="labware.getLabwareParamsFromID",
            return_status="Failure",
            return_code=1,
            return_parameters={},
        )
        client.get_labware_spec.side_effect = VenusCommandFailedError(_mock_resp)
    else:
        spec = LabwareLayoutSpec.from_definition({"rack_layout": {"rows": 1, "columns": 1}})
        client.get_labware_spec.side_effect = lambda _lid: spec
    return client


class TestResolveWastePosition:
    def test_returns_first_position(self):
        client = _make_client()
        result = resolve_waste_position(client)
        assert isinstance(result, Position)
        assert result.labware == "liquid_waste"

    def test_queries_liquid_waste_labware(self):
        client = _make_client()
        resolve_waste_position(client)
        client.get_labware_spec.assert_called_with("liquid_waste")

    def test_raises_value_error_when_labware_not_on_deck(self):
        client = _make_client(labware_cmd_fails=True)
        with pytest.raises(ValueError, match="liquid_waste"):
            resolve_waste_position(client)

    def test_default_error_message_suggests_explicit_location(self):
        client = _make_client(labware_cmd_fails=True)
        with pytest.raises(ValueError, match="explicit waste location"):
            resolve_waste_position(client)

    def test_raises_value_error_when_labware_has_no_positions(self):
        client = MagicMock()
        with (
            patch(
                "hamilton_venus.compound_commands._helpers._waste.resolve_selector_positions",
                return_value=[],
            ),
            pytest.raises(ValueError, match="no positions"),
        ):
            resolve_waste_position(client)


class TestResolveWastePositionSelectorOverride:
    def test_uses_explicit_selector_when_provided(self):
        client = MagicMock()
        override = Position(labware="MyWaste", well="A1")
        with patch(
            "hamilton_venus.compound_commands._helpers._waste.resolve_selector_positions",
            return_value=[override],
        ) as mock_resolve:
            result = resolve_waste_position(client, "MyWaste@A1")
        assert result is override
        mock_resolve.assert_called_once_with(client, "MyWaste@A1")

    def test_none_selector_falls_back_to_liquid_waste(self):
        client = MagicMock()
        with patch(
            "hamilton_venus.compound_commands._helpers._waste.resolve_selector_positions",
            return_value=[Position(labware="liquid_waste", well="A1")],
        ) as mock_resolve:
            resolve_waste_position(client, None)
        mock_resolve.assert_called_once_with(client, "liquid_waste")

    def test_override_error_message_names_selector(self):
        client = MagicMock()
        resp = MagicMock(return_status="Failure", return_code=1, return_parameters={})
        with (
            patch(
                "hamilton_venus.compound_commands._helpers._waste.resolve_selector_positions",
                side_effect=VenusCommandFailedError(resp),
            ),
            pytest.raises(ValueError, match="MyWaste@A1"),
        ):
            resolve_waste_position(client, "MyWaste@A1")
