# SDK Studio

Hamilton SDK Studio is a desktop app for building and running instrument flows by dragging command cards onto a canvas. Every card is one SDK command (or a loop, a condition, a variable change); you can run the whole flow or any part of it, watch the deck in 3D while it runs, and turn the flow into a Python script when it is done.

It replaces the STAR and Vantage Demo apps: the same drag-and-drop building, with variables, loops and conditions, saved flows, a command list that grows with the SDK, and one app for both instruments.

- **One app for both instruments.** A VENUS install is a STAR or a Vantage, never both, so Studio reads which one this PC has (the same check the installer makes) and shows it. There is nothing to choose.
- **Runs through the MCP server.** Every card goes through the same MCP spoke the [AI Assistant app](../Hamilton%20AI%20Assistant/ai-assistant-app.md) and scripts use, so a run gets the spoke's command journal and its hold-on-error recovery.
- **Generate Script is built in.** A flow becomes a normal SDK script that passes the [script validator](../mcp_server/mcp-guide.md).

## Installing

Tick **Install Hamilton SDK Studio app** in `VenusPythonSdkInstaller.exe`, in the repository root. It needs the MCP server, so ticking it ticks **Install MCP server for AI agents** too. Then open `HamiltonSDKStudio.exe` in this folder.

## The window

| Area | What it is |
|---|---|
| **Icon rail** (left) | One icon per command group: Liquid Handling, Transport, Tips, Deck & Labware, Instrument, Devices, Flow Control, Advanced. Hover for the name. Click one to open its commands. The magnifier searches every command. |
| **Top bar** | The flow's name (click to rename), the instrument type, the connection pill, **Run**, **Deck**, **Variables**, **Generate script** and **File**. |
| **Canvas** (middle) | Your flow: one column of cards. |
| **Right panel** | The settings of the selected card, or the Variables list. It closes when nothing is selected. |
| **Deck view** (bottom) | The 3D deck, when switched on with **Deck**. |

## Connecting

Click the connection pill (it reads **No session** until you do) or press **Run**. The dialog asks:

| Setting | Meaning |
|---|---|
| **Mode** | **Simulation** (nothing moves) or **Live instrument**. Studio never chooses this for you. |
| **Instrument** | Shown, not editable: the instrument installed on this PC. |
| **Deck layout** | A blank deck, the last layout used, or one of the saved layouts. |
| **Connect the instrument now** | On by default. Turn it off to start the session only. |
| **Initialize on connect** | Also home the arms and initialize the instrument. |

Starting a session or connecting the instrument can take a minute while it initializes. A spinner shows in the dialog and in the pill ("Starting…", "Connecting…") for as long as it works, so you can close the dialog and see that it is still going; a card shows a spinner beside "Running…" while its command runs.

The pill shows where you are: **No session**, **Simulation · not connected** (a session is open but the instrument is not connected yet, amber dot), or **Simulation · STAR** / **Live · STAR** (connected). Click it again to connect later or to end the session.

**Starting a session without connecting.** Commands that need the instrument fail until it is connected ("Instrument must be connected before calling this command"). Connect it from the pill's **Connect instrument** button, or put a **Connect Instrument** card (Instrument group, Session) in the flow where it should happen, for example after the deck is set up.

**Only what this instrument can run.** When the instrument connects, Studio reads its configuration (how many 1 mL, 5 mL and MagPip channels, whether it has an MPH96 head, an iSWAP or IPG gripper, an autoload) and hides the commands it cannot run: no 5 mL channels, no 5 mL commands; no MPH96, no MPH96 commands, and so on. Hover the connection pill to see what was found. A group with nothing left to show disappears from the rail. The command list shows an **Also show N commands this instrument can't run** switch when anything is hidden; a card already in the flow stays, marked "This instrument doesn't have what this command needs". Nothing is hidden before the instrument connects, or if its configuration cannot be read.

