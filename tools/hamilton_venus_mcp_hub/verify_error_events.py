"""Live check of the hub's instrument-error visibility, against a running spoke and hub.

What it proves, in the simulator (never real hardware -- every session it opens is simulate=True):

  A. A Z-drive "Step lost" on tip_pickup with hold_on_error=False (the default) reaches
     - the caller (error envelope),
     - a custom webhook receiver this script runs (an `error` event with command, step, message,
       session_id),
     - the spoke's get_spoke_state (recent_errors),
     - the hub: get_spoke_errors, GET /api/spokes/<id>/events.json and /api/status.json,
     and is still on the hub after the spoke has gone back to idle.
  B. The same failure with hold_on_error=True still holds the step (held event, hub "command
     holds"), and the held error is on the hub after release.
  C. (best effort) An operator prompt for a session command shows up as an operator_prompt
     event, in pending_operator_prompts and on the hub, then as operator_prompt_resolved. The
     simulator's injected error clears on the standard profile's retry, so there may be no
     prompt to see -- that is reported as SKIP, not FAIL.

Run it with the spoke on its own URL (so the hub is only being read, not used as the relay):

    python verify_error_events.py --spoke-url http://localhost:8001/mcp ^
        --hub-url http://localhost:8000/mcp --spoke-id vantage_simulation

Auth: --token / HAMILTON_MCP_AUTH_TOKEN for the hub, --spoke-token / HAMILTON_MCP_SPOKE_TOKEN for
the spoke (default: the same token). The spoke must be running the new code (copy + restart the
local vantage_simulation spoke first) and registered in the hub.

Starting a session replaces whatever session the spoke has open, which aborts a running method --
so the script refuses to start if the spoke has a run, a session or a waiting prompt, unless you
pass --force.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from orchestrator_client import orchestrator_session as osess

Z_ERROR = ("1mL", "Tip Pick Up", "Z drive: Step lost on Z drive.")
TIP_POOL = "300uLTips"
results: list[tuple[str, str, str]] = []  # (PASS | FAIL | SKIP, name, detail)


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append(("PASS" if ok else "FAIL", name, "" if ok else detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" -- {detail}"))
    return ok


def skip(name: str, detail: str) -> None:
    results.append(("SKIP", name, detail))
    print(f"  [SKIP] {name} -- {detail}")


def as_list(value: Any) -> list[Any]:
    """_call_tool hands back a one-item list as the bare item, and an empty one as []/None."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def wait_for(fn: Callable[[], Any], timeout_s: float = 15.0, every_s: float = 0.5) -> Any:
    """The first truthy fn() within timeout_s, else the last (falsy) value."""
    deadline = time.monotonic() + timeout_s
    value = fn()
    while not value and time.monotonic() < deadline:
        time.sleep(every_s)
        value = fn()
    return value


class Receiver:
    """A tiny webhook endpoint standing in for the customer's own receiver."""

    def __init__(self, port: int) -> None:
        events = self.events = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    events.append(json.loads(body))
                except ValueError:
                    pass
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return

        self.server = HTTPServer(("0.0.0.0", port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in list(self.events) if e.get("kind") == kind]

    def stop(self) -> None:
        self.server.shutdown()


class Env:
    def __init__(self, args: argparse.Namespace) -> None:
        self.spoke = args.spoke_url
        self.hub = args.hub_url
        self.hub_http = args.hub_url.rsplit("/mcp", 1)[0].rstrip("/")
        self.spoke_id = args.spoke_id
        self.token = args.token
        osess.set_auth_token(self.hub, args.token)
        osess.set_auth_token(self.spoke, args.spoke_token or args.token)

    def spoke_call(self, tool: str, timeout_s: float = 120.0, **arguments: Any) -> Any:
        return osess._call_tool(self.spoke, tool, arguments, timeout_s=timeout_s)

    def hub_call(self, tool: str, **arguments: Any) -> Any:
        return osess._call_tool(self.hub, tool, arguments, timeout_s=30.0)

    def hub_get(self, path: str) -> Any:
        request = urllib.request.Request(self.hub_http + path)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())

    def hub_row(self) -> dict[str, Any] | None:
        rows = self.hub_get("/api/status.json")["spokes"]
        return next((s for s in rows if s["id"] == self.spoke_id), None)

    def hub_errors(self, **query: Any) -> list[dict[str, Any]]:
        return as_list(self.hub_call("get_spoke_errors", spoke_id=self.spoke_id, **query))

    def command(self, name: str, **kwargs: Any) -> Any:
        return self.spoke_call("call_sdk_command", name=name, kwargs=kwargs)


