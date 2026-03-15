"""Select entities for HomeKit TV Remote configuration."""
# Version: 1.0.0
#
# ROLE IN INTEGRATION:
# Provides a single dropdown (SelectEntity) that lets the user choose the
# command TYPE for a new input before pressing Save Input (button.py).
#
# Options are populated dynamically on setup from all remote.* and
# media_player.* entities currently in HA (excluding the integration's own
# entities to avoid circular references).
#
# The selected value is stored in-memory only (_attr_current_option).
# It resets to "hap" on every integration reload because async_select_option
# does NOT call async_update_entry — this was an explicit design decision to
# avoid triggering a reload every time the user touches the dropdown.
#
# The entity reference is stored in hass.data so button.py can read
# current_option when the user presses Save Input.

from homeassistant.components.select import SelectEntity
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
    """
    Create the InputTypeSelectEntity and store a reference in hass.data
    so button.py (AddCustomInputButton) can read its current_option.
    """
    input_type = InputTypeSelectEntity(hass, entry)

    # Store reference in shared data store for button.py to access
    if "homekit_tv_remote" not in hass.data:
        hass.data["homekit_tv_remote"] = {}
    if entry.entry_id not in hass.data["homekit_tv_remote"]:
        hass.data["homekit_tv_remote"][entry.entry_id] = {}

    hass.data["homekit_tv_remote"][entry.entry_id]["input_type"] = input_type

    async_add_entities([input_type])


# ─── InputTypeSelectEntity ─────────────────────────────────────────────────────

class InputTypeSelectEntity(SelectEntity):
    """
    Dropdown for selecting the command type when adding a new custom input.

    Options:
      "hap"                        → command goes via HAP ActiveIdentifier/RemoteKey
      "remote.entity_id"           → command goes via remote.send_command on that entity
      "media_player.entity_id"     → command goes via media_player.play_media on that entity

    The option list is built once at __init__ time from hass.states.
    It does NOT update if new remote/media_player entities are added later
    without an integration reload.

    Selected value resets to "hap" on every reload (in-memory only, not persisted).
    Category: CONFIG (shown in the Configuration section of the device page)
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_input_type"
        self._attr_name = "1d. Input Type"
        self._attr_icon = None
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }
        # Build options list immediately (hass.states is available in __init__ via self.hass)
        self._update_options()

    def _update_options(self):
        """
        Build the dropdown options list:
          1. Always start with "hap" (direct HAP command via remote.homekit_tv)
          2. Add all remote.* entities except remote.homekit_tv (our own entity)
          3. Add all media_player.* entities except media_player.homekit_tv (our own entity)
        
        Called once during __init__. Not called again unless the integration reloads.
        """
        options = ["hap"]

        # Add external remote entities
        for state in self.hass.states.async_all("remote"):
            entity_id = state.entity_id
            if entity_id != "remote.homekit_tv":
                options.append(entity_id)

        # Add external media_player entities
        for state in self.hass.states.async_all("media_player"):
            entity_id = state.entity_id
            if entity_id != "media_player.homekit_tv":
                options.append(entity_id)

        self._attr_options = options
        self._attr_current_option = "hap"  # Default selection

    async def async_select_option(self, option: str):
        """
        Update the selected option in memory only.
        Does NOT call async_update_entry — deliberately avoids triggering
        an integration reload when the user changes the dropdown.
        Resets to "hap" after each integration reload.
        """
        self._attr_current_option = option
        self.async_write_ha_state()
