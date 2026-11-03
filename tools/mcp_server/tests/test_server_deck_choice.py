"""start_session asks the user for simulation vs live and the deck layout (MCP elicitation),
falling back to deck_choice_required + select_deck_layout when the client can't show a form."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hamilton_venus_mcp.server as srv
from hamilton_venus.models.command_types import DeckAvailableResponse, SavedDecksResponse

# The shape deck.getPreviousDeck returns (trimmed from a live STAR simulation run).
LAST_LAYOUT = {
    "deckAvailable": True,
    "layoutTracking": {"1": {"occupied": True, "carrier": "tipcarrier", "sensorTrack": 5, "sensorAvailable": True}},
    "carrierTracking": {
        "reagentcarrier": {
            "track": 13,
            "type": "carrier",
            "1": {"labware": [{"ID": "trough1", "type": "reservoir"}]},
            "2": {"labware": []},
        },
        "tipcarrier": {
            "track": 1,
            "type": "carrier",
            "1": {"labware": [{"ID": "tip_rack_1000ul_0001", "type": "tip"}]},
            "2": {"labware": [{"ID": "tip_rack_1000ul_0002", "type": "tip"}]},
        },
        "car_adapters": {"track": 34, "type": "sample carrier"},
    },
    "tipCountingTracking": {
        "tips1000": {"totalTips": 192, "tipRacks": ["tip_rack_1000ul_0001", "tip_rack_1000ul_0002"]},
    },
}


class _FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._session_id = "fake-session"
        self.loaded: list[tuple[str | None, bool]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def instrument_is_idle(self) -> bool:
        return True

    def instrument_connect(self, initialize: bool = False) -> None:
        return None

    def deck_get_previous(self) -> DeckAvailableResponse:
        return DeckAvailableResponse.model_validate({"returnParameters": LAST_LAYOUT})

    def deck_get_saved(self) -> SavedDecksResponse:
        return SavedDecksResponse.model_validate({"returnParameters": {"savedDecks": ["baselayout", "6wprefeeding"]}})

    def deck_load(self, deck_name: str | None = None, *, previous: bool = False) -> None:
        self.loaded.append((deck_name, previous))


class _FakeCtx:
    """Answers each elicitation with the next scripted (action, value)."""

    def __init__(self, *answers: tuple[str, str | dict]) -> None:
        self.session = SimpleNamespace(check_client_capability=lambda capability: True)
        self.answers = list(answers)
        self.messages: list[str] = []
        self.schemas: list[dict] = []

    async def elicit(self, message: str, schema: type) -> SimpleNamespace:
        self.messages.append(message)
        self.schemas.append(schema.model_json_schema())
        action, value = self.answers.pop(0)
        # A dict answers several fields; a plain value answers the first one.
        fields = value if isinstance(value, dict) else {next(iter(schema.model_fields)): value}
        return SimpleNamespace(action=action, data=schema(**fields) if action == "accept" else None)


class DeckChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._patches = [
            patch("hamilton_workflow_framework.session.StarClient", _FakeClient),
            patch("hamilton_workflow_framework.session.VantageClient", _FakeClient),
        ]
        for p in self._patches:
            p.start()

    async def asyncTearDown(self) -> None:
        await srv.close_session()
        for p in reversed(self._patches):
            p.stop()

    async def test_session_name_names_the_venus_run(self) -> None:
        result = await srv.start_session(simulate=True, blank_deck=True, session_name="Plate prep 3")
        self.assertEqual(result["session_name"], "Plate prep 3")
        config = srv._session.star.kwargs["config"]
        self.assertEqual(config.method.method_display_name, "Plate prep 3")
        self.assertEqual(srv.get_session_status()["session_name"], "Plate prep 3")

    async def test_without_a_session_name_the_run_is_hamilton_venus_mcp(self) -> None:
        result = await srv.start_session(simulate=True, blank_deck=True)
        self.assertEqual(result["session_name"], "hamilton-venus-mcp")
        self.assertIsNone(srv._session.star.kwargs["config"])  # the SDK's own default naming

    async def test_the_opening_form_asks_the_session_name_too(self) -> None:
        ctx = _FakeCtx(("accept", {"mode": "simulation", "session_name": "Plate #3: prep"}), ("accept", "blank"))
        result = await srv.start_session(session_name="Suggested name", ctx=ctx)
        self.assertEqual(result["session_name"], "Plate 3 prep")  # typed in the form, made VENUS-safe
        name_field = ctx.schemas[0]["properties"]["session_name"]
        self.assertEqual(name_field["default"], "Suggested name")  # pre-filled with what was passed
        self.assertEqual(list(ctx.schemas[0]["properties"]), ["mode", "session_name"])

    async def test_an_empty_name_in_the_form_keeps_the_default(self) -> None:
        ctx = _FakeCtx(("accept", {"mode": "simulation", "session_name": "  "}), ("accept", "blank"))
        result = await srv.start_session(ctx=ctx)
        self.assertEqual(result["session_name"], "hamilton-venus-mcp")

    async def test_unusable_session_names_are_refused_before_anything_starts(self) -> None:
        for name in ("plate/3", "x" * 65, "VENUS_SDK_Executor"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "start_session was not called"):
                await srv.start_session(simulate=True, blank_deck=True, session_name=name)
        self.assertFalse(srv._session_active())

    async def test_no_simulate_without_a_form_asks_the_ai_to_ask(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "simulation or on the live instrument"):
            await srv.start_session(blank_deck=True)

    async def test_form_asks_mode_then_layout_with_last_layout_details(self) -> None:
        ctx = _FakeCtx(("accept", "live"), ("accept", "saved:6wprefeeding"))
        result = await srv.start_session(ctx=ctx)
        self.assertFalse(result["simulate"])
        self.assertEqual(result["deck_layout"], "saved layout '6wprefeeding'")
        self.assertEqual(srv._session.star.loaded, [("6wprefeeding", False)])
        self.assertIn(
            "Carriers: tipcarrier on track 1 (tip_rack_1000ul_0001, tip_rack_1000ul_0002); "
            "reagentcarrier on track 13 (trough1); car_adapters on track 34. "
            "Tip pools: tips1000 (2 rack(s), 192 tips).",
            ctx.messages[1],
        )
        self.assertNotIn("sensorTrack", ctx.messages[1])
        enum = ctx.schemas[1]["properties"]["layout"]["enum"]
        self.assertEqual(enum, ["blank", "previous", "saved:baselayout", "saved:6wprefeeding"])
        await srv.connect_instrument()

    async def test_form_choosing_blank_loads_nothing(self) -> None:
        ctx = _FakeCtx(("accept", "simulation"), ("accept", "blank"))
        result = await srv.start_session(simulate=True, ctx=ctx)
        self.assertEqual(result["deck_layout"], "blank")
        self.assertEqual(srv._session.star.loaded, [])
        await srv.connect_instrument()

    async def test_without_a_form_the_choice_is_returned_and_connect_waits(self) -> None:
        result = await srv.start_session(simulate=True)
        self.assertTrue(result["deck_choice_required"])
        self.assertEqual(result["deck_options"]["last_layout"], LAST_LAYOUT)
        self.assertTrue(result["deck_options"]["last_layout_summary"].startswith("Carriers: tipcarrier on track 1"))
        self.assertEqual(result["deck_options"]["saved_layouts"], ["baselayout", "6wprefeeding"])
        with self.assertRaisesRegex(RuntimeError, "select_deck_layout"):
            await srv.connect_instrument()
        selected = await srv.select_deck_layout(load_previous_deck=True)
        self.assertEqual(srv._session.star.loaded, [(None, True)])
        self.assertTrue(selected["connected"])  # choosing the layout also connects

    async def test_select_without_connect_only_loads(self) -> None:
        await srv.start_session(simulate=True)
        selected = await srv.select_deck_layout(deck_name="baselayout", connect=False)
        self.assertFalse(selected["connected"])
        await srv.connect_instrument()

    async def test_last_layout_summary_is_always_offered(self) -> None:
        result = await srv.start_session(simulate=True)
        self.assertIn("all three kinds", result["next_step"])
        self.assertIn("Do not call start_session again", result["next_step"])
        self.assertTrue(result["deck_options"]["last_layout_summary"])

    async def test_start_session_again_with_the_chosen_layout_reuses_the_open_session(self) -> None:
        # Seen live: the user picked a saved layout and the AI called start_session again.
        first = await srv.start_session(simulate=True)
        client = srv._session.star
        again = await srv.start_session(simulate=True, deck_name="nuncplate_multitrough_layout")
        self.assertTrue(again["reused_open_session"])
        self.assertIs(srv._session.star, client)
        self.assertEqual(again["connection_id"], first["connection_id"])
        self.assertEqual(client.loaded, [("nuncplate_multitrough_layout", False)])
        self.assertTrue(again["connected"])

    async def test_a_different_mode_restarts_instead_of_reusing(self) -> None:
        await srv.start_session(simulate=True)
        client = srv._session.star
        again = await srv.start_session(simulate=False, blank_deck=True)
        self.assertNotIn("reused_open_session", again)
        self.assertIsNot(srv._session.star, client)

    async def test_this_spokes_own_running_method_does_not_block_a_restart(self) -> None:
        await srv.start_session(simulate=True, blank_deck=True)
        busy = next(iter(srv.BUSY_RUN_STATES))
        with patch.object(srv._session, "check_run_state", return_value=busy), patch.object(
            srv._session, "owns_current_run", return_value=True
        ):
            await srv.start_session(simulate=True, blank_deck=True)
        with patch.object(srv._session, "check_run_state", return_value=busy), patch.object(
            srv._session, "owns_current_run", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "wasn't started from this session"):
                await srv.start_session(simulate=True, blank_deck=True)

    async def test_dismissed_layout_prompt_falls_back(self) -> None:
        result = await srv.start_session(simulate=True, ctx=_FakeCtx(("accept", "simulation"), ("cancel", "")))
        self.assertTrue(result["deck_choice_required"])

    async def test_with_a_form_the_user_is_asked_even_when_the_ai_chose(self) -> None:
        # Seen live: the user said "connect" and the AI passed simulate=True on its own.
        ctx = _FakeCtx(("accept", "live"), ("accept", "previous"))
        result = await srv.start_session(simulate=True, deck_name="baselayout", ctx=ctx)
        self.assertEqual(len(ctx.messages), 2)
        self.assertEqual(ctx.schemas[0]["properties"]["mode"]["default"], "simulation")
        self.assertEqual(ctx.schemas[1]["properties"]["layout"]["default"], "saved:baselayout")
        self.assertFalse(result["simulate"])
        self.assertEqual(result["deck_layout"], "last layout used")
        self.assertEqual(srv._session.star.loaded, [(None, True)])

    async def test_forms_cancelled_by_the_app_fall_back_to_the_chat(self) -> None:
        # Seen live in Claude Desktop's Code tab: every form comes back "cancel" unshown.
        ctx = _FakeCtx(("cancel", ""))
        result = await srv.start_session(simulate=True, ctx=ctx)
        self.assertEqual(len(ctx.messages), 1)
        self.assertTrue(result["simulate"])
        self.assertFalse(result["asked_in_app"])
        self.assertTrue(result["deck_choice_required"])
        with self.assertRaisesRegex(RuntimeError, "select_deck_layout"):
            await srv.connect_instrument()

    async def test_cancelled_mode_form_without_simulate_asks_the_ai_to_ask(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "simulation or on the live instrument"):
            await srv.start_session(ctx=_FakeCtx(("cancel", "")))

    async def test_nothing_suggested_means_no_preselection(self) -> None:
        ctx = _FakeCtx(("accept", "simulation"), ("accept", "blank"))
        await srv.start_session(ctx=ctx)
        self.assertNotIn("default", ctx.schemas[0]["properties"]["mode"])
        self.assertNotIn("default", ctx.schemas[1]["properties"]["layout"])

    async def test_without_a_form_an_explicit_choice_is_used_as_is(self) -> None:
        result = await srv.start_session(simulate=True, deck_name="baselayout")
        self.assertEqual(result["deck_layout"], "saved layout 'baselayout'")
        self.assertEqual(srv._session.star.loaded, [("baselayout", False)])
        await srv.connect_instrument()

    async def test_blank_after_a_load_is_refused(self) -> None:
        await srv.start_session(simulate=True, load_previous_deck=True)
        with self.assertRaisesRegex(RuntimeError, "blank"):
            await srv.select_deck_layout(blank_deck=True)

    def test_summary_caps_long_labware_lists_and_handles_an_empty_deck(self) -> None:
        sites = {str(i): {"labware": [{"ID": f"p{i}"}]} for i in range(1, 9)}
        summary = srv._describe_last_layout({"carrierTracking": {"c": {"track": 2, **sites}}})
        self.assertIn("(p1, p2, p3, p4, p5, p6, +2 more)", summary)
        self.assertEqual(
            srv._describe_last_layout({"deckAvailable": True, "carrierTracking": {}}), "It has no carriers on it."
        )

    async def test_only_one_deck_choice(self) -> None:
        with self.assertRaises(ValueError):
            await srv.start_session(simulate=True, deck_name="x", blank_deck=True)
