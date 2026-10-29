"""Unit tests for the ODTC protocol builder / XML renderer.

Verified element-by-element against a trimmed excerpt of the real vendor
sample (``Inheco ODTC/PLR001_ODTCProtocols.xml``): its ``PLR001_Cool8C``
PreMethod, and the first two + final-loop steps of ``PLR001_GSPCR``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from hamilton_venus.odtc_protocol import (
    ODTCPid,
    ODTCProtocol,
    ODTCProtocolBuilder,
    ODTCStep,
    protocol_tempfile,
    render_protocol_xml,
)


def _text(elem: ET.Element, tag: str) -> str:
    child = elem.find(tag)
    assert child is not None, f"missing <{tag}> in {ET.tostring(elem, encoding='unicode')}"
    return child.text or ""


class TestPreMethodRendering:
    def test_simple_hold_renders_as_premethod(self):
        # Mirrors the sample's PLR001_Cool8C PreMethod.
        protocol = ODTCProtocol(
            method_name="PLR001_Cool8C",
            creator="JD",
            description="Drops temp for plate storage",
            target_block_temperature=8,
            target_lid_temperature=110,
        )
        xml_text = render_protocol_xml(protocol)
        root = ET.fromstring(xml_text)
        assert root.tag == "MethodSet"
        premethod = root.find("PreMethod")
        assert premethod is not None
        assert premethod.attrib["methodName"] == "PLR001_Cool8C"
        assert premethod.attrib["creator"] == "JD"
        assert premethod.attrib["description"] == "Drops temp for plate storage"
        assert "dateTime" in premethod.attrib
        assert _text(premethod, "TargetBlockTemperature") == "8"
        assert _text(premethod, "TargetLidTemp") == "110"
        assert root.find("Method") is None

    def test_no_description_omits_attribute(self):
        protocol = ODTCProtocol(method_name="X", target_block_temperature=25, target_lid_temperature=110)
        root = ET.fromstring(render_protocol_xml(protocol))
        assert "description" not in root.find("PreMethod").attrib


class TestMethodRendering:
    def test_full_cycling_method_matches_sample_shape(self):
        builder = ODTCProtocolBuilder(
            "PLR001_GSPCR",
            creator="JD",
            description="GS PCR program",
            variant=960000,
            plate_type=0,
            fluid_quantity=0,
            post_heating=True,
            start_block_temperature=25,
            start_lid_temperature=110,
        )
        builder.add_hold(95, 900, slope=2)  # step 1: initial denature
        builder.add_cycle(
            [
                ODTCStep(temperature=98, hold_seconds=60, slope=2),  # step 2
                ODTCStep(temperature=60, hold_seconds=0, slope=2.2),  # step 3
            ],
            repeats=4,
        )
        protocol = builder.build()

        xml_text = render_protocol_xml(protocol)
        root = ET.fromstring(xml_text)
        method = root.find("Method")
        assert method is not None
        assert method.attrib["methodName"] == "PLR001_GSPCR"
        assert _text(method, "Variant") == "960000"
        assert _text(method, "PlateType") == "0"
        assert _text(method, "FluidQuantity") == "0"
        assert _text(method, "PostHeating") == "true"
        assert _text(method, "StartBlockTemperature") == "25"
        assert _text(method, "StartLidTemperature") == "110"

        steps = method.findall("Step")
        assert len(steps) == 3
        assert [_text(s, "Number") for s in steps] == ["1", "2", "3"]
        assert _text(steps[0], "PlateauTemperature") == "95"
        assert _text(steps[0], "PlateauTime") == "900"
        assert _text(steps[0], "GotoNumber") == "0"
        assert _text(steps[0], "LoopNumber") == "0"

        # add_cycle sets Goto/Loop only on the *last* step of the block,
        # pointing back at the block's first step number.
        assert _text(steps[1], "GotoNumber") == "0"
        assert _text(steps[1], "LoopNumber") == "0"
        assert _text(steps[2], "GotoNumber") == "2"
        assert _text(steps[2], "LoopNumber") == "4"

        pidset = method.find("PIDSet")
        assert pidset is not None
        pids = pidset.findall("PID")
        assert len(pids) == 1
        assert pids[0].attrib["number"] == "1"
        assert _text(pids[0], "PHeating") == "60"

    def test_integers_render_without_trailing_zero(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 900, slope=2)
        root = ET.fromstring(render_protocol_xml(builder.build()))
        step = root.find("Method/Step")
        assert _text(step, "PlateauTemperature") == "95"
        assert _text(step, "Slope") == "2"

    def test_fractional_values_preserved(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(66.5, 30, slope=2.2)
        root = ET.fromstring(render_protocol_xml(builder.build()))
        step = root.find("Method/Step")
        assert _text(step, "PlateauTemperature") == "66.5"
        assert _text(step, "Slope") == "2.2"

    def test_overshoot_defaults_to_no_overshoot_with_a_nonzero_slope(self):
        # A zero overshoot slope is rejected by a real unit (MethodSet error 262:
        # VALIDATION_FAILED); 0.1 is the "none" value Hamilton's own sample uses.
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 30)
        step = ET.fromstring(render_protocol_xml(builder.build())).find("Method/Step")
        assert _text(step, "OverShootSlope1") == "0.1"
        assert _text(step, "OverShootSlope2") == "0.1"
        assert _text(step, "OverShootTemperature") == "0"
        assert _text(step, "OverShootTime") == "0"

    def test_overshoot_advanced_override(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_step(
            ODTCStep(
                temperature=95,
                hold_seconds=900,
                overshoot_slope1=2,
                overshoot_temperature=5.6,
                overshoot_time=0,
                overshoot_slope2=2.2,
            )
        )
        step = ET.fromstring(render_protocol_xml(builder.build())).find("Method/Step")
        assert _text(step, "OverShootSlope1") == "2"
        assert _text(step, "OverShootTemperature") == "5.6"
        assert _text(step, "OverShootSlope2") == "2.2"


class TestBuilderValidation:
    def test_add_cycle_requires_steps(self):
        with pytest.raises(ValueError, match="at least one step"):
            ODTCProtocolBuilder("X").add_cycle([], repeats=3)

    def test_repeats_is_written_as_loop_number_like_inheco_cycles(self):
        # Inheco's Script Editor "Cycles" field is the wire LoopNumber (extra passes):
        # Cycles=3 plots four denature/anneal/extend passes, and so does a real unit.
        def loop_of(repeats):
            b = ODTCProtocolBuilder("X")
            b.add_cycle([ODTCStep(temperature=95), ODTCStep(temperature=60)], repeats=repeats)
            steps = ET.fromstring(render_protocol_xml(b.build())).find("Method").findall("Step")
            return _text(steps[-1], "GotoNumber"), _text(steps[-1], "LoopNumber")

        assert loop_of(3) == ("1", "3")
        assert loop_of(1) == ("1", "1")

    def test_add_cycle_requires_positive_repeats(self):
        with pytest.raises(ValueError, match="repeats must be"):
            ODTCProtocolBuilder("X").add_cycle([ODTCStep(temperature=95)], repeats=0)

    def test_steps_auto_numbered_in_order(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 10)
        builder.add_hold(60, 20)
        builder.add_hold(72, 30)
        numbers = [s.number for s in builder.build().steps]
        assert numbers == [1, 2, 3]


class TestCustomPids:
    def test_set_pids_replaces_default(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 10)
        builder.set_pids([ODTCPid(number=1, p_heating=42), ODTCPid(number=2, p_heating=7)])
        method = ET.fromstring(render_protocol_xml(builder.build())).find("Method")
        pids = method.find("PIDSet").findall("PID")
        assert [p.attrib["number"] for p in pids] == ["1", "2"]
        assert _text(pids[0], "PHeating") == "42"


class TestProtocolTempfile:
    def test_writes_and_cleans_up(self):
        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 10)
        protocol = builder.build()
        with protocol_tempfile(protocol) as path:
            import os

            assert os.path.isfile(path)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            assert "PLR" not in content  # sanity: our own content, not a stray fixture
            assert "<MethodSet>" in content
        assert not os.path.exists(path)

    def test_keep_true_retains_file(self):
        import os

        builder = ODTCProtocolBuilder("X")
        builder.add_hold(95, 10)
        with protocol_tempfile(builder.build(), keep=True) as path:
            pass
        try:
            assert os.path.exists(path)
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# add_pcr: golden data copied from Inheco Script Editor 3.0.1 ("Volume Comparison.xml"): the same
# 3-step PCR (95 C 15 s; 3 cycles of 95 C 10 s / 60 C 10 s / 72 C 15 s; 72 C 15 s; cool to 25 C 10 s)
# saved once per fluid setting. Columns: temperature, seconds, slope, OverShootSlope1,
# OverShootTemperature, OverShootTime, OverShootSlope2, GotoNumber, LoopNumber.
# ---------------------------------------------------------------------------
_NONE = (0.1, 0.0, 0.0, 0.1)


def _editor_steps(fq, init, denat, anneal, ext, cool):
    """Rows of the editor's 11-step layout. Each argument is that fluid setting's tuned values."""
    heat = 4.4
    (init_os, init_hold), (den_os, den_hold), (an_slope, an_os), ext_os = init, denat, anneal, ext
    c60, c40, c25 = cool
    return [
        (95, 15, heat, heat, init_os, init_hold, 2.2, 0, 0),
        (95, 10, heat, *_NONE, 0, 0),
        (60, 10, an_slope, an_slope, an_os, 0, 2.2, 0, 0),
        (72, 15, heat, heat, ext_os, 0, 2.2, 0, 0),
        (95, 10, heat, heat, den_os, den_hold, 2.2, 3, 2),
        (60, 10, an_slope, an_slope, an_os, 0, 2.2, 0, 0),
        (72, 15, heat, heat, ext_os, 0, 2.2, 0, 0),
        (72, 15, heat, *_NONE, 0, 0),
        (60, 0, c60, *_NONE, 0, 0),
        (40, 0, c40, *_NONE, 0, 0),
        (25, 10, c25, c25, 0.0, 0.0, 0.1, 0, 0),
    ]


_EDITOR = {
    0: _editor_steps(0, (6.5, 0), (5.3, 0), (2.2, 4.3), 4.2, (2.2, 1.4, 0.8)),
    1: _editor_steps(1, (7.0, 6), (7.0, 3.4), (2.0, 4.5), 9.0, (2.0, 1.3, 0.75)),
    2: _editor_steps(2, (7.0, 9.1), (7.0, 5.9), (1.8, 5.5), 11.3, (1.8, 1.2, 0.65)),
}


def _rows(protocol):
    root = ET.fromstring(render_protocol_xml(protocol))
    out = []
    for st in root.find("Method").findall("Step"):
        def num(tag, st=st):
            return float(_text(st, tag))
        out.append(
            (
                num("PlateauTemperature"), num("PlateauTime"), num("Slope"), num("OverShootSlope1"),
                num("OverShootTemperature"), num("OverShootTime"), num("OverShootSlope2"),
                int(num("GotoNumber")), int(num("LoopNumber")),
            )
        )
    return out


class TestAddPcrMatchesTheScriptEditor:
    @pytest.mark.parametrize("fq", [0, 1, 2])
    def test_every_step_field_matches_the_editors_output(self, fq):
        builder = ODTCProtocolBuilder("PCR", fluid_quantity=fq)
        builder.add_pcr()  # the editor's defaults, cycles=3
        protocol = builder.build()
        assert protocol.fluid_quantity == fq
        assert _rows(protocol) == [tuple(float(v) if i < 7 else int(v) for i, v in enumerate(r)) for r in _EDITOR[fq]]

    def test_fluid_quantity_defaults_to_the_smallest_volume(self):
        builder = ODTCProtocolBuilder("PCR")
        builder.add_pcr()
        assert builder.build().fluid_quantity == 0
        assert _rows(builder.build()) == [
            tuple(float(v) if i < 7 else int(v) for i, v in enumerate(r)) for r in _EDITOR[0]
        ]

    def test_cooling_ladder_stops_at_the_requested_temperature(self):
        # Hamilton's own PLR001 methods cool 60 -> 40 -> 20 -> 8 with slopes 1.4 / 0.8 / 0.25 (volume 0).
        builder = ODTCProtocolBuilder("PCR")
        builder.add_pcr(cooling=(8.0, 120.0))
        cooling = _rows(builder.build())[8:]
        assert [(r[0], r[1], r[2]) for r in cooling] == [(60, 0, 2.2), (40, 0, 1.4), (20, 0, 0.8), (8, 120, 0.25)]

    def test_optional_parts_can_be_switched_off_and_loop_numbers_follow(self):
        builder = ODTCProtocolBuilder("PCR")
        builder.add_pcr(initial_denaturation=None, final_extension=None, cooling=None, cycles=2)
        rows = _rows(builder.build())
        assert len(rows) == 6  # denature, anneal, extend, denature (loop), anneal, extend
        assert (rows[3][7], rows[3][8]) == (2, 1)  # loops back to the anneal (step 2), cycles-1 times
        assert rows[0][3:7] == (4.4, 6.5, 0.0, 2.2)  # with no initial step, the first denature heats from the start

    def test_one_cycle_sets_no_loop(self):
        builder = ODTCProtocolBuilder("PCR")
        builder.add_pcr(cycles=1)
        assert all(r[7] == 0 and r[8] == 0 for r in _rows(builder.build()))

    def test_overshoot_peak_is_capped_at_102_c(self):
        builder = ODTCProtocolBuilder("PCR", fluid_quantity=1)
        builder.add_pcr(initial_denaturation=(98.0, 15.0), denaturation=(98.0, 10.0))
        first = _rows(builder.build())[0]
        assert first[0] == 98 and first[4] == 4.0  # 102 - 98, not the 7.0 used for a 95 C target

    def test_unsupported_fluid_quantity_and_cycles_are_rejected(self):
        with pytest.raises(ValueError, match="fluid_quantity"):
            ODTCProtocolBuilder("PCR", fluid_quantity=5).add_pcr()
        with pytest.raises(ValueError, match="cycles"):
            ODTCProtocolBuilder("PCR").add_pcr(cycles=0)