**Closing the app ends the session.** When you close the window, Studio stops a flow that is running (after the command in progress finishes, releasing a card held after an error), closes the session so VENUS unloads its method, and only then exits. This can take up to about 45 seconds if a long command is in progress; after that the app is closed regardless. If the app is killed instead (Task Manager, a crash), the session can be left open; Studio notices at the next start and asks before replacing it.

**VENUS busy.** Starting a session stops whatever method VENUS is running, including one started by the AI Assistant. If VENUS is running something, Studio says so and asks before going on. When the busy session is Studio's own (an earlier window, for example) the message says that instead.

## Building a flow

- **Send to instrument:** the settings panel has a **Send to instrument** button under any SDK command, for a card or for a command you opened from the drawer without adding it. It runs the command once, without putting it in the flow. The result (the returned values, or the reason it failed) shows above the button, and the flow's own card results are left untouched. It needs a session, and is disabled while a run is in progress or required settings are missing.
- **Card options:** right-click a card (or use its `⋯` button) for the run options, range markers, Duplicate, Skip and Delete. Hold `Ctrl` while dropping a dragged card to copy it instead of moving it.
- **Add a card:** drag a command from the rail's drawer onto the canvas to add it; its settings open at once. Clicking a command only opens its settings, with **Add to flow** (appends it with the values you entered), **Send to instrument** and **Cancel**. That panel stays open when you click elsewhere, until you add the command or cancel (the `✕` also cancels). The drawer slides out below the top bar and closes after a drop, when you click anywhere outside it, or on `Esc`. The settings and Variables panels on the right slide in and out the same way.
- **Order and nesting:** drag a card by its grip (⋮⋮) to move it, and drop it between cards or into a loop or If lane.
- **Settings:** click a card. The panel on the right shows its fields; leave one empty to use the SDK default. A field marked **\*** is required, and the card shows **Needs: ...** until it is filled. Commands with many options show the main ones and fold the rest under **Advanced**. Settings objects (such as aspirate settings) are groups you can open.
- **Choices have names.** A field that takes one of a fixed set shows the names, not numbers: Set Status Light offers White, Red, Green…, and settings such as the capacitive LLD offer Off, Low, Medium…. Fields that take either one value or one per channel use the single-value control.
- **What a card shows:** the values you set, as chips, for example `Positions Plate1@col:1` and `Volume 50`, so the flow can be read without opening each card.
- **Card buttons** (on hover): **⋯** run options, ◉ skip the card (a skipped card is left out of runs and kept as a comment in generated scripts), ⧉ duplicate, ✕ delete.
- **Positions** use the SDK's selector text, such as `Plate1@A1:H1` or `Plate1@col:1`.
- **Autosave.** The open flow is remembered in the app between starts; use **File → Save** to keep it as a file (below).

Keyboard: `Ctrl+K` or `/` search, `Ctrl+S` save, `Esc` closes a menu, dialog or the flyout.

## Finding names and values

Some fields are easier to fill in by searching than by typing. They have a **Choose…** button beside their label:

**Labware type** (the `labware_definition` field of Add Plate, Add Carrier and similar). Search the SDK's labware catalog by words (`nunc 96`) and filter by category (carrier, plate, tip rack, reservoir, tube rack, tube, adapter, lid). Carriers show how many deck tracks they take. It is the same catalog the MCP `search_labware` tool searches, and the value inserted is the labware id the SDK uses (for example `Nun_96_Fl`).

**Liquid class.** Two ways:
- **Browse the library:** every liquid class for this instrument's type, with filter chips for the tip or head (50 / 300 / 1000 µL, high / standard / low volume, filter, needle, 5 mL, 96 or 384 head), the liquid (water, ethanol, DMSO, serum, ...) and the dispense mode (jet, surface, empty, part volume, aliquot), plus a words box. The filters match words in the class names, which are not always regular, so use the words box when a chip finds too little.
- **Find one for a transfer:** asks the SDK, which knows the tips and pipetting devices fitted on this instrument. Enter the liquid, the dispense mode, the volume and the tip pool, and the best classes come back first. It needs a session, and the tip pool (the tips decide which classes fit).

