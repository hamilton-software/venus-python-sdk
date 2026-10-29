"""Unit tests for the SDK-side liquid class push (``_LiquidClassSync``).

The VENUS method no longer imports liquid classes itself, so the SDK pushes custom
ones before the commands that use them: never originals, once per session for a
custom class, and again whenever its JSON changes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hamilton_venus._internal._liquid_class_sync import _LiquidClassSync, liquid_class_names, liquid_class_names_in
from hamilton_venus._internal._run_message_command_dispatcher import _RunMessageCommandDispatcher
from hamilton_venus.exceptions import LiquidClassPushError, VenusCommandFailedError
from hamilton_venus.models import CommandResponse


def _write(root: Path, rel: str, name: str, body: dict[str, Any] | None = None) -> Path:
    path = root / "STAR" / rel / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": name, **(body or {})}), encoding="utf-8")
    return path


def _ok(**return_parameters: Any) -> CommandResponse:
    return CommandResponse(return_status="Success", return_parameters=return_parameters)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Liquid Class"
    _write(root, "System/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "StandardVolume_Water_DispenseJet_Empty")
    _write(root, "User/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "MyWater", {"flow": 100})
    _write(root, "User/Channels_1000ul/Tip_300ul/Serum/Jet_Empty", "MySerum", {"flow": 50})
    _write(root, "User/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "TipCheck_300", {"v": 1})
    _write(root, "User/Head_96/Tip_300ul/Water/Jet_Empty", "TipCheck_300", {"v": 1})
    return root


def _sync(root: Path) -> tuple[_LiquidClassSync, AsyncMock]:
    push = AsyncMock(return_value=_ok(importedClasses=[], skippedOriginals=[], failedImports=[]))
    return _LiquidClassSync(root, "STAR", push), push


class TestNames:
    def test_flattens_names_and_per_channel_lists(self):
        assert liquid_class_names("A") == ["A"]
        assert liquid_class_names(["A", ["B", ""], None]) == ["A", "B"]
        assert liquid_class_names(None) == []

    def test_finds_liquid_class_values_at_any_depth(self):
        params = {"liquidClass": ["A", "B"], "steps": [{"liquidClass": "C"}], "names": ["not-a-liquid-class"]}
        assert liquid_class_names_in(params) == ["A", "B", "C"]
        assert liquid_class_names_in({"channels": [1, 2]}) == []


class TestEnsure:
    @pytest.mark.asyncio
    async def test_original_is_never_pushed(self, library):
        sync, push = _sync(library)
        await sync.ensure(["StandardVolume_Water_DispenseJet_Empty"])
        push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_pushed_once_while_unchanged(self, library):
        sync, push = _sync(library)
        await sync.ensure(["MyWater"])
        await sync.ensure(["MyWater"])
        push.assert_awaited_once_with(["MyWater"])

    @pytest.mark.asyncio
    async def test_edited_custom_is_pushed_again_once(self, library):
        sync, push = _sync(library)
        await sync.ensure(["MyWater"])
        _write(library, "User/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "MyWater", {"flow": 120})
        await sync.ensure(["MyWater"])
        await sync.ensure(["MyWater"])
        assert push.await_count == 2

    @pytest.mark.asyncio
    async def test_changed_names_go_out_in_one_push(self, library):
        sync, push = _sync(library)
        await sync.ensure(["MyWater", "StandardVolume_Water_DispenseJet_Empty", "MySerum", "MyWater"])
        push.assert_awaited_once_with(["MyWater", "MySerum"])

    @pytest.mark.asyncio
    async def test_name_in_two_folders_is_hashed_together(self, library):
        sync, push = _sync(library)
        await sync.ensure(["TipCheck_300"])
        # Only the 96-head copy changes -- still a different liquid class for VENUS.
        _write(library, "User/Head_96/Tip_300ul/Water/Jet_Empty", "TipCheck_300", {"v": 2})
        await sync.ensure(["TipCheck_300"])
        assert push.await_count == 2

    @pytest.mark.asyncio
    async def test_unknown_name_not_pushed_until_its_file_appears(self, library):
        sync, push = _sync(library)
        await sync.ensure(["NewOne"])
        push.assert_not_awaited()
        _write(library, "User/Channels_1000ul/Tip_300ul/Water/Jet_Empty", "NewOne")
        await sync.ensure(["NewOne"])
        push.assert_awaited_once_with(["NewOne"])

    @pytest.mark.asyncio
    async def test_held_name_is_skipped_until_released(self, library):
        sync, push = _sync(library)
        with sync.hold(["MyWater"]):
            await sync.ensure(["MyWater"])
        push.assert_not_awaited()
        await sync.ensure(["MyWater"])
        push.assert_awaited_once_with(["MyWater"])

    @pytest.mark.asyncio
    async def test_failed_import_raises(self, library):
        push = AsyncMock(return_value=_ok(failedImports=[{"name": "MyWater", "message": "bad flow rate"}]))
        sync = _LiquidClassSync(library, "STAR", push)
        with pytest.raises(LiquidClassPushError, match="MyWater: bad flow rate"):
            await sync.ensure(["MyWater"])
        # Not recorded as pushed: the next command tries again.
        push.return_value = _ok(failedImports=[])
        await sync.ensure(["MyWater"])
        assert push.await_count == 2

    @pytest.mark.asyncio
    async def test_failed_push_command_raises_liquid_class_push_error(self, library):
        push = AsyncMock(side_effect=VenusCommandFailedError(CommandResponse(return_status="Error")))
        sync = _LiquidClassSync(library, "STAR", push)
        with pytest.raises(LiquidClassPushError):
            await sync.ensure(["MyWater"])

    @pytest.mark.asyncio
    async def test_without_local_library_each_name_pushed_once(self, tmp_path):
        sync, push = _sync(tmp_path / "not-here")
        await sync.ensure(["A", "B"])
        await sync.ensure(["A", "C"])
        assert [call.args[0] for call in push.await_args_list] == [["A", "B"], ["C"]]

    @pytest.mark.asyncio
    async def test_record_pushed_skips_the_next_push(self, library):
        sync, push = _sync(library)
        sync.record_pushed(["MyWater"])
        await sync.ensure(["MyWater"])
        push.assert_not_awaited()


class TestBeforeCommandHook:
    @pytest.mark.asyncio
    async def test_hook_runs_before_the_command_is_sent(self):
        order: list[str] = []
        request = AsyncMock(side_effect=AssertionError("stop after hook"))

        async def hook(category, action_name, parameters):
            order.append(f"hook {action_name} {parameters.get('liquidClass')}")

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher.set_before_command(hook)
        with pytest.raises(AssertionError, match="stop after hook"):
            await dispatcher.send_command("Channels", "aspirate", {"liquidClass": "MyWater"}, default_timeout=1.0)

        assert order == ["hook aspirate MyWater"]

    @pytest.mark.asyncio
    async def test_hook_exception_means_nothing_is_sent(self):
        request = AsyncMock()

        async def hook(category, action_name, parameters):
            raise LiquidClassPushError("bad")

        dispatcher = _RunMessageCommandDispatcher(request)
        dispatcher.set_before_command(hook)
        with pytest.raises(LiquidClassPushError):
            await dispatcher.send_command("Channels", "aspirate", {"liquidClass": "X"}, default_timeout=1.0)
        request.assert_not_awaited()


class TestCompoundCommandPushOnce:
    @staticmethod
    def _client(sync: _LiquidClassSync) -> MagicMock:
        from hamilton_venus._internal._base_instrument_client import _InstrumentSyncClientBase

        client = MagicMock()
        client._connected_instrument.liquid_class_sync = sync
        client._run = asyncio.run
        client._liquid_classes_for_command = lambda *args: _InstrumentSyncClientBase._liquid_classes_for_command(
            client, *args
        )
        return client

    def test_compound_command_pushes_once_and_holds_its_liquid_classes(self, library, monkeypatch):
        from hamilton_venus.mixins.compound_commands.add_reagent_command import AddReagentCommand

        sync, push = _sync(library)
        held_during_execute: list[bool] = []

        def fake_execute(_client, **kwargs):
            held_during_execute.append("MyWater" in sync._held)
            # An aspirate inside the compound would call ensure(); the held name is skipped.
            asyncio.run(sync.ensure(["MyWater"]))
            return "done"

        monkeypatch.setattr("hamilton_venus.compound_commands.add_reagent.execute_add_reagent", fake_execute)
        result = AddReagentCommand.add_reagent(
            self._client(sync),
            reagent_source="Trough",
            dest_plate="Plate",
            volume=10.0,
            tip_pool="tips",
            liquid_class=["MyWater", "MyWater"],
        )

        assert result == "done"
        assert held_during_execute == [True]
        push.assert_awaited_once_with(["MyWater"])
        assert sync._held == {}

    def test_serial_dilution_pushes_both_liquid_classes_in_one_call(self, library, monkeypatch):
        from hamilton_venus.mixins.compound_commands.serial_dilution_command import SerialDilutionCommand

        sync, push = _sync(library)
        monkeypatch.setattr(
            "hamilton_venus.compound_commands.serial_dilution.execute_serial_dilution_by_volume",
            lambda _client, **kwargs: "done",
        )
        SerialDilutionCommand.serial_dilution_by_volume(
            self._client(sync),
            plate_id="Plate",
            start_column=1,
            num_dilutions=3,
            diluent_source="Trough",
            diluent_volume=50.0,
            transfer_volume=50.0,
            transfer_tip_pool="tips",
            diluent_liquid_class="MySerum",
            transfer_liquid_class="MyWater",
        )

        push.assert_awaited_once_with(["MySerum", "MyWater"])
