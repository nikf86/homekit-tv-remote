"""Switch entities for debug options."""
# Version: 1.0.0
#
# ROLE IN INTEGRATION:
# Provides two toggle switches that enable/disable debug logging in remote.py
# WITHOUT triggering an integration reload.
#
# The debug flags (_debug_listen, _debug_send) live on the TVRemote instance
# in remote.py. When toggled, these switches:
#   1. Persist the new value to config_entry.options (so it survives reloads)
#   2. Directly flip the flag on the live TVRemote instance via remote_entity_ref
#      stored in hass.data by remote.py — no reload required
#
# DebugListenSwitch: enables [HOMEKIT_TV_LISTEN] log lines in remote.py
#   (subscription events, poll updates, ActiveIdentifier changes)
# DebugSendSwitch:   enables [HOMEKIT_TV_SEND] log lines in remote.py
#   (RemoteKey, Volume, Mute, Input switch commands sent to TV)
#
# NOTE: async_update_entry IS called here (unlike select.py) because toggling
# debug should persist across reloads. However, this also triggers the
# update_listener in __init__.py → async_reload_entry. This is acceptable
# because debug toggles are rarely changed.

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

DOMAIN = "homekit_tv_remote"


# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create both debug switch entities."""
    switches = [
        DebugListenSwitch(hass, entry),
        DebugSendSwitch(hass, entry),
    ]
    async_add_entities(switches)


# ─── Debug Listen Switch ───────────────────────────────────────────────────────

class DebugListenSwitch(SwitchEntity):
    """
    Toggle [HOMEKIT_TV_LISTEN] debug logging in remote.py.
    
    When ON: remote.py logs every ActiveIdentifier poll update,
    push subscription event, and source change at WARNING level
    (so they appear without enabling debug mode globally).
    
    Initial state is read from config_entry.options["debug_listen"].
    Category: DIAGNOSTIC (shown in the Diagnostic section of the device page)
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_debug_listen"
        self._attr_name = "Debug Listen"
        self._attr_icon = "mdi:bug"
        # Read persisted state from options (False if never set)
        self._attr_is_on = config_entry.options.get("debug_listen", False)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        """
        Enable listen debug logging:
        1. Persist True to config_entry.options (survives reloads)
        2. Update local state and write to HA
        3. Flip _debug_listen on the live TVRemote instance directly
           (avoids needing a reload to take effect immediately)
        """
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "debug_listen": True}
        )
        self._attr_is_on = True
        self.async_write_ha_state()

        # Update the live remote entity flag without waiting for reload
        remote_ref = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity_ref")
        )
        if remote_ref:
            remote_ref._debug_listen = True

    async def async_turn_off(self, **kwargs):
        """
        Disable listen debug logging:
        1. Persist False to config_entry.options
        2. Update local state and write to HA
        3. Flip _debug_listen on the live TVRemote instance directly
        """
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "debug_listen": False}
        )
        self._attr_is_on = False
        self.async_write_ha_state()

        remote_ref = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity_ref")
        )
        if remote_ref:
            remote_ref._debug_listen = False


# ─── Debug Send Switch ─────────────────────────────────────────────────────────

class DebugSendSwitch(SwitchEntity):
    """
    Toggle [HOMEKIT_TV_SEND] debug logging in remote.py.
    
    When ON: remote.py logs every command sent to the TV at WARNING level:
    RemoteKey values, Volume directions, Mute toggles, Input switches.
    
    Initial state is read from config_entry.options["debug_send"].
    Category: DIAGNOSTIC (shown in the Diagnostic section of the device page)
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_debug_send"
        self._attr_name = "Debug Send"
        self._attr_icon = "mdi:bug"
        # Read persisted state from options (False if never set)
        self._attr_is_on = config_entry.options.get("debug_send", False)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        """
        Enable send debug logging:
        1. Persist True to config_entry.options
        2. Update local state and write to HA
        3. Flip _debug_send on the live TVRemote instance directly
        """
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "debug_send": True}
        )
        self._attr_is_on = True
        self.async_write_ha_state()

        remote_ref = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity_ref")
        )
        if remote_ref:
            remote_ref._debug_send = True

    async def async_turn_off(self, **kwargs):
        """
        Disable send debug logging:
        1. Persist False to config_entry.options
        2. Update local state and write to HA
        3. Flip _debug_send on the live TVRemote instance directly
        """
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "debug_send": False}
        )
        self._attr_is_on = False
        self.async_write_ha_state()

        remote_ref = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity_ref")
        )
        if remote_ref:
            remote_ref._debug_send = False