**Positions.** Click wells on the plate instead of typing a selector:
- Choose labware on the deck (listed with its size, read from the instrument) or type a name and a format (6 to 384 wells, or a custom size).
- Click a well to toggle it, drag a rectangle to add (or to remove, when you start on a selected well), click a column number or row letter to take the whole column or row, or **Select all**.
- The selector is written for you in the shortest form: `Plate1@all`, `Plate1@col:1:3,5`, `Plate1@row:A`, `Plate1@A1:C3,E1`. Turn off **Use ranges** to list wells one by one in the order you clicked them (the order the channels will take them).
- **Add another labware** starts a new selection and joins them with `;` (`Plate1@col:1;Plate2@row:A`). Click a chip to edit it. Reopening the wizard on a field that already has a value shows its parts as chips.
- Reservoirs and tube racks are addressed whole (`@all`), so the wizard offers just that.

Fields that name something on the deck (a plate, a carrier, a tip pool) suggest the names as you type: the labware on the instrument now, plus the names that Add cards in this flow define, so you can build a flow before running it. The instrument reports names in lower case; where the flow spells one differently, your spelling is offered.

The same wizards fill **variables**: a variable can be of type **Labware type**, **Liquid class** or **Positions**, and then has the same **Choose…** button. Use it as `{{name}}` like any other variable.

## Variables

