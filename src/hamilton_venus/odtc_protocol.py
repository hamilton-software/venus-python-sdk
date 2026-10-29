"""PCR protocol data model + XML builder for the Inheco ODTC.

The ODTC does not take setpoints directly -- it runs a named ``<Method>`` /
``<PreMethod>`` from a ``<MethodSet>`` XML document (the vendor HSL calls this
``SetMethod``/``DownloadProtocol``). This module lets a protocol be built in
Python (:class:`ODTCProtocolBuilder`) instead of hand-authoring the XML, and
renders it to the exact schema the device expects.

The schema was reverse-engineered field-by-field from a real, complete sample
(``Inheco ODTC/PLR001_ODTCProtocols.xml``, two full PCR programs) -- there is
no vendor XSD. Two fields are deliberately **not** reverse-engineered and are
passed through opaque, defaulted from that sample:

* ``OverShoot*`` (``OverShootSlope1``, ``OverShootTemperature``,
  ``OverShootTime``, ``OverShootSlope2``) -- these look auto-calculated by
  Inheco's own protocol editor per temperature transition; :class:`ODTCStep`
  defaults them to "no overshoot" -- slopes ``0.1`` (the smallest value; never
  ``0``: a real unit rejects a zero ramp rate with ``MethodSet error 262:
  VALIDATION_FAILED``, and Hamilton's sample file never uses one), temperature
  and time ``0`` -- with an advanced override, rather than guessing a formula.
* ``Variant`` / ``PlateType`` / ``FluidQuantity`` -- model/plate/volume codes with
  no enumeration in the HSL or HSI. Their meaning below was worked out from
  Inheco's own methods: ``Variant`` is ``960000`` (96-well ODTC) or ``3840000``
  (384-well ODTC), ``PlateType`` is ``0``, ``FluidQuantity`` is the Script Editor's
  "Fluid" volume drop-down (``0``/``1``/``2``, or ``-1`` for unspecified).

Cycling (e.g. "repeat these 3 steps 30 more times") is expressed in the wire format
by ``GotoNumber`` / ``LoopNumber`` on exactly one step -- the last one before
the repeat -- confirmed against both real programs in the sample file.
``LoopNumber`` is the number of *extra* passes, which Inheco's Script Editor
calls "Cycles" (so ``LoopNumber=3`` runs the steps four times in all).
:meth:`ODTCProtocolBuilder.add_cycle` lowers a Python-level cycle into that
shape automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

_DEFAULT_VARIANT = 960000

#: The Script Editor's "Fluid" drop-down, keyed by the wire format's ``FluidQuantity``.
FLUID_QUANTITY_RANGES_UL = {0: "10-29 ul", 1: "30-74 ul", 2: "75-100 ul"}

#: The block never overshoots past this absolute temperature (95 C + 7 C, 98 C + 4 C
#: in the editor's own output); when the cap binds, the editor turns the rest of the
#: overshoot into a hold time at the peak.
_MAX_OVERSHOOT_PEAK_C = 102.0
_COOLING_BREAKPOINTS_C = (60.0, 40.0, 20.0)


@dataclass(frozen=True)
class EditorTuning:
    """Ramp slopes and overshoot the Inheco Script Editor writes for one fluid volume.

    All values are read from the editor's own output (Script Editor 3.0.1, the same
    3-step PCR saved once per fluid setting -- ``Volume Comparison.xml``). The
    unit's ramp rates and overshoot are tuned to the liquid volume, so using the
    editor's numbers instead of one fixed slope gets the liquid to temperature
    faster and with less error.

    Heating always uses the maximum slope. Cooling slows down as the block nears
    ambient, so it is done in segments whose slope depends on the temperature the
    segment *starts* at (``cooling_slopes``: above 60 C, 60-40, 40-20, 20 and below).
    Overshoot is described for the four transitions of a 3-step PCR at the editor's
    default temperatures (95 / 60 / 72 C); each is ``(peak offset in C, hold time in s)``
    except ``anneal``/``extension`` whose hold time is 0.
    """

    heating_slope: float
    cooling_slopes: tuple[float, float, float, float]
    initial_denaturation: tuple[float, float]  # heating from the start temperature (25 C) to ~95 C
    denaturation: tuple[float, float]  # heating from the extension step (72 C) to ~95 C
    annealing_undershoot: float  # cooling from ~95 C to ~60 C
    extension_overshoot: float  # heating from ~60 C to ~72 C

    def cooling_slope(self, from_temperature: float) -> float:
        for slope, floor in zip(self.cooling_slopes, _COOLING_BREAKPOINTS_C, strict=False):
            if from_temperature > floor:
                return slope
        return self.cooling_slopes[3]


#: Keyed by ``FluidQuantity``. The last cooling slope for fluid setting 2 (0.20) is an
#: estimate -- the editor file has no cooling segment that low for it; the other
#: bands and settings are exact.
EDITOR_TUNING: dict[int, EditorTuning] = {
    0: EditorTuning(4.4, (2.2, 1.4, 0.8, 0.25), (6.5, 0.0), (5.3, 0.0), 4.3, 4.2),
    1: EditorTuning(4.4, (2.0, 1.3, 0.75, 0.23), (7.0, 6.0), (7.0, 3.4), 4.5, 9.0),
    2: EditorTuning(4.4, (1.8, 1.2, 0.65, 0.20), (7.0, 9.1), (7.0, 5.9), 5.5, 11.3),
}


@dataclass
class ODTCStep:
    """One block-temperature step in a PCR protocol.

    Each step ramps the block to *temperature*, holds it there, then moves on.
    The ranges below are the ones Inheco's own methods use; the unit validates a
    method when it is uploaded and rejects values it cannot do (e.g. a zero ramp
    rate), so an out-of-range value fails at upload time.

    Attributes
    ----------
    temperature:
        Block target in degrees C (wire ``PlateauTemperature``). Typically 4-99.
    hold_seconds:
        How long to hold at *temperature*, in seconds (``PlateauTime``). ``0``
        means "ramp there and carry straight on" (used for the intermediate
        points of a cooling ladder). Typically 0-43000 (about 12 h).
    slope:
        Ramp rate to reach *temperature*, in degrees C per second (``Slope``).
        Must be above 0. Typically 0.18-5.0; the Script Editor uses at most 4.4 for
        heating and 2.2 or less for cooling (see :data:`EDITOR_TUNING`), because
        the block cannot cool as fast as it heats.
    lid_temperature:
        Heated-lid target in degrees C while this step runs (``LidTemp``).
        Typically 30-115; 110 is the usual PCR value that stops condensation on the plate
        seal.
    pid_number:
        Which ``<PID>`` control-loop set of the protocol regulates this step
        (``PIDNumber``); ``1`` unless you add your own with
        :meth:`ODTCProtocolBuilder.set_pids`. Inheco's methods all use ``1``.
    goto_number, loop_number:
        Loop marker, set by :meth:`ODTCProtocolBuilder.add_cycle` -- leave both
        at ``0`` when building a step by hand. On the *last* step of a loop,
        ``goto_number`` is the 1-based number of the step to jump back to and
        ``loop_number`` is how many *extra* passes to make (Inheco's "Cycles").
        Typically goto 0-9, loop 0-58.
    overshoot_slope1, overshoot_temperature, overshoot_time, overshoot_slope2:
        Optional overshoot ("boost") used to reach a target faster: the block is
        driven past *temperature* to ``temperature + overshoot_temperature`` at
        ``overshoot_slope1`` (degrees C/s), held there for ``overshoot_time``
        seconds, then brought back to *temperature* at ``overshoot_slope2``.
        ``overshoot_temperature = 0`` (the default) means no overshoot; the
        slopes must still be above 0. Typically temperature 0-12.6 C, time 0-13.3 s,
        slope1 0.1-4.4, slope2 0.1-2.2. :meth:`ODTCProtocolBuilder.add_pcr` fills
        these in the way Inheco's editor does for the chosen fluid volume.
    number:
        1-based position in the method; assigned by the builder, don't set it.
    """

    temperature: float
    hold_seconds: float = 0.0
    slope: float = 2.0
    lid_temperature: float = 110.0
    pid_number: int = 1
    goto_number: int = 0
    loop_number: int = 0
    overshoot_slope1: float = 0.1
    overshoot_temperature: float = 0.0
    overshoot_time: float = 0.0
    overshoot_slope2: float = 0.1
    # 1-based position in the method; assigned by the builder / renderer.
    number: int = 0


@dataclass
class ODTCPid:
    """One set of temperature-controller (PID) gains, referenced by ``ODTCStep.pid_number``.

    ``p_*``/``i_*``/``d_*`` are the proportional, integral and derivative gains for
    the block while heating and while cooling, and for the lid. The defaults are
    Inheco's (used by nearly all of its methods); the only other set it uses is
    ``100/100, 250/150, 0/0`` for the block. Leave them alone unless Inheco
    gives you tuned values -- wrong gains make the block oscillate or lag.
    """

    number: int = 1
    p_heating: float = 60.0
    p_cooling: float = 80.0
    i_heating: float = 250.0
    i_cooling: float = 100.0
    d_heating: float = 10.0
    d_cooling: float = 10.0
    p_lid: float = 100.0
    i_lid: float = 70.0


@dataclass
class ODTCProtocol:
    """A full ``<Method>`` (cycling program) or ``<PreMethod>`` (simple hold).

    A :class:`ODTCProtocol` with no :attr:`steps` renders as a ``<PreMethod>``
    (block + lid hold only, matching e.g. the sample's ``PLR001_Cool8C``).
    One with :attr:`steps` renders as a full ``<Method>``.

    Normally created with :class:`ODTCProtocolBuilder` rather than by hand; the
    fields are described there.
    """

    method_name: str
    creator: str = "hamilton_venus"
    description: str | None = None
    target_block_temperature: float = 25.0
    target_lid_temperature: float = 110.0
    variant: int = _DEFAULT_VARIANT
    plate_type: int = 0
    fluid_quantity: int = 0
    post_heating: bool = True
    start_block_temperature: float = 25.0
    start_lid_temperature: float = 110.0
    steps: list[ODTCStep] = field(default_factory=list)
    pids: list[ODTCPid] = field(default_factory=lambda: [ODTCPid()])


class ODTCProtocolBuilder:
    """Fluent builder for an :class:`ODTCProtocol`'s step list.

    Steps are auto-numbered ``1..N`` in the order added. With no steps the result
    is a ``PreMethod`` (bring block and lid to a temperature and hold); with steps
    it is a ``Method`` (a cycling program). The unit only starts a ``Method`` after
    a ``PreMethod`` has finished (see *post_heating*), so run one first.

    Parameters
    ----------
    method_name:
        Name the method is stored under on the unit and run by. Uploading a
        method whose name already exists replaces it. Use letters, digits, ``_``
        and ``-``; no spaces or XML characters.
    creator:
        Free-text author, shown next to the method in
        :meth:`~hamilton_venus.devices.odtc_commands.ODTCDeviceCommands.odtc_list_methods`
        (Inheco's own are ``HAN``/``MST``; this driver defaults to ``hamilton_venus``).
    description:
        Free-text note stored with the method; ``None`` for none.
    variant:
        Instrument model the method is written for (wire ``Variant``): ``960000``
        = 96-well ODTC (the default), ``3840000`` = 384-well ODTC (Inheco's 384-well
        methods are named ``..._384``). Set it to your unit's model; a mismatch has
        not been tried on hardware.
    plate_type:
        Plate-type code (wire ``PlateType``). Always ``0`` in Inheco's methods
        and files, and no other value is known -- leave it at ``0``.
    fluid_quantity:
        Liquid volume per well, as the Script Editor's "Fluid" drop-down (wire
        ``FluidQuantity``): ``0`` = 10-29 ul (the default), ``1`` = 30-74 ul,
        ``2`` = 75-100 ul (see :data:`FLUID_QUANTITY_RANGES_UL`). ``-1`` appears in
        Inheco's 384-well verification methods and means "not specified". It is
        stored with the method, and :meth:`add_pcr` uses it to choose the
        editor's ramp slopes and overshoot for that volume; :meth:`add_step` and
        :meth:`add_hold` do not, they use the slopes you give.
    post_heating:
        Whether the unit keeps the block and lid heated when the method ends
        (wire ``PostHeating``). The unit refuses to start a stepped ``Method``
        with "PreMethod or enabled PostHeating is required" unless a ``PreMethod``
        has been run first or this is on, so leave it ``True`` (the default;
        Inheco's methods use both).
    start_block_temperature:
        Block temperature in degrees C the method starts from. For a ``PreMethod``
        (no steps) this is the block target it holds. For a ``Method`` it is the
        temperature the preceding ``PreMethod`` left the block at; :meth:`add_pcr`
        uses it to decide whether the first step heats or cools. Typically 4-99; 25 is
        the default.
    start_lid_temperature:
        Lid temperature in degrees C for the ``PreMethod`` to hold, and the value
        the method starts with. Typically 30-115; 110 is the default.
    """

    def __init__(
        self,
        method_name: str,
        *,
        creator: str = "hamilton_venus",
        description: str | None = None,
        variant: int = _DEFAULT_VARIANT,
        plate_type: int = 0,
        fluid_quantity: int = 0,
        post_heating: bool = True,
        start_block_temperature: float = 25.0,
        start_lid_temperature: float = 110.0,
    ) -> None:
        self._method_name = method_name
        self._creator = creator
        self._description = description
        self._variant = variant
        self._plate_type = plate_type
        self._fluid_quantity = fluid_quantity
        self._post_heating = post_heating
        self._start_block_temperature = start_block_temperature
        self._start_lid_temperature = start_lid_temperature
        self._steps: list[ODTCStep] = []
        self._pids: list[ODTCPid] = [ODTCPid()]

    def add_step(self, step: ODTCStep) -> ODTCProtocolBuilder:
        """Append *step* (an :class:`ODTCStep`, see there for its fields) and number it."""
        step.number = len(self._steps) + 1
        self._steps.append(step)
        return self

    def add_hold(
        self,
        temperature: float,
        hold_seconds: float,
        *,
        slope: float = 2.0,
        lid_temperature: float = 110.0,
        pid_number: int = 1,
    ) -> ODTCProtocolBuilder:
        """Append a single non-cycling step held at *temperature* for *hold_seconds*.

        Parameters
        ----------
        temperature:
            Block target in degrees C (typically 4-99).
        hold_seconds:
            Hold time in seconds; ``0`` to pass straight through.
        slope:
            Ramp rate to reach it in degrees C per second, above 0 (default 2.0;
            the block heats at up to 4.4 and cools slower -- see :class:`ODTCStep`).
        lid_temperature:
            Lid target in degrees C during the step (typically 30-115; default 110).
        pid_number:
            Which PID set regulates the step; leave at ``1``.
        """
        return self.add_step(
            ODTCStep(
                temperature=temperature,
                hold_seconds=hold_seconds,
                slope=slope,
                lid_temperature=lid_temperature,
                pid_number=pid_number,
            )
        )

    def add_cycle(self, steps: list[ODTCStep], repeats: int) -> ODTCProtocolBuilder:
        """Append *steps* once, then repeat them *repeats* more times.

        Parameters
        ----------
        steps:
            The :class:`ODTCStep` objects that make up one pass, in order (at least
            one); they are appended and numbered like :meth:`add_step`.
        repeats:
            Extra passes after the first, ``>= 1`` (Inheco's "Cycles"; up to 58 in Inheco's methods).

        *repeats* is Inheco's "Cycles" field (the ``LoopNumber`` on the wire): the
        steps run once and then *repeats* more times, so ``repeats=3`` runs them
        four times in all. Inheco's own Script Editor does the same -- the same
        steps with ``Cycles = 3`` plot four denature/anneal/extend passes, and a
        real unit's temperature trace shows four anneal plateaus for it. (When the
        first step is at the same temperature as the step before the block, the
        first pass merges with it into one wider plateau, so count the anneals.)

        On the wire this sets ``GotoNumber``/``LoopNumber`` on the *last*
        appended step, pointing back at the first appended step's number. Matches
        the pattern in both real programs in the sample protocol file.
        """
        if not steps:
            raise ValueError("add_cycle needs at least one step")
        if repeats < 1:
            raise ValueError(f"repeats must be >= 1, got {repeats}")
        first_number = len(self._steps) + 1
        for step in steps:
            self.add_step(step)
        last = self._steps[-1]
        last.goto_number = first_number
        last.loop_number = repeats
        return self

    def add_pcr(
        self,
        *,
        initial_denaturation: tuple[float, float] | None = (95.0, 15.0),
        denaturation: tuple[float, float] = (95.0, 10.0),
        annealing: tuple[float, float] = (60.0, 10.0),
        extension: tuple[float, float] = (72.0, 15.0),
        cycles: int = 3,
        final_extension: tuple[float, float] | None = (72.0, 15.0),
        cooling: tuple[float, float] | None = (25.0, 10.0),
        lid_temperature: float = 110.0,
    ) -> ODTCProtocolBuilder:
        """Append a 3-step PCR laid out and tuned the way Inheco's Script Editor does.

        Each ``(temperature C, seconds)`` pair is one editor field (the defaults are
        the editor's), and *cycles* is its "Cycles" field -- the block runs the
        denature/anneal/extend pass once and then *cycles* more times (see
        :meth:`add_cycle`), so ``cycles=3`` is four passes. ``None`` switches an
        optional part off, like unticking its box in the editor.

        Parameters
        ----------
        initial_denaturation:
            ``(temperature C, seconds)`` of the one-off first heat-up, typically
            95 C for 15-180 s, or ``None`` to leave it out (the first denaturation
            then acts as the start).
        denaturation:
            ``(temperature C, seconds)`` of the melt step in every pass (95 C, 10 s).
        annealing:
            ``(temperature C, seconds)`` of the primer-binding step (60 C, 10 s).
        extension:
            ``(temperature C, seconds)`` of the polymerase step (72 C, 15 s).
        cycles:
            Inheco's "Cycles", ``>= 1``: extra passes after the first, so ``3``
            gives four anneal/extend passes (see :meth:`add_cycle`).
        final_extension:
            ``(temperature C, seconds)`` of a last hold after the cycles (72 C,
            15 s), or ``None`` for none.
        cooling:
            ``(temperature C, seconds)`` of the final hold the block is cooled to
            (25 C, 10 s), or ``None`` to stop after the last step. Cooling passes
            through 60, 40 and 20 C breakpoints with progressively slower slopes.
        lid_temperature:
            Lid target in degrees C for every step (typically 30-115; default 110).

        Raises
        ------
        ValueError
            If this builder's ``fluid_quantity`` is not 0, 1 or 2, or *cycles* < 1.

        Slopes and overshoot come from :data:`EDITOR_TUNING` for this builder's
        ``fluid_quantity`` (0 = 10-29 ul, the default; 1 = 30-74 ul; 2 = 75-100 ul)
        instead of one fixed ramp rate: heating at the maximum slope with the
        editor's overshoot, cooling in slower and slower segments (60, 40 and 20 C
        breakpoints) down to *cooling*. The step layout is the editor's too -- the
        loop covers anneal/extend/denature and a last anneal/extend follows it.
        Verified field-for-field against the editor's output for the default
        temperatures at all three volumes. Other temperatures reuse the same
        per-step values with the overshoot peak capped at 102 C -- the editor
        recomputes them, so treat those as approximate.
        """
        if self._fluid_quantity not in EDITOR_TUNING:
            raise ValueError(
                f"add_pcr needs fluid_quantity in {sorted(EDITOR_TUNING)} "
                f"({FLUID_QUANTITY_RANGES_UL}), got {self._fluid_quantity}"
            )
        if cycles < 1:
            raise ValueError(f"cycles must be >= 1, got {cycles}")
        tune = EDITOR_TUNING[self._fluid_quantity]
        previous = self._start_block_temperature
        no_overshoot = (0.1, 0.0, 0.0, 0.1)

        def add(
            temperature: float,
            seconds: float,
            slope: float,
            overshoot: tuple[float, float, float, float],
            goto: int = 0,
            loop: int = 0,
        ) -> int:
            nonlocal previous
            slope1, peak, hold, slope2 = overshoot
            self.add_step(
                ODTCStep(
                    temperature=temperature,
                    hold_seconds=seconds,
                    slope=slope,
                    lid_temperature=lid_temperature,
                    goto_number=goto,
                    loop_number=loop,
                    overshoot_slope1=slope1,
                    overshoot_temperature=peak,
                    overshoot_time=hold,
                    overshoot_slope2=slope2,
                )
            )
            previous = temperature
            return len(self._steps)

        def heat_overshoot(target: float, peak: float, hold: float) -> tuple[float, float, float, float]:
            return (tune.heating_slope, min(peak, _MAX_OVERSHOOT_PEAK_C - target), hold, 2.2)

        def go(target: float, seconds: float, kind: str, goto: int = 0, loop: int = 0) -> int:
            """One step to *target*; *kind* names which editor transition it is."""
            if target == previous:
                return add(target, seconds, tune.heating_slope, no_overshoot, goto, loop)
            if target > previous:
                peak, hold = {
                    "initial": tune.initial_denaturation,
                    "denaturation": tune.denaturation,
                }.get(kind, (tune.extension_overshoot, 0.0))
                return add(target, seconds, tune.heating_slope, heat_overshoot(target, peak, hold), goto, loop)
            slope = tune.cooling_slope(previous)
            undershoot = (slope, tune.annealing_undershoot, 0.0, 2.2) if kind == "annealing" else no_overshoot
            return add(target, seconds, slope, undershoot, goto, loop)

        if initial_denaturation is not None:
            go(initial_denaturation[0], initial_denaturation[1], "initial")
        go(denaturation[0], denaturation[1], "initial" if initial_denaturation is None else "denaturation")
        anneal_step = go(annealing[0], annealing[1], "annealing")
        go(extension[0], extension[1], "extension")
        go(
            denaturation[0],
            denaturation[1],
            "denaturation",
            goto=anneal_step if cycles > 1 else 0,
            loop=cycles - 1 if cycles > 1 else 0,
        )
        go(annealing[0], annealing[1], "annealing")
        go(extension[0], extension[1], "extension")
        if final_extension is not None:
            go(final_extension[0], final_extension[1], "extension")
        if cooling is not None:
            target, seconds = cooling
            for breakpoint_c in _COOLING_BREAKPOINTS_C:
                if target < breakpoint_c < previous:
                    go(breakpoint_c, 0.0, "cooling")
            slope = tune.cooling_slope(previous)
            add(target, seconds, slope, (slope, 0.0, 0.0, 0.1))
        return self

    def set_pids(self, pids: list[ODTCPid]) -> ODTCProtocolBuilder:
        """Replace the controller-gain sets (default: one :class:`ODTCPid` numbered 1).

        Each :class:`ODTCPid` is referenced by the ``pid_number`` of the steps that
        should use it. Only needed for gains supplied by Inheco.
        """
        self._pids = list(pids)
        return self

    def build(self) -> ODTCProtocol:
        """Return the finished :class:`ODTCProtocol` (a ``PreMethod`` if no steps were added)."""
        return ODTCProtocol(
            method_name=self._method_name,
            creator=self._creator,
            description=self._description,
            target_block_temperature=self._start_block_temperature,
            target_lid_temperature=self._start_lid_temperature,
            variant=self._variant,
            plate_type=self._plate_type,
            fluid_quantity=self._fluid_quantity,
            post_heating=self._post_heating,
            start_block_temperature=self._start_block_temperature,
            start_lid_temperature=self._start_lid_temperature,
            steps=list(self._steps),
            pids=list(self._pids),
        )


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().astimezone().isoformat()


def _num(value: float) -> str:
    """Render a number the way the sample file does: integers without a
    trailing ``.0`` (``<PlateauTemperature>95</PlateauTemperature>``, not
    ``95.0``), fractional values as-is."""
    if isinstance(value, bool):
        return str(int(value))
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _render_step_xml(step: ODTCStep) -> str:
    return (
        "    <Step>\n"
        f"      <Number>{step.number}</Number>\n"
        f"      <Slope>{_num(step.slope)}</Slope>\n"
        f"      <PlateauTemperature>{_num(step.temperature)}</PlateauTemperature>\n"
        f"      <PlateauTime>{_num(step.hold_seconds)}</PlateauTime>\n"
        f"      <OverShootSlope1>{_num(step.overshoot_slope1)}</OverShootSlope1>\n"
        f"      <OverShootTemperature>{_num(step.overshoot_temperature)}</OverShootTemperature>\n"
        f"      <OverShootTime>{_num(step.overshoot_time)}</OverShootTime>\n"
        f"      <OverShootSlope2>{_num(step.overshoot_slope2)}</OverShootSlope2>\n"
        f"      <GotoNumber>{step.goto_number}</GotoNumber>\n"
        f"      <LoopNumber>{step.loop_number}</LoopNumber>\n"
        f"      <PIDNumber>{step.pid_number}</PIDNumber>\n"
        f"      <LidTemp>{_num(step.lid_temperature)}</LidTemp>\n"
        "    </Step>"
    )


def _render_pid_xml(pid: ODTCPid) -> str:
    return (
        f'    <PID number="{pid.number}">\n'
        f"      <PHeating>{_num(pid.p_heating)}</PHeating>\n"
        f"      <PCooling>{_num(pid.p_cooling)}</PCooling>\n"
        f"      <IHeating>{_num(pid.i_heating)}</IHeating>\n"
        f"      <ICooling>{_num(pid.i_cooling)}</ICooling>\n"
        f"      <DHeating>{_num(pid.d_heating)}</DHeating>\n"
        f"      <DCooling>{_num(pid.d_cooling)}</DCooling>\n"
        f"      <PLid>{_num(pid.p_lid)}</PLid>\n"
        f"      <ILid>{_num(pid.i_lid)}</ILid>\n"
        "    </PID>"
    )


def _method_attrs(protocol: ODTCProtocol) -> str:
    attrs = f'methodName="{escape(protocol.method_name)}" creator="{escape(protocol.creator)}"'
    if protocol.description:
        attrs += f' description="{escape(protocol.description)}"'
    attrs += f' dateTime="{_now_iso()}"'
    return attrs


def render_protocol_xml(protocol: ODTCProtocol) -> str:
    """Render *protocol* as a standalone ``<MethodSet>`` document -- the wire
    format ``SetMethod`` expects (the HSL just forwards the file's bytes)."""
    attrs = _method_attrs(protocol)
    if not protocol.steps:
        body = (
            f"  <PreMethod {attrs}>\n"
            f"    <TargetBlockTemperature>{_num(protocol.target_block_temperature)}</TargetBlockTemperature>\n"
            f"    <TargetLidTemp>{_num(protocol.target_lid_temperature)}</TargetLidTemp>\n"
            "  </PreMethod>"
        )
    else:
        steps_xml = "\n".join(_render_step_xml(s) for s in protocol.steps)
        pids_xml = "\n".join(_render_pid_xml(p) for p in protocol.pids)
        body = (
            f"  <Method {attrs}>\n"
            f"    <Variant>{protocol.variant}</Variant>\n"
            f"    <PlateType>{protocol.plate_type}</PlateType>\n"
            f"    <FluidQuantity>{protocol.fluid_quantity}</FluidQuantity>\n"
            f"    <PostHeating>{'true' if protocol.post_heating else 'false'}</PostHeating>\n"
            f"    <StartBlockTemperature>{_num(protocol.start_block_temperature)}</StartBlockTemperature>\n"
            f"    <StartLidTemperature>{_num(protocol.start_lid_temperature)}</StartLidTemperature>\n"
            f"{steps_xml}\n"
            "    <PIDSet>\n"
            f"{pids_xml}\n"
            "    </PIDSet>\n"
            "  </Method>"
        )
    return f'<?xml version="1.0" encoding="utf-8"?>\n<MethodSet>\n{body}\n</MethodSet>\n'


class protocol_tempfile:  # noqa: N801
    """Context manager: write *protocol*'s rendered XML to a temp file, yield
    its path, delete it on exit unless *keep* is True."""

    def __init__(self, protocol: ODTCProtocol, *, keep: bool = False) -> None:
        self._protocol = protocol
        self._keep = keep
        self._path: str | None = None

    def __enter__(self) -> str:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="odtc_protocol_", suffix=".xml")
        try:
            import os

            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(render_protocol_xml(self._protocol))
        except BaseException:
            import os

            os.close(fd)
            raise
        self._path = path
        return path

    def __exit__(self, *exc_info: object) -> None:
        if self._keep or self._path is None:
            return
        import contextlib
        import os

        with contextlib.suppress(OSError):
            os.remove(self._path)


__all__ = [
    "ODTCPid",
    "ODTCProtocol",
    "ODTCProtocolBuilder",
    "ODTCStep",
    "protocol_tempfile",
    "render_protocol_xml",
]
