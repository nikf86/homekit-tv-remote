"""Text entities for HomeKit TV Remote configuration."""
# Version: 1.0.1
#
# CHANGES FROM 1.0.0:
# - CurrentIdentifierTextEntity now reads the remote entity ID from
#   hass.data[DOMAIN][entry_id] (set by __init__.py) instead of hardcoding
#   "remote.homekit_tv". This fixes the current identifier display when
#   tv_name is anything other than "Homekit TV" during setup.

from homeassistant.components.text import TextEntity
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
    Create all text entities and store ConfigTextEntity references in hass.data
    so button.py can read their values when the user presses Save Input.
    """
    texts = [
        ConfigTextEntity(hass, entry, "test_command",
                         "1a. Test Command (try: 4, volume_up, input_9)",
                         EntityCategory.DIAGNOSTIC),
        ConfigTextEntity(hass, entry, "input_name",
                         "1a. Input Name",
                         EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "input_command",
                         "1b. Command (for remote/HAP - OR leave empty for app)",
                         EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "input_app",
                         "1c. App Name (for media_player - OR leave empty for command)",
                         EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "hap_identifier",
                         "1d. HAP Identifier (for remote/media_player only)",
                         EntityCategory.CONFIG),
        # Read-only display of current TV input
        CurrentIdentifierTextEntity(hass, entry),
    ]

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if entry.entry_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.entry_id] = {}

    hass.data[DOMAIN][entry.entry_id]["text_entities"] = {
        text._key: text for text in texts if hasattr(text, '_key')
    }

    async_add_entities(texts)


# ─── ConfigTextEntity ──────────────────────────────────────────────────────────

class ConfigTextEntity(TextEntity):
    """Editable text field for configuration input. Values reset on reload."""

    def __init__(self, hass, config_entry, key, name, entity_category=None):
        self.hass = hass
        self._config_entry = config_entry
        self._key = key
        self._attr_unique_id = f"{config_entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = ""
        self._attr_icon = None
        self._attr_entity_category = entity_category
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }
        self._value = ""

    @property
    def native_value(self):
        return self._value

    async def async_set_value(self, value: str):
        self._value = value
        self.async_write_ha_state()


# ─── CurrentIdentifierTextEntity ───────────────────────────────────────────────

class CurrentIdentifierTextEntity(TextEntity):
    """
    Read-only text entity showing the currently active TV input.

    Listens to remote.<slug> state changes (entity ID read from hass.data
    so it works regardless of tv_name). Displays current_source and
    current_identifier in the format "Apple TV (#9)" or "Input 9".
    """

    _attr_should_poll = False
    _attr_mode = "text"

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_current_identifier_text"
        self._attr_name = "1c. Current Identifier"
        self._attr_icon = "mdi:television-play"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }
        self._value = "Unknown"

    @property
    def native_value(self):
        return self._value

    async def async_added_to_hass(self):
        """
        Subscribe to remote entity state changes.
        Remote entity ID is read from hass.data (set by __init__.py)
        to support any tv_name, not just "Homekit TV".
        """
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_state_change_event

        # Look up the correct remote entity ID for this config entry
        remote_entity_id = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity", "remote.homekit_tv")
        )

        @callback
        def remote_state_changed(event):
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            source = new_state.attributes.get("current_source")
            identifier = new_state.attributes.get("current_identifier")
            if identifier is not None:
                self._value = f"{source} (#{identifier})" if source else f"Input {identifier}"
            else:
                self._value = source or "Unknown"
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, remote_entity_id, remote_state_changed
            )
        )

        # Read current state immediately
        remote_state = self.hass.states.get(remote_entity_id)
        if remote_state:
            source = remote_state.attributes.get("current_source")
            identifier = remote_state.attributes.get("current_identifier")
            if identifier is not None:
                self._value = f"{source} (#{identifier})" if source else f"Input {identifier}"
            else:
                self._value = source or "Unknown"
        self.async_write_ha_state()

    async def async_set_value(self, value: str):
        """No-op — read-only entity."""
        pass