A variable is a named value any card field can use. Open **Variables** (top bar; it slides out on the right), add one, and choose its type: **Text**, **Number**, **List** (comma separated, `1, 2, 3`), **Yes / No**, or **Labware type**, **Liquid class** or **Positions** (text that a [wizard](#finding-names-and-values) fills in).

- Use it in a card field as `{{name}}`, or click the `{ }` button beside the field to insert it at the cursor.
- A field that is only one reference gets the variable's real value (so `{{volume}}` in a number field sends a number, and `{{wells}}` a list). A reference inside longer text is replaced by the value's text, so `{{plate}}@col:{{col}}` becomes `DestPlate@col:3`.
- **Numbers and text.** A loop counter or a Number variable is a number, but some parameters want text (a carrier *site* is the text `"1"`), and the reverse. Studio fits a referenced value to what the command accepts: a number going into a text-only parameter is sent as its text, and numeric text going into a number-only parameter is sent as the number. Values you typed by hand are never changed.
- **Converting explicitly.** Add a conversion after a bar: `{{site|str}}` (text), `{{x|int}}` (whole number), `{{x|float}}` (decimal number), `{{x|bool}}` (yes / no), `{{x|list}}` (a list; text is split at commas). It works inside longer text too (`Rack{{site|int}}`), and a value that cannot be converted (`{{x|int}}` on `abc`) stops the card with a message naming it. The `{ }` button does it for you: when the field holds a reference, its menu offers **Convert {{site}} to text / a whole number / a decimal number / yes / no / a list** and **Remove the conversion**. The same menu lists the counters your loops and Set Variable cards provide, not just the variables in the panel. Renaming a variable keeps its conversions.
- **Changing a variable's own type.** Pick another type in the Variables panel. Generated scripts follow the same rules (`site=str(site)`, `int(N)`), and Import Script turns `str(X)`, `int(X)`, `float(X)` and `bool(X)` back into conversions.
- Fields that are dropdowns or Yes/No choices cannot take a variable; text, number and list fields can.
- **Ask before each run** shows a small dialog with the variable's current value at the start of every run, so a flow can be reused with a different volume without editing it.
- Renaming a variable updates every card that uses it. A reference to a name that does not exist is marked in red on the card, and the run will not start until it is fixed.
- The panel shows how many cards use each variable.

## Running

Press **Run** to run the whole flow, or open its **▾** menu:

| Choice | What it runs |
|---|---|
| **Run all** | Every card, in order. |
| **Run selected card only** | Just the selected card. |
| **Run from selected card** | The selected card and everything after it. |
| **Run up to selected card** | Everything up to and including it. |
| **Run range** | Between a **Start** and an **End** marker: set them from any card's **⋯** menu (**Set range start here**, **Set range end here**). The flags show on the cards. |
| **Preview what will be sent…** | A dry run: how many commands would be sent, without sending any. See [Preview](#preview). |

The same options are on each card's **⋯** menu (**Run this card only**, **Run from here**, **Run up to here**).

**Stop and Pause** appear while a flow runs. Both take effect after the command that is running now finishes, because a command already sent to the instrument cannot be taken back. **Pause** can be resumed with **Continue**; **Stop** ends the run.

**While it runs.** Each card shows its state by the colour of its left edge and a label: **Running…**, **Done 1.2 s**, **Failed**, **Held**, **Skipped**. A finished card has a **Result** you can open: it shows what the command returned (the instrument's return parameters, for example the serial number), not the whole response. **Show full response** beside it shows everything.

**When a command fails.** Studio starts sessions with the spoke's hold-on-error on: the failing card is **Held** and shows the instrument's message with two buttons. **Retry** runs the card again (after you fixed the cause, for example a missing tip rack); **Stop run** gives up and the run ends at that card with an error. A card that fails for another reason (a bad value, no session) stops the run with its message.

Before a run starts, Studio checks the cards it is about to run and refuses with the first problem: a missing required field, an undefined variable, a bad condition, a stray Break.

## Subflows (tabs)

Tabs along the top of the canvas split a flow into pieces. **Main** is always the first tab on the left and cannot be renamed, moved or deleted; each subflow is a tab of its own after it.

- **Add:** click **+ Subflow**; the new tab is named for you to type over. **Rename:** double-click its name (names must be different from every other tab, including Main). **Reorder:** drag a subflow tab. **Delete:** the `✕` on the tab (you are asked if it has cards or is still called).
- **Use one:** add a **Run Subflow** card (Flow Control) and choose the subflow. Its cards run there, then the flow carries on. The same subflow can be run from several places, from inside loops and If cards, and from other subflows (a subflow cannot run itself, directly or through others). The card has a **runs Name ›** chip that opens the tab. Renaming a subflow updates its Run Subflow cards.
- **Variables are shared** by every tab: a Set Variable card in a subflow changes the variable for the cards after the call, and a loop counter is visible inside the subflows its loop calls.
- **Organize:** drop a card on another tab to move it there (hold `Ctrl` to copy it); drop a command from the drawer on a tab to add it to that tab.
- **Run** runs the tab on screen (the button says **Run subflow** on a subflow tab), with the same run-from, run-to and range options inside that tab. A subflow run on its own may use variables that Main sets. Cards in a subflow show their status in its tab while a run goes through it.
- **Files and scripts:** a saved flow keeps all its tabs. Generate Script writes each subflow as a function (`def prepare_plates():`, with its cards numbered as on its tab), defined once before the main cards, and each Run Subflow card as a call to it. Variables are module-level, so a function that sets one declares it `global`, matching how tabs share variables in the app. A subflow with a Break or Continue that would end its caller's loop cannot be a function, so it is written out inline at the call (a comment says so). Import Script brings a script in as Main.

## Keeping a result

A command that returns something (the serial number, a tip counter, a liquid level, whether a door is locked) has a **Keep the result** section at the bottom of its settings. Give it a variable name and choose what to keep:

- Every value the command returns is listed with its own box (for Get Serial Number: **Everything returned** and **Serial Number**). Type a variable name beside each value to keep, as many as you like; leave a box empty to skip that value. Two boxes can even keep the same value under two names.
- Each value shows its type beside its name (text, integer, number, true/false, object, list of text, ...). Values seen in a real result get their type from what was returned.
- A **list** can be kept whole, or one item at a time: under a list value, enter its position (0 is the first) and click **Add item**, then name the variable. You can also type `tracks[0]` or `candidates[1].name` in the "another value" box. A script can read a position (`response.return_parameters.tracks[2]`) but not a field below it; those are kept when run in Studio only and Generate Script says so.
- To use an item of a list you already kept whole, a Set Variable card does it with an expression such as `tracks[2]`.
- The card then shows **keeps {{serial}}**, and after the run one **Saved {{serial}} = 0042** line per value under its result.
- From that card on, `{{serial}}` can be used in any field, in the conditions of If and While cards (`serial == "0042"`, `info["totalPlates"] > 0`) and in Set Variable. The `{ }` menu lists it under the names that come from a card, and conversions such as `{{serial|int}}` apply as for any variable.
- If the command's result has no such value when it runs, the card stops with a message naming it. A [preview](#preview) cannot know a result, so it leaves what depends on it unknown and says so in its notes.
- Some commands return values that are not listed ahead of time (Add Carrier returns `labwareName`, the id it gave the carrier). Run the card once and its values appear in the **Keep** list, or type its name in the box under the list and click **Add**.
- If a run stops, the failed card shows the reason, and the same message appears in a notification that stays until you click it.
- Generate Script writes `serial = response.return_parameters.serial_number` after the call, and Import Script turns that line back into the setting. Commands that return nothing have no section.

## Loops and logic

The **Flow Control** group has cards that hold other cards. Drop cards into their lanes; the lane is indented under the card, and cards are numbered `1`, `2`, `2.1`, `2.2`, ...

| Card | What it does | Gives the cards inside |
|---|---|---|
| **Repeat** | Runs its cards **Times** times (a number or `{{variable}}`). | `{{i}}` counting from 1 (rename it with **Counter name**) |
| **For Each in Plate** | Once per **column**, **row** or **well** of a plate (formats 6 to 384, or custom rows and columns; wells can go column-wise or row-wise). | `{{col}}` (columns), `{{row}}` (letters A, B, ...), or `{{well}}` (such as `B3`) together with `{{col}}` and `{{row}}`; always `{{index}}` counting from 1 |
| **For Each in List** | Once per item of a comma separated list, or a List variable. | `{{item}}` and `{{index}}` |
| **While** | Repeats while a condition is true, with a safety limit (1000 by default); passing the limit stops the run with an error. | |
| **If / Else** | Runs the **Then** lane if the condition is true, otherwise the **Else** lane. | |
| **Break** / **Continue** | Leave the enclosing loop / skip to its next repeat. | |
| **Set Variable** | Gives a variable a new value calculated from others, such as `volume * 2` or `count + 1`. | Makes the variable available from then on |
| **Ask / Pause** | Stops the run and shows a message on the card; **Continue** carries on, **Stop run** ends it. Optionally keeps what you typed in a variable. | |
| **Wait** | Waits a number of seconds. | |

A loop card shows the variable names it gives (**gives {{col}} {{index}}**), and `{{col}}` is not flagged as undefined inside it. Example, for each column of a 96-well plate: a **For Each in Plate** card (columns) holding a Tip Pickup, an Aspirate from `Buffer`, a Dispense to `DestPlate@col:{{col}}` and a Tip Eject.

### Conditions and values

While, If and Set Variable use a small expression language. Variables are plain names, without braces:

```
volume > 50 and plates_done < 3
col % 2 == 0
max(a, b) * 2
len(wells) > 0
last["status"] == "success"
```

Allowed: numbers, text in quotes, `True` / `False`, variable names, `+ - * / // % **`, comparisons (also chained, `in`, `not in`), `and` / `or` / `not`, `x if cond else y`, lists, indexing and slicing, and the functions `len`, `min`, `max`, `abs`, `round`, `int`, `float`, `str`, `bool`, `sum`. Nothing else: no attribute access, no other function calls, no imports. The expression is checked, never executed as Python.

`last` is the result of the previous command, so `last["status"] == "success"` tests whether it worked.

### Running part of a loop

Picking a loop card (for example with **Run this card only**) runs the whole loop. Picking a card *inside* a loop runs that card **once**, with the loop's variables at their first values (for example `{{col}}` = 1), so a single step can be tried out. **Run from here** on a card inside a loop runs the rest of that one pass and then carries on with whatever follows the loop. **Run up to here** inside a loop runs the loop's repeats, but only its cards up to the chosen one.

### Preview

**Preview what will be sent…** (in the Run menu, the File menu and each card's **⋯** menu) counts the commands a run would send and lists the first ones with the loop variables each would see, without touching the instrument. It also lists anything that would stop the run. A While or If whose condition depends on a command's result cannot be known in advance; the preview assumes it is false and says so, so the real count can be higher.

## Deck view

**Deck** opens the 3D deck from VENUS under the flow. It is the same viewer the AI Assistant and Script Manager use and shows the live deck, so you see carriers and labware appear as the cards that add them run.

- Drag the bar above it to resize, **Maximize** to cover the flow, **Top** / **Default** to change the camera, **Auto-Zoom** (the viewer's own zoom-to-labware switch), **Refresh 3D View** if it falls behind.
- Selecting a card highlights the labware it names (from its `positions`, plate or carrier field, or a text variable holding the name).
- It follows the light / dark theme and reloads when a session starts or the instrument connects. It needs a session in VENUS (simulation counts) to have a deck to show.

## Saving and opening flows

The **File** menu:

| Item | What it does |
|---|---|
| **Save** (`Ctrl+S`) / **Save as…** | Saves the flow as `<name>.studio.json` in `Hamilton SDK Studio\backend\data\flows\`. It holds the cards, their nesting, and the variables. |
| **Open…** | Lists saved flows, newest first, with their card counts. |
| **Export flow file…** / **Import flow file…** | Download or load a `.studio.json` file, to move a flow to another PC. |
| **Import script…** | Turns an SDK script into cards (below). |
| **Preview what will be sent…** | See [Preview](#preview). |
| **Reload command definitions** | Re-reads the command definition files (below). |
| **New flow** | Clears the canvas. |

## Generate script

**Generate script** turns the flow into a standalone Python script and checks it with the same static validator the MCP server uses, so you see *Passes the SDK script validator* or its errors and warnings (with rule ids and line numbers) before you copy anything.

- **Simulation** sets the script's `SIMULATE` constant.
- Each variable becomes a constant at the top (`VOLUME = 50`), and a field that uses it refers to it; text mixed with a variable becomes an f-string (`f"{PLATE}@col:{COL}"`).
- Options become the SDK's own types: `WellOrder.COL_ASC`, `AspirateSettings(...)`, with the imports added.
- Loops, conditions and Set Variable become real `for`, `while`, `if` / `else`, `break`, `continue` and assignments. A **While** keeps its limit with a counter that raises an error when passed.
- Skipped cards stay as comments. A **Connect Instrument** card is a comment, since the SDK client connects when its `with` block opens.
- An **Ask / Pause** card cannot ask anyone in a script: it becomes a print line and a warning, and a variable it was to fill is added to the constants for you to set.
- Cards for the pure-Python devices (heater cooler, ODTC, ...) get their own client in the same `with`.
- **Copy**, **Download .py**, or **Save to MCP scripts**, which puts the script in the MCP spoke's script store where `run_script` and AI agents find it.

The validator's warnings are worth reading: a script that picks up tips without setting up the tip counters, for example, gets W035.

## Import script

**File → Import script…** reads a script (paste it or choose a `.py` file), shows what it found, and then adds it to the flow or replaces the flow. Nothing in the script is run.

- `star.<command>(...)` calls (and `hhc.`, `odtc.`, ... for devices) become cards. Enum members, labware catalog names and settings objects become the plain values the cards store.
- Top-level constants (`VOLUME = 50`) become variables, and uses of them become `{{references}}`.
- `for x in range(1, n + 1)` becomes **Repeat**, `for x in [...]` **For Each in List**, `while`, `if` / `elif` / `else`, `break`, `continue`, `x = ...` / `x += 1` and `time.sleep(n)` become their cards.
- What cannot be worked out without running the script is skipped with a note: values computed by other code, commands the SDK does not have, loops over anything other than the patterns above (their cards are imported once, outside any loop). Read the notes before relying on the result.

A script made by **Generate script** imports back to the same flow.

## Adding or changing commands

The command list is the SDK's own, read live, so a new SDK method appears in Studio by itself, in a group chosen from where it lives in the SDK, with a form built from its signature. What Studio cannot know from the signature (a friendlier name, a group, help text, a range) comes from small JSON *definition* files you can edit without rebuilding anything.

- Shipped definitions: `Hamilton SDK Studio\backend\command_defs\*.json`.
- Your own: `Hamilton SDK Studio\backend\data\command_defs\*.json`. They are read after the shipped ones and win where they overlap.
- After editing, choose **File → Reload command definitions**.

```json
{
  "version": 1,
  "commands": {
    "tip_pickup": {
      "label": "Pick Up Tips",
      "group": "Tips",
      "subgroup": "",
      "description": "Pick up tips from a tip pool or from positions.",
      "hidden": false,
      "params": {
        "tip_pool": { "label": "Tip pool", "help": "Name of the tip pool.", "order": 1 },
        "channels": { "label": "Channels", "order": 0, "advanced": false }
      }
    }
  }
}
```

The key is the SDK method name. Everything is optional. For a parameter: `label`, `help`, `order` (lower comes first), `advanced` (fold it under Advanced), `min` / `max` (shown as a hint), `choices` (a list, with `"widget": "enum"`), and `widget` to force a kind of field: `string`, `int`, `float`, `bool`, `enum`, `int_list`, `float_list`, `string_list`, `number_or_list`, `scalar`, `object`, `json`, or a name hint (`positions`, `tip_pool`, `carrier`, `plate`, `track`, `liquid_class`). Groups are Liquid Handling, Transport, Tips, Deck & Labware, Instrument, Devices and Advanced; set `"hidden": true` to remove a command from the palette. A malformed file is skipped with a warning in the app's log rather than breaking the list.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| **"VENUS is running a method"** when connecting | Another application (or the AI Assistant) has a method running; connecting stops it. Finish or stop that first, or continue if you mean to. |
| A card is **Held** with "Instrument must be connected before calling this command" | The session has no connected instrument yet. Click **Retry** after connecting from the pill, or **Stop run** and add a Connect Instrument card first. |
| **Run** opens the connection dialog | There is no session yet; start one from the dialog and press Run again. |
| "N problem(s) stop this run" | The first problem is in the message: a missing field, an undefined `{{variable}}`, a bad condition or a Break outside a loop. Cards with a problem are marked. |
| "The loop ran more than its limit" | A **While** never became false. Fix its condition, or raise **Stop after at most**. |
| The instrument shows **STAR** in italics with "No VENUS install found" | Studio found no VENUS installation on this PC, so it assumed a STAR. The command list is the STAR one. |
| The deck view is empty or says it is waiting | No session is open in VENUS yet. Start one (simulation counts), then **Refresh 3D View** if needed. |
| A command you expect is not in the palette | It is not an SDK command for this instrument type (the Vantage and STAR lists differ), this instrument was found not to have what it needs (tick **Also show … commands this instrument can't run** in the flyout), or a definition file hides it. |
| "Choose the tip pool the transfer will use" in the liquid class finder | The SDK needs the tips to know which classes fit. Add the tip rack (so its tip pool exists) and pick the pool. |
| A labware, tip pool or carrier box offers no suggestions | Suggestions come from the labware on the instrument (needs a session) and from Add cards in the flow. Add the labware first, or run the cards that add it, and the names appear. |

## Coming from the Demo apps

| In the Demo apps | In SDK Studio |
|---|---|
| A separate app for STAR and for Vantage | One app; the instrument comes from the VENUS install |
| "Resume From Here" | **Run from here**, **Run up to here**, **Run this card only** and **Run range** |
| Commands hand-written in the app | The SDK's own list, plus editable definition files |
| No saved flows (only a downloaded script) | **File → Save** / **Open**, plus export and import of flow files |
| Flat list of cards | Loops, conditions and variables, with cards inside cards |
| Settings spread over many fields | Settings objects as groups under the command, advanced fields folded away |
| Run results in the Terminal Trace tab | The result on each card; the full trace is in the [Log Viewer](../Hamilton%20Log%20Viewer/log-viewer.md) |
