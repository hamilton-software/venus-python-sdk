"""Unit tests for hamilton_workflow_framework.run_summary (moved from
python_script_manager_app/backend/run_summary.py -- see that module's docstring)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hamilton_workflow_framework.run_summary import RunLogError, load_run_log, summarize_run


def _command_pair(command_id, action_name, category, parameters, return_parameters,
                   return_code=0, return_status="Success", status="Success"):
    request = {
        "type": "command_request",
        "source": "WebAPI",
        "direction": "Out",
        "payload": {
            "command_id": command_id,
            "category": category,
            "action_name": action_name,
            "parameters": parameters,
        },
    }
    response = {
        "type": "command_response",
        "source": "WebAPI",
        "direction": "In",
        "payload": {
            "id": command_id,
            "category": "",
            "actionName": "",
            "parameters": {},
            "status": status,
            "returnStatus": return_status,
            "returnCode": return_code,
            "returnParameters": return_parameters,
        },
    }
    return [request, response]


def _tadm_curve(liquid_class_name, step_type_name, volume, channel_number, curve_id,
                 curve_flagged=0, error=0):
    return {
        "curveId": curve_id,
        "liquidClassName": liquid_class_name,
        "stepType": 0,
        "stepTypeName": step_type_name,
        "volume": volume,
        "stepNumber": 1,
        "curvePoints": [{"timeMs": 0, "pressure": 10}, {"timeMs": 10, "pressure": 12}],
        "error": error,
        "channelNumber": channel_number,
        "tadmMode": 0,
        "curveFlagged": curve_flagged,
        "checkSum": 0,
    }


class SummarizeRunTests(unittest.TestCase):
    def _build_log(self, entries, reason="normal"):
        return {
            "schema_version": "1.0",
            "session_id": "sess1",
            "run_guid": "guid1",
            "method_name": "main.hsl",
            "sdk_version": "0.0.0",
            "script_name": "say hi.py",
            "started_at": "2026-08-06T00:00:00+00:00",
            "ended_at": "2026-08-06T00:00:12+00:00",
            "reason": reason,
            "log": entries,
        }

    def test_session_end_gives_result_duration_and_simulate(self):
        entries = [
            {
                "type": "session_start", "source": "SDK", "direction": "Out",
                "payload": {"simulate": True, "script_name": "say hi.py", "sdk_version": "0.0.0"},
            },
            {
                "type": "session_end", "source": "SDK", "direction": "Out",
                "payload": {
                    "reason": "error", "duration_seconds": 12.5, "entry_count": 2,
                    "error_type": "VenusCommandFailedError", "error_message": "boom",
                },
            },
        ]
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(summary["result"], "error")
        self.assertEqual(summary["duration_seconds"], 12.5)
        self.assertIs(summary["simulate"], True)
        self.assertEqual(summary["error_type"], "VenusCommandFailedError")
        self.assertEqual(summary["error_message"], "boom")

    def test_tips_used_counts_channel_mph96_full_and_partial_pickups(self):
        entries = []
        # Channel arm: exactly the channels named in the request.
        entries += _command_pair(
            "cmd1", "channels.1mL.tipPickup", "Instrument",
            {"channels": [1, 2, 3], "tipPool": "Pool300"}, {"remainingTips": 88},
        )
        # MPH96 full pickup: no channel list on the wire at all -- always 96.
        entries += _command_pair(
            "cmd2", "mph96.tipPickup", "Instrument",
            {"tipPool": "Pool1000"}, {},
        )
        # MPH96 partial pickup: 2 columns on a 96-well (8x12) grid = 16 tips.
        entries += _command_pair(
            "cmd3", "mph96.tipPickupPartial", "Instrument",
            {"tipPool": "Pool1000", "mode": "cols", "count": 2}, {},
        )
        entries += _command_pair(
            "cmd4", "channels.1mL.aspirate", "Instrument",
            {"channels": [1], "volumes": 50.0}, {"channels": []},
        )
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(summary["tip_pickup_calls"], 3)
        self.assertEqual(summary["tips_used"], 3 + 96 + 16)
        self.assertEqual(summary["step_count"], 4)
        self.assertEqual(summary["error_count"], 0)

    def test_tips_by_type_resolves_pool_to_labware_definition(self):
        entries = []
        entries += _command_pair(
            "rack1", "labware.addTipRack", "Deck Layout",
            {"tipPool": "Pool300", "labwareDefinition": "Tip_Rack_300uL", "carrier": "TipCarrier1", "site": "1"}, {},
        )
        entries += _command_pair(
            "cmd1", "channels.1mL.tipPickup", "Instrument",
            {"channels": [1, 2, 3], "tipPool": "Pool300"}, {},
        )
        entries += _command_pair(
            "cmd2", "channels.1mL.tipPickup", "Instrument",
            {"channels": [1, 2], "tipPool": "UnresolvedPool"}, {},
        )
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(
            summary["tips_by_type"],
            [
                {"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_300uL", "count": 3},
                {"kind": "unknown", "kind_label": "Other", "tip_type": "UnresolvedPool", "count": 2},
            ],
        )

    def test_tips_by_type_splits_by_which_add_tip_action_registered_the_pool(self):
        entries = []
        entries += _command_pair(
            "rack1", "labware.addTipRack", "Deck Layout",
            {"tipPool": "PoolRack", "labwareDefinition": "Tip_Rack_300uL", "carrier": "TipCarrier1", "site": "1"}, {},
        )
        entries += _command_pair(
            "box1", "labware.addTipBox", "Deck Layout",
            {"tipPool": "PoolBox", "labwareDefinition": "Tip_Box_1000uL", "carrier": "TipCarrier1", "site": "2"}, {},
        )
        entries += _command_pair(
            "ntr1", "labware.addNTR", "Deck Layout",
            {"tipPool": "PoolNTR", "labwareDefinition": "Tip_Nested_300uL", "carrier": "TipCarrier1", "site": "3", "stack": 1}, {},
        )
        entries += _command_pair("p1", "channels.1mL.tipPickup", "Instrument", {"channels": [1, 2], "tipPool": "PoolRack"}, {})
        entries += _command_pair("p2", "channels.1mL.tipPickup", "Instrument", {"channels": [1], "tipPool": "PoolBox"}, {})
        entries += _command_pair("p3", "mph96.tipPickup", "Instrument", {"tipPool": "PoolNTR"}, {})

        summary = summarize_run(self._build_log(entries))
        self.assertEqual(
            summary["tips_by_type"],
            [
                {"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_300uL", "count": 2},
                {"kind": "tip_box", "kind_label": "Tip Box", "tip_type": "Tip_Box_1000uL", "count": 1},
                {"kind": "ntr", "kind_label": "Nested Tip Rack", "tip_type": "Tip_Nested_300uL", "count": 96},
            ],
        )

    def test_tips_by_type_resolves_pool_when_venus_lowercases_the_response_name(self):
        """VENUS lower-cases whatever tip_pool name it's given when it echoes
        the pool back in returnParameters.tipPoolName. A script that reuses
        that returned (lower-cased) name for tip_pickup -- rather than its
        own originally-supplied mixed-case string -- must still resolve to
        the right kind/tip_type."""
        entries = []
        entries += _command_pair(
            "rack1", "labware.addTipRack", "Deck Layout",
            {"tipPool": "TipRack1000uLPool", "labwareDefinition": "Tip_Rack_1000uL", "carrier": "TipCarrier1", "site": "1"},
            {"totalTips": 96, "tipPoolName": "tiprack1000ulpool", "labwareName": "washtips", "tipType": 0},
        )
        entries += _command_pair(
            "p1", "channels.1mL.tipPickup", "Instrument", {"channels": [1, 2], "tipPool": "tiprack1000ulpool"}, {}
        )

        summary = summarize_run(self._build_log(entries))
        self.assertEqual(
            summary["tips_by_type"],
            [{"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_1000uL", "count": 2}],
        )

    def test_tips_by_type_resolves_auto_assigned_pool_when_tip_pool_omitted(self):
        """add_tip_rack/add_tip_box/add_ntr may omit tip_pool (and labware_id),
        letting VENUS auto-assign both -- the auto-assigned pool name then only
        appears in that call's own response, never in its request."""
        entries = []
        entries += _command_pair(
            "rack1", "labware.addTipRack", "Deck Layout",
            {"labwareDefinition": "Tip_Rack_1000uL", "carrier": "TipCarrier1", "site": "1"},
            {"totalTips": 96, "tipPoolName": "auto_pool_rack", "labwareName": "auto_rack_1", "tipType": 0},
        )
        entries += _command_pair(
            "box1", "labware.addTipBox", "Deck Layout",
            {"labwareDefinition": "Tip_Box_1000uL", "carrier": "TipBoxCarrier1", "site": "1"},
            {"totalTips": 96, "tipPoolName": "auto_pool_box", "labwareName": "auto_box_1", "tipType": 0},
        )
        entries += _command_pair(
            "ntr1", "labware.addNTR", "Deck Layout",
            {"labwareDefinition": "Tip_Nested_300uL", "carrier": "NtrCarrier1", "site": "1", "stack": 4},
            {"totalTips": 384, "tipPoolName": "auto_pool_ntr", "labwareName": "auto_ntr_1", "tipType": 0},
        )
        entries += _command_pair(
            "p1", "channels.1mL.tipPickup", "Instrument", {"channels": [1, 2], "tipPool": "auto_pool_rack"}, {}
        )
        entries += _command_pair(
            "p2", "channels.1mL.tipPickup", "Instrument", {"channels": [1], "tipPool": "auto_pool_box"}, {}
        )
        entries += _command_pair(
            "p3", "channels.1mL.tipPickup", "Instrument", {"channels": [1, 2, 3], "tipPool": "auto_pool_ntr"}, {}
        )

        summary = summarize_run(self._build_log(entries))
        self.assertEqual(
            summary["tips_by_type"],
            [
                {"kind": "tip_rack", "kind_label": "Tip Rack", "tip_type": "Tip_Rack_1000uL", "count": 2},
                {"kind": "tip_box", "kind_label": "Tip Box", "tip_type": "Tip_Box_1000uL", "count": 1},
                {"kind": "ntr", "kind_label": "Nested Tip Rack", "tip_type": "Tip_Nested_300uL", "count": 3},
            ],
        )

    def test_plates_and_lids_by_type_including_lidded_plate_counting_both(self):
        entries = []
        entries += _command_pair(
            "p1", "labware.addPlate", "Deck Layout",
            {"labwareName": "Plate1", "labwareDefinition": "Cos_96_Rd", "carrier": "PlateCarrier1", "site": "1"}, {},
        )
        entries += _command_pair(
            "p2", "labware.addPlate", "Deck Layout",
            {"labwareName": "Plate2", "labwareDefinition": "Cos_96_Rd", "carrier": "PlateCarrier1", "site": "2"}, {},
        )
        entries += _command_pair(
            "p3", "labware.addLiddedPlate", "Deck Layout",
            {
                "labwareName": "Plate3", "labwareDefinition": "Nunc_96_FL", "lidDefinition": "Nunc_Lid",
                "carrier": "PlateCarrier1", "site": "3",
            }, {},
        )
        entries += _command_pair(
            "l1", "labware.addLid", "Deck Layout",
            {"labwareName": "Lid1", "labwareDefinition": "Std_Lid", "carrier": "PlateCarrier1", "site": "4"}, {},
        )
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(
            summary["plates_by_type"],
            [{"labware_definition": "Cos_96_Rd", "count": 2}, {"labware_definition": "Nunc_96_FL", "count": 1}],
        )
        self.assertEqual(
            summary["lids_by_type"],
            [{"labware_definition": "Nunc_Lid", "count": 1}, {"labware_definition": "Std_Lid", "count": 1}],
        )

    def test_no_plates_or_lids_gives_empty_breakdowns(self):
        summary = summarize_run(self._build_log([]))
        self.assertEqual(summary["plates_by_type"], [])
        self.assertEqual(summary["lids_by_type"], [])
        self.assertEqual(summary["reservoir_volumes"], [])

    def test_reservoir_volume_consumed_across_channel_scalar_list_and_mph96(self):
        entries = []
        entries += _command_pair(
            "r1", "labware.addReservoir", "Deck Layout",
            {"labwareName": "Water", "labwareDefinition": "RGT_CONT_60ML", "carrier": "ReagentCarrier1", "site": "1"}, {},
        )
        entries += _command_pair(
            "r2", "labware.addReservoir", "Deck Layout",
            {"labwareName": "Buffer", "labwareDefinition": "RGT_CONT_60ML", "carrier": "ReagentCarrier1", "site": "2"}, {},
        )
        entries += _command_pair(
            "r3", "labware.addReservoir", "Deck Layout",
            {"labwareName": "Unused", "labwareDefinition": "RGT_CONT_60ML", "carrier": "ReagentCarrier1", "site": "3"}, {},
        )
        # Scalar volume applied uniformly across 8 channels, all from Water/A1.
        entries += _command_pair(
            "a1", "channels.1mL.aspirate", "Instrument",
            {
                "channels": [1, 2, 3, 4, 5, 6, 7, 8],
                "positions": [{"labwareId": "Water", "wellId": "A1"}] * 8,
                "volumes": 100.0,
            },
            {"channels": []},
        )
        # Per-channel volume list, split across two distinct reservoirs plus a
        # non-reservoir plate well that must be ignored.
        entries += _command_pair(
            "a2", "channels.1mL.aspirate", "Instrument",
            {
                "channels": [1, 2, 3],
                "positions": [
                    {"labwareId": "Water", "wellId": "A1"},
                    {"labwareId": "Buffer", "wellId": "A1"},
                    {"labwareId": "Plate1", "wellId": "A1"},
                ],
                "volumes": [30.0, 20.0, 10.0],
            },
            {"channels": []},
        )
        # MPH96 full-head aspirate (no mphSelection on the wire) from Buffer.
        entries += _command_pair(
            "a3", "mph96.aspirate", "Instrument",
            {"labwareName": "Buffer", "volume": 5.0, "liquidClass": "Water"},
            {},
        )
        # MPH96 partial aspirate (explicit mphSelection) from Water.
        entries += _command_pair(
            "a4", "mph96.aspirate", "Instrument",
            {"labwareName": "Water", "mphSelection": ["A1", "B1", "C1", "D1"], "volume": 2.0, "liquidClass": "Water"},
            {},
        )
        summary = summarize_run(self._build_log(entries))
        # Water: 100*8 + 30 + (4*2.0) = 838; Buffer: 20 + 96*5.0 = 500; Unused: dropped entirely.
        self.assertEqual(
            summary["reservoir_volumes"],
            [{"labware": "Water", "volume_ul": 838.0}, {"labware": "Buffer", "volume_ul": 500.0}],
        )

    def test_reservoir_volume_consumed_from_a_loaded_deck_with_no_addreservoir_call(self):
        # Regression guard: a reservoir that was already on a deck loaded via
        # deck_load()/backup-restore (rather than added fresh by this script)
        # never produces a labware.addReservoir request -- deck.loadDeck's own
        # response carries no labware list either (see docs/json_schemas_System.md:
        # {"message": ...} only). The live bootstrap's own "reservoir_labware"
        # entry (script_runner.py's _is_reservoir_labware) is the only signal
        # available in that case, and must be enough on its own -- no
        # labware.addReservoir entry appears anywhere in this log.
        entries = [
            {"type": "reservoir_labware", "source": "Bootstrap", "direction": "Out", "payload": {"labware": "Enzyme"}},
        ]
        entries += _command_pair(
            "a1", "channels.1mL.aspirate", "Instrument",
            {
                "channels": [1, 2],
                "positions": [{"labwareId": "Enzyme", "wellId": "A1"}, {"labwareId": "Enzyme", "wellId": "A2"}],
                "volumes": [50.0, 60.0],
            },
            {"channels": []},
        )
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(summary["reservoir_volumes"], [{"labware": "Enzyme", "volume_ul": 110.0}])

    def test_malformed_reservoir_labware_entries_are_ignored(self):
        entries = [
            {"type": "reservoir_labware", "source": "Bootstrap", "direction": "Out", "payload": {}},
            {"type": "reservoir_labware", "source": "Bootstrap", "direction": "Out", "payload": {"labware": 123}},
            {"type": "reservoir_labware", "source": "Bootstrap", "direction": "Out"},
            "not a dict",
        ]
        summary = summarize_run(self._build_log(entries))  # must not raise
        self.assertEqual(summary["reservoir_volumes"], [])

    def test_instrument_error_groups_channels_sharing_the_same_message(self):
        entries = [
            {
                "type": "instrument_error", "source": "SignalR", "direction": "In",
                "payload": {
                    "uuid": "err1", "device_id": 1, "code": "P1:06/71", "date": "2026-08-06T00:00:05+00:00",
                    "message": "P1:06/71", "title": "1000ul Channel Aspirate (Single Step) - Error", "timeout": -1,
                    "default_recovery_action_id": 0, "actions": [],
                    "detailed_errors": [
                        # Channels 1, 2, 5 -- matching the real VENUS shape -- all get the
                        # exact same message and should collapse into one grouped row...
                        {"uuid": "d1", "index": 0, "code": "71", "message": "Not enough liquid.",
                         "attributes": [{"name": "channel", "value": "1"}]},
                        {"uuid": "d2", "index": 1, "code": "71", "message": "Not enough liquid.",
                         "attributes": [{"name": "channel", "value": "2"}]},
                        {"uuid": "d5", "index": 2, "code": "71", "message": "Not enough liquid.",
                         "attributes": [{"name": "channel", "value": "5"}]},
                        # ...while channel 3, with a genuinely different message for the same
                        # event, must stay in its own separate row.
                        {"uuid": "d3", "index": 3, "code": "72", "message": "Tip is bent.",
                         "attributes": [{"name": "channel", "value": "3"}]},
                    ],
                    "help": None, "notification_sound": None, "recovery_actions": [],
                },
            },
            {
                "type": "device_error_handled", "source": "SignalR", "direction": "In",
                "payload": {"uuid": "err1", "recovery_action": "Execute"},
            },
            {
                # No detailed_errors at all -- falls back to one row, no channels.
                "type": "instrument_error", "source": "SignalR", "direction": "In",
                "payload": {"uuid": "err2", "code": "E202", "message": "Clot detected", "title": "Aspirate Error"},
            },
        ]
        summary = summarize_run(self._build_log(entries))

        err1_rows = [e for e in summary["instrument_errors"] if e["uuid"] == "err1"]
        self.assertEqual(len(err1_rows), 2)
        grouped = next(r for r in err1_rows if r["detail"] == "Not enough liquid.")
        self.assertEqual(grouped["channels"], ["1", "2", "5"])
        self.assertEqual(grouped["step"], "1000ul Channel Aspirate (Single Step) - Error")
        self.assertEqual(grouped["recovery_action"], "Execute")
        distinct = next(r for r in err1_rows if r["detail"] == "Tip is bent.")
        self.assertEqual(distinct["channels"], ["3"])

        err2_row = next(e for e in summary["instrument_errors"] if e["uuid"] == "err2")
        self.assertEqual(err2_row["channels"], [])
        self.assertEqual(err2_row["detail"], "Clot detected")
        self.assertIsNone(err2_row["recovery_action"])

        # error_count counts distinct error events (2), not table rows (3).
        self.assertEqual(summary["error_count"], 2)

    def test_recovery_action_prefers_the_real_submitted_detail_action_over_execute(self):
        # device_error_handled reports "Execute" for any per-channel (advanced
        # ErrorRecovery) submission -- that's just the fixed top-level wrapper
        # id meaning "apply the detailedErrorRecoveries below", not what the
        # operator actually picked. The real per-channel choice ("Repeat")
        # only exists in the matching POST .../recovery request's own body.
        entries = [
            {
                "type": "instrument_error", "source": "SignalR", "direction": "In",
                "payload": {
                    "uuid": "err1", "device_id": 1, "code": "P1:06/71", "date": "2026-08-06T00:00:05+00:00",
                    "message": "P1:06/71", "title": "1000ul Channel Aspirate (Single Step) - Error", "timeout": -1,
                    "default_recovery_action_id": 0, "actions": [],
                    "detailed_errors": [
                        {"uuid": "d1", "index": 0, "code": "71", "message": "Not enough liquid.",
                         "attributes": [{"name": "channel", "value": "1"}],
                         "recovery_actions": [{"id": 1026, "name": "Repeat", "index": 0}]},
                        {"uuid": "d2", "index": 1, "code": "71", "message": "Not enough liquid.",
                         "attributes": [{"name": "channel", "value": "2"}],
                         "recovery_actions": [{"id": 1026, "name": "Repeat", "index": 0}]},
                    ],
                    "help": None, "notification_sound": None,
                    "recovery_actions": [{"id": 1, "name": "Execute", "index": 0}],
                },
            },
            {
                "type": "http_request", "source": "WebAPI", "direction": "Out",
                "payload": {
                    "method": "POST",
                    "path": "/api/vector/v3/instrument-errors/err1/recovery",
                    "body": {
                        "date": "x", "uuid": "err1",
                        "detailedErrorRecoveries": [
                            {"date": "x", "uuid": "d1", "inputs": [], "selectedActionId": 1026},
                            {"date": "x", "uuid": "d2", "inputs": [], "selectedActionId": 1026},
                        ],
                        "selectedActionId": 1, "selectedActionIsRecovery": True, "errorHandlingKey": "x",
                    },
                },
            },
            {
                "type": "device_error_handled", "source": "SignalR", "direction": "In",
                "payload": {"uuid": "err1", "recovery_action": "Execute"},
            },
        ]
        summary = summarize_run(self._build_log(entries))
        row = summary["instrument_errors"][0]
        self.assertEqual(row["channels"], ["1", "2"])
        self.assertEqual(row["recovery_action"], "Repeat")

    def test_recovery_action_falls_back_to_device_error_handled_for_the_simple_path(self):
        # No detailedErrorRecoveries submission at all -- a plain top-level
        # action (e.g. a straight Abort) -- device_error_handled's own
        # recovery_action is already accurate for this path and should be
        # used as-is.
        entries = [
            {
                "type": "instrument_error", "source": "SignalR", "direction": "In",
                "payload": {"uuid": "err1", "code": "E1", "message": "Some failure", "title": "Some Step - Error"},
            },
            {
                "type": "device_error_handled", "source": "SignalR", "direction": "In",
                "payload": {"uuid": "err1", "recovery_action": "Abort"},
            },
        ]
        summary = summarize_run(self._build_log(entries))
        row = summary["instrument_errors"][0]
        self.assertEqual(row["recovery_action"], "Abort")

    def test_failed_step_is_detected_and_joined_to_its_request(self):
        entries = _command_pair(
            "cmd4", "channels.1mL.dispense", "Instrument",
            {"channels": [1], "volumes": 50.0}, {},
            return_code=99, return_status="Failed", status="Error",
        )
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(len(summary["failed_steps"]), 1)
        failed = summary["failed_steps"][0]
        self.assertEqual(failed["action_name"], "channels.1mL.dispense")
        self.assertEqual(failed["category"], "Instrument")
        self.assertEqual(failed["return_code"], 99)
        self.assertEqual(failed["return_status"], "Failed")

    def test_tadm_curves_group_by_liquid_class_step_type_and_volume(self):
        curves_group_a = [
            _tadm_curve("Water", "Aspirate", 100.0, channel_number=1, curve_id=1, curve_flagged=1),
            _tadm_curve("Water", "Aspirate", 100.0, channel_number=2, curve_id=2, error=1),
        ]
        curves_group_b = [
            _tadm_curve("Water", "Aspirate", 50.0, channel_number=3, curve_id=3),
        ]
        entries = []
        entries += _command_pair(
            "cmd5", "channels.1mL.aspirate", "Instrument", {"channels": [1, 2]},
            {"channels": [], "TADM": {"tadmCurves": curves_group_a}},
        )
        entries += _command_pair(
            "cmd6", "channels.1mL.aspirate", "Instrument", {"channels": [3]},
            {"channels": [], "TADM": {"tadmCurves": curves_group_b}},
        )
        summary = summarize_run(self._build_log(entries))

        self.assertEqual(summary["tadm_totals"], {"curve_count": 3, "flagged_count": 1, "error_count": 1})
        self.assertEqual(len(summary["tadm_groups"]), 2)

        group_a = next(g for g in summary["tadm_groups"] if g["volume"] == 100.0)
        self.assertEqual(group_a["liquid_class_name"], "Water")
        self.assertEqual(group_a["step_type_name"], "Aspirate")
        self.assertEqual(len(group_a["curves"]), 2)
        flagged_curve = next(c for c in group_a["curves"] if c["channel_number"] == 1)
        self.assertEqual(flagged_curve["curve_flagged"], 1)
        error_curve = next(c for c in group_a["curves"] if c["channel_number"] == 2)
        self.assertEqual(error_curve["error"], 1)

        group_b = next(g for g in summary["tadm_groups"] if g["volume"] == 50.0)
        self.assertEqual(len(group_b["curves"]), 1)

    def test_missing_log_key_returns_zeroed_summary_without_raising(self):
        summary = summarize_run({})
        self.assertEqual(summary["step_count"], 0)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["tips_used"], 0)
        self.assertEqual(summary["tadm_groups"], [])
        self.assertEqual(summary["result"], "unknown")

    def test_non_dict_return_parameters_is_tolerated(self):
        entries = [
            {
                "type": "command_response", "source": "WebAPI", "direction": "In",
                "payload": {
                    "id": "cmd-weird", "status": "Success", "returnStatus": "Success",
                    "returnCode": 0, "returnParameters": ["not", "a", "dict"],
                },
            },
        ]
        summary = summarize_run(self._build_log(entries))
        self.assertEqual(summary["step_count"], 1)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["tadm_groups"], [])

    def test_no_session_end_falls_back_to_top_level_timestamps(self):
        summary = summarize_run(self._build_log([]))
        self.assertEqual(summary["duration_seconds"], 12.0)
        self.assertEqual(summary["result"], "success")


class LoadRunLogTests(unittest.TestCase):
    def test_round_trips_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_SdkRunLog.json"
            path.write_text(json.dumps({"schema_version": "1.0", "log": []}), encoding="utf-8")
            data = load_run_log(path)
            self.assertEqual(data["schema_version"], "1.0")

    def test_invalid_json_raises_run_log_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_SdkRunLog.json"
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(RunLogError):
                load_run_log(path)

    def test_missing_file_raises_run_log_error(self):
        with self.assertRaises(RunLogError):
            load_run_log(Path("C:/does/not/exist_SdkRunLog.json"))


if __name__ == "__main__":
    unittest.main()
