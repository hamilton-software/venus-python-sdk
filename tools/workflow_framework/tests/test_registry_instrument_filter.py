"""Regression tests for RegistryEntry.instruments / CommandRegistry.for_instrument()."""

from __future__ import annotations

import unittest

from hamilton_venus.models import InstrumentType

from hamilton_workflow_framework.registry import CommandRegistry, RegistryEntry


class RegistryInstrumentFilterTests(unittest.TestCase):
    def test_entry_defaults_to_both_instruments(self) -> None:
        entry = RegistryEntry(command_id="aspirate", label="Aspirate", category="Liquid", method_name="aspirate")
        self.assertEqual(entry.instruments, frozenset({InstrumentType.STAR, InstrumentType.Vantage}))

    def test_for_instrument_keeps_only_matching_entries(self) -> None:
        star_only = RegistryEntry(
            command_id="aspirate_5ml",
            label="Aspirate (5mL)",
            category="Liquid",
            method_name="aspirate_5ml",
            instruments=frozenset({InstrumentType.STAR}),
        )
        shared = RegistryEntry(command_id="aspirate", label="Aspirate", category="Liquid", method_name="aspirate")
        registry = CommandRegistry([star_only, shared])

        vantage_view = registry.for_instrument(InstrumentType.Vantage)
        star_view = registry.for_instrument(InstrumentType.STAR)

        self.assertEqual({e.command_id for e in vantage_view.entries}, {"aspirate"})
        self.assertEqual({e.command_id for e in star_view.entries}, {"aspirate_5ml", "aspirate"})

    def test_for_instrument_returns_an_independent_registry(self) -> None:
        entry = RegistryEntry(command_id="aspirate", label="Aspirate", category="Liquid", method_name="aspirate")
        registry = CommandRegistry([entry])
        filtered = registry.for_instrument(InstrumentType.STAR)
        self.assertIsNot(filtered, registry)
        self.assertIsInstance(filtered, CommandRegistry)
        filtered.get_entry("aspirate")  # does not raise

    def test_for_instrument_get_entry_raises_for_a_filtered_out_command(self) -> None:
        star_only = RegistryEntry(
            command_id="aspirate_5ml",
            label="Aspirate (5mL)",
            category="Liquid",
            method_name="aspirate_5ml",
            instruments=frozenset({InstrumentType.STAR}),
        )
        registry = CommandRegistry([star_only]).for_instrument(InstrumentType.Vantage)
        with self.assertRaises(KeyError):
            registry.get_entry("aspirate_5ml")


if __name__ == "__main__":
    unittest.main()
