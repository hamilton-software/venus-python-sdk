# Live-test scripts (FM STARlet, 2026-09-23)

Scripts and small drivers used for live-instrument testing against a real FM STARlet. They are not part
of the package or its tests. Import a script to a spoke with `import_script` (or copy it into the spoke's
`mcp_scripts` folder), then run it with `run_script`.

Deck they assume: tip carrier 480 on track 1 (`TIP_CAR_480BC`); site 1 = 1000 uL tips, sites 2-3 = 300 uL,
sites 4-5 = 50 uL, all non-filter. Every rack needs an explicit `labware_id` (VENUS names racks by type, so two
racks of one type collide otherwise).

| Script | Test | What it does |
|---|---|---|
| `t1_pickup_eject.py` | T1 | Init, confirm the tip counter, one 8-tip pickup and eject. |
| `t2_pause_abort.py` | T2 | 6 cycles of pickup / hold 4 s / eject, long enough to pause, resume and abort. |
| `t3_no_tip_error.py` | T3 | Initializes + resets the tip counter so VENUS thinks used positions are full; the pickup then raises a real "No tip picked up" error for the human gate. |
| `diag_tipcounter.py`, `diag2.py` | diagnostics | Read/initialize/set/show the tip counter (simulation only). |

VENUS will not hand out tips from a pool until its tip counter has been *shown and confirmed*
(`tip_pool_show_tip_counter`, answered at the VENUS PC); initialize/reset/set alone are not enough. Each script
therefore waits for a person at the VENUS PC once, right after `instrument_init`.

Drivers (plain Python, no dependencies; they talk to the hub's MCP endpoint at `http://localhost:8000/mcp` and
use spoke id `FM STARlet` -- edit both for another setup):
- `hub_call.py <tool> [json-args]` -- call any hub tool; `--list` lists them. Use `call_tool_on` for spoke tools.
- `follow_run.py <script>` -- start a REAL run and narrate stdout, prompts (with options), decisions and the result.
- `t2_drive.py` -- run T2 and issue pause / resume / abort at fixed points.

These start real hardware runs (`simulate=False`). Only use them with a person at the instrument and the spoke's
`HAMILTON_MCP_ALLOW_HARDWARE` set on purpose.
