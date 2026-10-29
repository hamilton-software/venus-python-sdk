"""Deck persistence commands mixin for StarClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hamilton_venus.mixins.split_well_commands import clear_split_wells
from hamilton_venus.models import (
    CommandResponse,
    DeckAvailableResponse,
    DeckGetRackIdsFromDeckParameters,
    DeckGetRackIdsFromDeckResponse,
    DeckImportParameters,
    DeckImportRackAsSiteParameters,
    DeckImportRackAsSiteResponse,
    DeckImportResponse,
    DeckLoadParameters,
    DeckNameParameters,
    DeckSaveParameters,
    SavedDecksResponse,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from hamilton_venus._internal._async_instrument_client import _AsyncInstrumentClient

class DeckCommandsMixin:
    """Mixin class providing deck persistence commands for StarClient."""

    if TYPE_CHECKING:

        @property
        def _connected_instrument(self) -> _AsyncInstrumentClient: ...

        def _run(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

    def deck_get_previous(self) -> DeckAvailableResponse:
        """Check whether a previous deck layout is available to restore."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.getPreviousDeck",
            )
        )
        return DeckAvailableResponse.model_validate(response.model_dump(by_alias=True))

    def deck_get_saved(self) -> SavedDecksResponse:
        """Return the list of saved deck layout names."""
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.getSavedDecks",
            )
        )
        return SavedDecksResponse.model_validate(response.model_dump(by_alias=True))

    def deck_load(self, deck_name: str | None = None, *, previous: bool = False) -> CommandResponse:
        """Load a previously saved deck layout by name, or reload the last-used deck.

        Pass ``deck_name`` to load by name, or set ``previous=True`` to reload
        the last deck (omitting ``deck_name``).
        """
        parameters = DeckLoadParameters(deck=deck_name, previous=previous)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.loadDeck",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        # The loaded layout replaces the deck, split racks included.
        clear_split_wells(self)
        return response

    def deck_save(self, deck_name: str, *, overwrite: bool = False) -> CommandResponse:
        """Save the current deck layout with the specified name."""
        parameters = DeckSaveParameters(name=deck_name, overwrite=overwrite)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.saveDeck",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def deck_delete_saved(self, deck_name: str) -> CommandResponse:
        """Delete a previously saved deck layout by name."""
        parameters = DeckNameParameters(name=deck_name)
        return self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.deleteSavedDeck",
                parameters=parameters.model_dump(by_alias=True),
            )
        )

    def deck_import(self, path: str) -> DeckImportResponse:
        """Import a deck layout from a ``.lay`` file path.

        Every carrier defined in the file is placed on the current deck and
        registered in the SDK's built-in carrier tracking (so it shows up in
        :meth:`get_added_carriers` afterwards). This modifies the live deck,
        so the instrument must already be connected -- it is a lifecycle
        step 4 operation, unlike :meth:`deck_load` (step 2), which loads a
        saved-by-name layout and can run before connecting.

        Returns the list of added carriers in ``return_parameters.carriers_added``.
        """
        parameters = DeckImportParameters(path=path)
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.importDeck",
                parameters=parameters.model_dump(by_alias=True),
            )
        )
        return DeckImportResponse.model_validate(response.model_dump(by_alias=True))

    def deck_get_rack_ids_from_deck(
        self,
        path: str,
        carrier_filter: list[str] | None = None,
        only_floating_racks: bool | None = None,
    ) -> DeckGetRackIdsFromDeckResponse:
        """Get rack IDs from a deck layout file."""
        parameters = DeckGetRackIdsFromDeckParameters(
            path=path,
            carrier_filter=carrier_filter,
            only_floating_racks=only_floating_racks,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.GetRackIdsFromDeck",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return DeckGetRackIdsFromDeckResponse.model_validate(response.model_dump(by_alias=True))

    def deck_import_rack_as_site(
        self,
        path: str,
        target_labware_name: str,
        carrier_filter: list[str] | None = None,
        only_floating_racks: bool | None = None,
        site_name: str | None = None,
    ) -> DeckImportRackAsSiteResponse:
        """Import a rack from a deck layout file as a site on the specified labware."""
        parameters = DeckImportRackAsSiteParameters(
            path=path,
            target_labware_name=target_labware_name,
            carrier_filter=carrier_filter,
            only_floating_racks=only_floating_racks,
            site_name=site_name,
        )
        response = self._run(
            self._connected_instrument.venus.send_command(
                category="Deck Layout",
                action_name="deck.importRackAsSite",
                parameters=parameters.model_dump(by_alias=True, exclude_none=True),
            )
        )
        return DeckImportRackAsSiteResponse.model_validate(response.model_dump(by_alias=True))

