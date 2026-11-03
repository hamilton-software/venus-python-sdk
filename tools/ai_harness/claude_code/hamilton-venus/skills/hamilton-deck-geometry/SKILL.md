---
name: hamilton-deck-geometry
description: 'Converting between deck tracks and X coordinates on a Hamilton STAR or Vantage, and estimating whether the MPH96 can reach a carrier. Use when a carrier X origin or track number has to be calculated, when the STAR and Vantage track origins differ, when working out the X range a carrier or labware occupies, or when checking MPH96 reach across the deck.'
---

# Deck conversion

- A track is **22.5 mm** wide.
- **STAR**: track 1 starts at X = 100.0 mm. **Vantage**: track 1 starts at X = 32.5 mm.
- A carrier on track 1 of a STAR has X origin 100.0. The right side of track 1 (left side of track 2) is 122.5.
- A carrier N tracks wide occupies X origin to `X origin + 22.5 * N`.

| Convert | STAR | Vantage |
|---|---|---|
| X origin to track | `(X - 77.5) / 22.5` | `(X - 10.0) / 22.5` |

Carrier widths come from `search_labware` (`width_tracks`); never assume them.

## MPH96 reach

Take the **centre of the carrier's X range** and compare it with the MPH96's X range (measured at A1 of the 96 head). If the centre is outside, the head cannot reach it. The reach itself is reported by `instrument_get_configuration`; see `hamilton-channel-random-access`.