def preflight(env: Env, force: bool) -> bool:
    print("Preflight")
    try:
        row = env.hub_row()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return check(False, "hub reachable", str(exc))
    if not check(row is not None, f"spoke {env.spoke_id!r} is registered in the hub"):
        return False
    state = env.spoke_call("get_spoke_state")
    if not check("recent_errors" in state, "spoke is running the new code (get_spoke_state has recent_errors)",
                 "copy the new mcp_server to the spoke's install and restart it"):
        return False
    busy = state.get("state") == "running" or state.get("session_active") or state.get("pending_prompts")
    if busy and not force:
        return check(False, "spoke is idle", "a run, session or prompt is active; starting a session would "
                     "abort it. Wait for it, or pass --force")
    subscribed = wait_for(lambda: any("/api/spoke-events" in u for u in env.spoke_call("get_spoke_state").get("event_subscriptions", [])), 20)
    check(bool(subscribed), "the hub has subscribed itself to the spoke's events",
          "is HAMILTON_MCP_HUB_EVENT_PUSH=0, or the hub unable to reach the spoke's callback URL?")
    return True


def open_session(env: Env, *, hold_on_error: bool, profile: str) -> str:
    started = env.spoke_call(
        "start_session", simulate=True, blank_deck=True, instrument_type="STAR",
        hold_on_error=hold_on_error, error_profile=profile,
    )
    connection_id = started["connection_id"]
    env.spoke_call("connect_instrument", timeout_s=300.0, initialize=True, expected_connection_id=connection_id)
    env.command("add_carrier", labware_definition="TIP_CAR_480BC", left_track=1, labware_id="TipCarrier")
    env.command("add_tip_rack", labware_definition="Tip_Rack_300uL", carrier_id="TipCarrier", site="1", tip_pool=TIP_POOL)
    env.command("tip_pool_reset_tip_counter", tip_pool=TIP_POOL)
    return started.get("session_id") or env.spoke_call("get_session_status")["session_id"]


def inject_z_error(env: Env) -> None:
    result = env.spoke_call("set_simulated_error", module=Z_ERROR[0], step=Z_ERROR[1], error=Z_ERROR[2], channels=[1])
    if result.get("status") == "error":
        raise SystemExit(f"Could not inject the simulated error: {result}")


def scenario_plain_failure(env: Env, receiver: Receiver) -> None:
    print("\nA. Failure with hold_on_error=False")
    session_id = open_session(env, hold_on_error=False, profile="cancel_all")
    inject_z_error(env)
    result = env.command("tip_pickup", channels=[1], tip_pool=TIP_POOL)
    check(result.get("status") == "error", "the caller receives the error", str(result)[:200])
    message = result.get("message") or ""

    pushed = wait_for(lambda: [e for e in receiver.of_kind("error") if e.get("command") == "tip_pickup"])
    if check(bool(pushed), "the custom webhook receives an `error` event", f"got kinds {[e.get('kind') for e in receiver.events]}"):
        event = pushed[-1]
        check(bool(event.get("message")) and event.get("step") is not None and event.get("session_id") == session_id
              and event.get("held") is False, "the event carries message, step, session_id, held=false", str(event))
    check(not receiver.of_kind("held"), "nothing was held")

    state = env.spoke_call("get_spoke_state")
    check(any(e.get("command") == "tip_pickup" for e in state["recent_errors"]),
          "the spoke's get_spoke_state lists it in recent_errors")

    on_hub = wait_for(lambda: [e for e in env.hub_errors(kind="error") if e.get("command") == "tip_pickup"])
    if check(bool(on_hub), "hub get_spoke_errors has it"):
        check(on_hub[0].get("session_id") == session_id and bool(on_hub[0].get("message")),
              "...with session id, message and time", str(on_hub[0]))
    over_http = env.hub_get(f"/api/spokes/{env.spoke_id}/events.json?kind=error")["events"]
    check(any(e.get("command") == "tip_pickup" for e in over_http), "GET /api/spokes/<id>/events.json has it")
    row = env.hub_row() or {}
    check(any(e.get("command") == "tip_pickup" for e in row.get("recent_errors", [])),
          "/api/status.json recent_errors (the dashboard card) has it")
    check(bool(message) and any(message[:40] in (e.get("message") or "") for e in on_hub), "hub message matches what the caller saw")

    env.spoke_call("clear_simulated_errors")
    print("  waiting for the spoke to go back to idle...")
    wait_for(lambda: (env.hub_row() or {}).get("status", {}) and (env.hub_row() or {})["status"].get("status") == "idle", 20)
    check(any(e.get("command") == "tip_pickup" for e in env.hub_errors(kind="error")),
          "the hub still has it after the spoke is idle again", str(env.hub_row().get("status")))


