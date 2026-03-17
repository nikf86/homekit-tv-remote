"""Switch entities — debug toggles, Apple TV save-time flags, and per-input Include switches."""
# Version: 1.3.1

import re
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

DOMAIN = "homekit_tv_remote"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """
    Convert an input name to a safe unique_id suffix.
    Matches the same helper used in sensor.py for consistency.
    Example: "Apple TV" → "apple_tv"
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Create all switch entities for this config entry.

    Fixed switches: DebugListenSwitch, DebugSendSwitch, AppleTVAppSwitch,
                    AppleTVInputSwitch — always present regardless of inputs.

    Dynamic switches: one HomeKitInputSwitch per entry in custom_inputs.

    Orphan cleanup removes HomeKitInputSwitch entities from the registry
    whose unique_id no longer matches any saved input — same pattern as
    sensor.py so deleted inputs don't leave ghost switches on the device page.
    """
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # ── Fixed switches ─────────────────────────────────────────────────────────
    apple_tv_app_switch = AppleTVAppSwitch(hass, entry)
    apple_tv_input_switch = AppleTVInputSwitch(hass, entry)

    hass.data[DOMAIN][entry.entry_id]["apple_tv_switch"] = apple_tv_app_switch
    hass.data[DOMAIN][entry.entry_id]["apple_tv_input_switch"] = apple_tv_input_switch

    fixed_switches = [
        DebugListenSwitch(hass, entry),
        DebugSendSwitch(hass, entry),
        apple_tv_app_switch,
        apple_tv_input_switch,
    ]

    # ── Dynamic switches: one per saved input ──────────────────────────────────
    inputs = entry.options.get("custom_inputs", [])

    # Compute valid unique_ids for current inputs
    valid_unique_ids = {
        f"{entry.entry_id}_homekit_input_{_slug(inp.get('name', ''))}"
        for inp in inputs
    }

    # Remove orphaned HomeKitInputSwitch entities from registry
    registry = er.async_get(hass)
    for entity_entry in list(registry.entities.values()):
        if (
            entity_entry.config_entry_id == entry.entry_id
            and entity_entry.domain == "switch"
            and entity_entry.unique_id.startswith(f"{entry.entry_id}_homekit_input_")
            and entity_entry.unique_id not in valid_unique_ids
        ):
            registry.async_remove(entity_entry.entity_id)

    # Create one switch per current input
    dynamic_switches = [
        HomeKitInputSwitch(hass, entry, inp)
        for inp in inputs
    ]

    async_add_entities(fixed_switches + dynamic_switches)


# ─── Apple TV App Switch ───────────────────────────────────────────────────────

class AppleTVAppSwitch(SwitchEntity):
    """
    Toggle Apple TV app launching mode.

    OFF (default): media_player type inputs use media_player.play_media
    ON:            media_player type inputs use media_player.select_source

    Use ON when the selected media_player entity is an Apple TV.
    select_source is the only working method for launching apps on Apple TV.

    State is in-memory only — resets to OFF on every integration reload.
    Read by AddCustomInputButton in button.py when saving an input.
    Category: CONFIG
    """

    _attr_should_poll = False

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_apple_tv_mode"
        self._attr_name = "1. Apple TV App"
        self._attr_icon = "mdi:apple"
        self._attr_is_on = False
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()


# ─── Apple TV Input Switch ─────────────────────────────────────────────────────

class AppleTVInputSwitch(SwitchEntity):
    """
    Mark the input being saved as the Apple TV HDMI source.

    OFF (default): input saved normally, no automatic HDMI switching.
    ON:            button.py embeds the HAP identifier as |input_N in the
                   command string. media_player.py switches the TV HDMI input
                   to the Apple TV port before launching the app.
                   If HAP Identifier field is empty, silently ignored.

    State is in-memory only — resets to OFF on every integration reload.
    Read by AddCustomInputButton in button.py when saving an input.
    Category: CONFIG
    """

    _attr_should_poll = False

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_apple_tv_input"
        self._attr_name = "1. Apple TV Input"
        self._attr_icon = "mdi:hdmi-port"
        self._attr_is_on = False
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()


# ─── HomeKit Input Switch ──────────────────────────────────────────────────────

class HomeKitInputSwitch(SwitchEntity):
    """
    Controls whether a saved input is included in HomeKit / HA source list
    and the input cycle (Info button + Next Saved Input button).

    One instance is created per entry in config_entry.options["custom_inputs"].
    Name: "Include: <input name>"
    Default: OFF — user must explicitly enable each input after saving it.

    State is persisted immediately to config_entry.options["homekit_inputs"]
    (a list of input names that are currently included) on every toggle.
    Does NOT trigger an integration reload — media_player.py reads
    options["homekit_inputs"] live on each source_list access and each
    _cycle_custom_inputs() call.

    Orphan cleanup in async_setup_entry removes this entity if the
    corresponding input is deleted (same pattern as sensor.py).
    Category: CONFIG
    """

    _attr_should_poll = False

    def __init__(self, hass, config_entry, inp: dict):
        self.hass = hass
        self._config_entry = config_entry
        self._input_name = inp.get("name", "")
        self._attr_unique_id = (
            f"{config_entry.entry_id}_homekit_input_{_slug(self._input_name)}"
        )
        self._attr_name = f"Include: {self._input_name}"
        self._attr_icon = "mdi:television-play"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }
        # Initial state: read from persisted options
        included = config_entry.options.get("homekit_inputs", [])
        self._attr_is_on = self._input_name in included

    def _update_options(self, included: bool) -> None:
        """
        Persist the updated homekit_inputs list to config_entry.options.
        Adds or removes self._input_name from the list and writes immediately.
        Does not call async_update_entry with reload=True — no reload triggered.

        Always fetches the live config entry from hass.config_entries to avoid
        using a stale reference — if multiple switches are toggled in sequence,
        each one must read the latest options written by the previous toggle,
        not the snapshot from when this switch instance was created.
        """
        live_entry = self.hass.config_entries.async_get_entry(
            self._config_entry.entry_id
        )
        if not live_entry:
            return
        current = list(live_entry.options.get("homekit_inputs", []))
        if included and self._input_name not in current:
            current.append(self._input_name)
        elif not included and self._input_name in current:
            current.remove(self._input_name)
        self.hass.config_entries.async_update_entry(
            live_entry,
            options={**live_entry.options, "homekit_inputs": current}
        )

    async def async_turn_on(self, **kwargs):
        """Include this input in the HomeKit source list and cycle."""
        self._attr_is_on = True
        self.async_write_ha_state()
        self._update_options(included=True)

    async def async_turn_off(self, **kwargs):
        """Exclude this input from the HomeKit source list and cycle."""
        self._attr_is_on = False
        self.async_write_ha_state()
        self._update_options(included=False)


# ─── Debug Listen Switch ───────────────────────────────────────────────────────

class DebugListenSwitch(SwitchEntity):
    """
    Toggle [HOMEKIT_TV_LISTEN] debug logging in remote.py.
    Initial state read from config_entry.options["debug_listen"].
    State persisted to options on toggle. Category: DIAGNOSTIC
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
    Initial state read from config_entry.options["debug_send"].
    State persisted to options on toggle. Category: DIAGNOSTIC
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
