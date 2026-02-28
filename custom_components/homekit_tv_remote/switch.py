"""Switch entities for debug options and input configuration."""
# Version: 1.1.0
#
# CHANGES FROM 1.0.0:
# - Added AppleTVSwitch: when ON, the Save Input button uses
#   media_player.select_source instead of media_player.play_media
#   when saving a media_player type input. Required for Apple TV
#   integration which does not support play_media for app launching.
#   State is stored in hass.data (in-memory only) — resets to OFF on reload
#   since it is a per-input configuration toggle, not a persistent setting.

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
    """Create debug switches and the Apple TV switch."""
    apple_tv_switch = AppleTVSwitch(hass, entry)

    # Store reference in hass.data so button.py can read its state
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["apple_tv_switch"] = apple_tv_switch

    switches = [
        DebugListenSwitch(hass, entry),
        DebugSendSwitch(hass, entry),
        apple_tv_switch,
    ]
    async_add_entities(switches)


# ─── Apple TV Switch ───────────────────────────────────────────────────────────

class AppleTVSwitch(SwitchEntity):
    """
    Toggle Apple TV app launching mode.

    OFF (default): media_player type inputs use media_player.play_media
    ON:            media_player type inputs use media_player.select_source

    Use ON when the selected media_player entity is an Apple TV.
    select_source is the only working method for launching apps on Apple TV.

    State is in-memory only — resets to OFF on every integration reload.
    Read by AddCustomInputButton in button.py when saving an input.
    Category: CONFIG (shown in the Configuration section of the device page)
    """

    _attr_should_poll = False

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_apple_tv_mode"
        self._attr_name = "1. Apple TV"
        self._attr_icon = "mdi:apple"
        self._attr_is_on = False
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        """Enable Apple TV mode — select_source will be used for media_player inputs."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Disable Apple TV mode — play_media will be used for media_player inputs."""
        self._attr_is_on = False
        self.async_write_ha_state()


# ─── Debug Listen Switch ───────────────────────────────────────────────────────

class DebugListenSwitch(SwitchEntity):
    """
    Toggle [HOMEKIT_TV_LISTEN] debug logging in remote.py.
    Initial state is read from config_entry.options["debug_listen"].
    Category: DIAGNOSTIC
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_debug_listen"
        self._attr_name = "Debug Listen"
        self._attr_icon = "mdi:bug"
        self._attr_is_on = config_entry.options.get("debug_listen", False)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "debug_listen": True}
        )
        self._attr_is_on = True
        self.async_write_ha_state()
        remote_ref = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity_ref")
        )
        if remote_ref:
            remote_ref._debug_listen = True

    async def async_turn_off(self, **kwargs):
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
    Initial state is read from config_entry.options["debug_send"].
    Category: DIAGNOSTIC
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_debug_send"
        self._attr_name = "Debug Send"
        self._attr_icon = "mdi:bug"
        self._attr_is_on = config_entry.options.get("debug_send", False)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
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