def scenario_hold(env: Env, receiver: Receiver) -> None:
    print("\nB. Failure with hold_on_error=True (existing behaviour must be unchanged)")
    open_session(env, hold_on_error=True, profile="cancel_all")
    inject_z_error(env)
    result = env.command("tip_pickup", channels=[1], tip_pool=TIP_POOL)
    check(result.get("status") == "held", "the step is held", str(result)[:200])
    check(bool(wait_for(lambda: receiver.of_kind("held"))), "the custom webhook receives a `held` event")
    holds = wait_for(lambda: [h for h in as_list(env.hub_call("list_command_holds")) if h.get("spoke_id") == env.spoke_id])
    check(bool(holds), "the hub lists the command hold")
    env.spoke_call("clear_simulated_errors")
    env.spoke_call("release_command_hold")
    held = wait_for(lambda: [e for e in env.hub_errors(kind="held") if e.get("command") == "tip_pickup"])
    check(bool(held), "the held error is still on the hub after the hold is released")


def scenario_prompt(env: Env, receiver: Receiver) -> None:
    print("\nC. Operator prompt (best effort)")
    open_session(env, hold_on_error=False, profile="standard")
    inject_z_error(env)
    outcome: dict[str, Any] = {}
    worker = threading.Thread(
        target=lambda: outcome.update(result=env.command("tip_pickup", channels=[1], tip_pool=TIP_POOL)), daemon=True
    )
    worker.start()
    prompts = wait_for(lambda: env.spoke_call("get_spoke_state").get("pending_operator_prompts"), 25)
    if not prompts:
        worker.join(timeout=30)
        env.spoke_call("clear_simulated_errors")
        skip("operator prompt", "no prompt appeared (the injected error cleared on the standard profile's retry); "
             f"command result: {str(outcome.get('result'))[:120]}")
        return
    prompt = prompts[0]
    check(bool(wait_for(lambda: receiver.of_kind("operator_prompt"))), "the custom webhook receives `operator_prompt`")
    check(env.spoke_call("get_spoke_state").get("status", {}).get("status") == "error", "spoke status is `error` while it waits")
    on_hub = wait_for(lambda: [e for e in env.hub_errors(kind="operator_prompt")])
    check(bool(on_hub), "the hub records the prompt")
    row = wait_for(lambda: (env.hub_row() or {}).get("session_prompts"))
    check(bool(row), "the hub row shows the waiting session prompt")
    actions = prompt.get("top_level_actions") or []
    action = next((a for a in ("cancel", "abort") if a in actions), actions[0] if actions else "abort")
    env.spoke_call("resolve_operator_prompt", error_uuid=prompt["error_uuid"], action=action)
    worker.join(timeout=60)
    check(bool(wait_for(lambda: receiver.of_kind("operator_prompt_resolved"))), "the webhook receives `operator_prompt_resolved`")
    resolved = wait_for(lambda: [e for e in env.hub_errors(kind="operator_prompt") if e.get("resolved_at")])
    check(bool(resolved), "the hub marks the prompt answered")
    env.spoke_call("clear_simulated_errors")


