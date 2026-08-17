"""Switch entities — the two debug toggles."""
# Version: 2.0.0
#
# WHAT CHANGED FROM 1.3.5
#   The Apple TV App and Apple TV Input switches are gone: what they selected is
#   now detected automatically when an input runs (see media_player.py).
#   The per-input "Include:" switches are gone too — options["inputs"] is the
#   list of included inputs, so there is nothing separate to toggle. Between
#   them that removes one switch per saved input plus two fixed ones.
#
#   What remains is the two debug toggles, and they keep their 1.x unique_ids
#   and behaviour: flip the flag on the live remote entity so logging starts
#   immediately, and persist it so it survives a restart.
#
# WHY THESE WRITES DO NOT RELOAD
#   The integration has no config entry update listener. Writing options here is
#   therefore silent, which is what makes a mid-session log toggle possible. The
#   options flow owns reloading (OptionsFlowWithReload) and is the only thing
#   that reloads.

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeKitTVConfigEntry
from .const import DOMAIN, OPT_DEBUG_LISTEN, OPT_DEBUG_SEND


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitTVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            DebugSwitch(
                entry,
                option=OPT_DEBUG_LISTEN,
                attribute="_debug_listen",
                name="Debug listen",
            ),
            DebugSwitch(
                entry,
                option=OPT_DEBUG_SEND,
                attribute="_debug_send",
                name="Debug send",
            ),
        ]
    )


class DebugSwitch(SwitchEntity):
    """Turn one debug log stream on or off without restarting.

    Debug listen  → [HOMEKIT_TV_LISTEN] lines: what we read from the HomeKit
                    Device entity (power changes, input changes).
    Debug send    → [HOMEKIT_TV_SEND] lines: every characteristic write we make.

    Both log at warning level on purpose, so they show up without changing the
    logger configuration. Turn them off again when you are done.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:bug"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: HomeKitTVConfigEntry,
        *,
        option: str,
        attribute: str,
        name: str,
    ) -> None:
        self._entry = entry
        self._option = option
        self._attribute = attribute
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{option}"   # unchanged from 1.x
        self._attr_is_on = entry.options.get(option, False)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        # Read the entry back from hass rather than trusting the reference this
        # entity was built with — options may have been rewritten since.
        entry = self.hass.config_entries.async_get_entry(self._entry.entry_id)
        if entry is not None:
            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, self._option: value}
            )
        self._attr_is_on = value
        self.async_write_ha_state()

        # Flip the flag on the live entity so it takes effect straight away.
        remote = self._entry.runtime_data.remote_ref
        if remote is not None:
            setattr(remote, self._attribute, value)
