"""Button entities — the two presses worth keeping on the device page."""
# Version: 2.0.0
#
# WHAT CHANGED FROM 1.7.0
#   1.x had five buttons: Test Command, Save Input, Delete Last Input, Next
#   Saved Input and Reload HomeKit YAML. The first three existed only because
#   configuration lived in entities; they are now steps in the Configure dialog.
#
#   Reload HomeKit no longer reloads the integration first. It does not need to:
#   the options flow reloads the entry itself when it saves. This button is now
#   exactly one thing — re-register the accessory with Apple Home so a changed
#   input list shows up there.
#
#   Next Input keeps its 1.x unique_id, so the entity, its entity_id and its
#   history survive the upgrade even though its name changed.

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeKitTVConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitTVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NextInputButton(entry), ReloadHomeKitButton(entry)])


class _BaseButton(ButtonEntity):
    """Shared device wiring."""

    _attr_has_entity_name = True

    def __init__(self, entry: HomeKitTVConfigEntry) -> None:
        self._entry = entry
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})


class NextInputButton(_BaseButton):
    """Advance one step through the configured inputs.

    Does exactly what the ⓘ Info button on the iOS remote widget does, and
    shares its position in the cycle — press either and the next press from
    either continues from there.
    """

    _attr_name = "Next input"
    _attr_icon = "mdi:skip-next"

    def __init__(self, entry: HomeKitTVConfigEntry) -> None:
        super().__init__(entry)
        # Unique ID deliberately unchanged from 1.x to preserve the entity.
        self._attr_unique_id = f"{entry.entry_id}_next_saved_input"

    async def async_press(self) -> None:
        media = self._entry.runtime_data.media_ref
        if media is None:
            _LOGGER.warning("Media player entity is not ready yet")
            return
        await media.async_cycle_input()


class ReloadHomeKitButton(_BaseButton):
    """Reload HomeKit Bridge so Apple Home picks up a changed input list.

    Apple Home caches the accessory's input list. After adding or removing
    inputs, press this once, then force-close and reopen the Home app on your
    iPhone or iPad.
    """

    _attr_name = "Reload HomeKit Bridge"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: HomeKitTVConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_reload_homekit"

    async def async_press(self) -> None:
        if not self.hass.services.has_service("homekit", "reload"):
            _LOGGER.error(
                "HomeKit Bridge is not set up, so there is nothing to reload. "
                "Add the homekit: block to configuration.yaml first"
            )
            return
        try:
            await self.hass.services.async_call("homekit", "reload", blocking=True)
            _LOGGER.info("HomeKit Bridge reloaded")
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to reload HomeKit Bridge: %s", err)