def scenario_pending(env: Env, kind: str, seconds: float) -> None:
    """Leave an error waiting for a person so the dashboard's current state can be looked at."""
    print(f"\nPending {kind}: an error that waits until you release it")
    open_session(env, hold_on_error=(kind == "hold"), profile="cancel_all" if kind == "hold" else "standard")
    inject_z_error(env)
    outcome: dict[str, Any] = {}
    worker = threading.Thread(
        target=lambda: outcome.update(result=env.command("tip_pickup", channels=[1], tip_pool=TIP_POOL)), daemon=True
    )
    worker.start()
    if kind == "hold":
        waiting = wait_for(lambda: env.spoke_call("get_command_hold").get("state") == "held", 30)
    else:
        waiting = wait_for(lambda: env.spoke_call("get_spoke_state").get("pending_operator_prompts"), 30)
    if not check(bool(waiting), f"the instrument is waiting on a {kind}", str(outcome.get("result"))[:200]):
        return
    print(f"  spoke status on the hub: {(env.hub_row() or {}).get('status')}")
    print("\n  Look at the hub now:")
    print(f"    overview:   {env.hub_http}/")
    print(f"    instrument: {env.hub_http}/spokes/{env.spoke_id}")
    if seconds > 0:
        print(f"\n  Leaving it waiting for {seconds:g} s...")
        time.sleep(seconds)
    else:
        try:
            input("\n  Press Enter to release it and finish... ")
        except EOFError:
            time.sleep(30)
    env.spoke_call("clear_simulated_errors")
    if kind == "hold":
        env.spoke_call("release_command_hold")
    else:
        prompts = as_list(env.spoke_call("get_spoke_state").get("pending_operator_prompts"))
        if prompts:
            actions = prompts[0].get("top_level_actions") or []
            env.spoke_call("resolve_operator_prompt", error_uuid=prompts[0]["error_uuid"],
                           action=next((a for a in ("cancel", "abort") if a in actions), actions[0] if actions else "abort"))
    worker.join(timeout=60)
    print("  released.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spoke-url", required=True, help="the spoke's own MCP URL, e.g. http://localhost:8001/mcp")
    parser.add_argument("--hub-url", required=True, help="the hub's MCP URL, e.g. http://localhost:8000/mcp")
    parser.add_argument("--spoke-id", required=True, help="the spoke's id in the hub")
    parser.add_argument("--token", default=os.environ.get("HAMILTON_MCP_AUTH_TOKEN"))
    parser.add_argument("--spoke-token", default=os.environ.get("HAMILTON_MCP_SPOKE_TOKEN"))
    parser.add_argument("--webhook-port", type=int, default=0, help="port for the test receiver (default: any free port)")
    parser.add_argument("--webhook-host", default="127.0.0.1", help="address the SPOKE can reach this PC on")
    parser.add_argument("--skip-prompt", action="store_true", help="skip scenario C")
    parser.add_argument("--scenarios", default="ABC", help="which scenarios to run, e.g. BC to rerun without A (default ABC)")
    parser.add_argument("--leave-pending", choices=("prompt", "hold"),
                        help="instead of the scenarios, leave one error waiting (an operator prompt, or a held command) "
                             "until you press Enter, so you can look at the dashboard while it needs attention")
    parser.add_argument("--pending-seconds", type=float, default=0, help="with --leave-pending: wait this long instead of for Enter")
    parser.add_argument("--force", action="store_true", help="start a session even if the spoke looks busy")
    args = parser.parse_args()

    env = Env(args)
    if not preflight(env, args.force):
        return 2
    receiver = Receiver(args.webhook_port)
    hook = f"http://{args.webhook_host}:{receiver.port}/events"
    env.spoke_call("subscribe_command_events", url=hook, kinds=["error", "held", "operator_prompt", "operator_prompt_resolved"])
    try:
        wanted = "" if args.leave_pending else args.scenarios.upper()
        if args.leave_pending:
            scenario_pending(env, args.leave_pending, args.pending_seconds)
        if "A" in wanted:
            scenario_plain_failure(env, receiver)
        if "B" in wanted:
            scenario_hold(env, receiver)
        if "C" in wanted and not args.skip_prompt:
            scenario_prompt(env, receiver)
    finally:
        for cleanup in (
            lambda: env.spoke_call("clear_simulated_errors"),
            lambda: env.spoke_call("unsubscribe_command_events", url=hook),
            lambda: env.spoke_call("close_session"),
        ):
            try:
                cleanup()
            except Exception as exc:  # noqa: BLE001 - best effort, the session may already be gone
                print(f"  (cleanup: {exc})")
        receiver.stop()
        osess.close_connections()

    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, {sum(r[0] == 'SKIP' for r in results)} skipped")
    for _, name, detail in failed:
        print(f"  FAILED: {name} -- {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
