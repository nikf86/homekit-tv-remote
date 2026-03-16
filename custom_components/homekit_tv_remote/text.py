"""Text input fields and Current Identifier display for the device page."""
# Version: 1.1.0

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

DOMAIN = "homekit_tv_remote"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create input fields and store references so button.py can read their values."""
    texts = [
        ConfigTextEntity(hass, entry, "input_name",
                         "1a. Input Name", EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "input_command",
                         "1b. Command (HAP / remote — or leave empty for app)",
                         EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "input_app",
                         "1c. App Name (media_player — or leave empty for command)",
                         EntityCategory.CONFIG),
        ConfigTextEntity(hass, entry, "hap_identifier",
                         "1e. HAP Identifier (for remote/media_player only)",
                         EntityCategory.CONFIG),
        CurrentIdentifierTextEntity(hass, entry),
    ]

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["text_entities"] = {
        t._key: t for t in texts if hasattr(t, "_key")
    }
    async_add_entities(texts)


class ConfigTextEntity(TextEntity):
    """Editable text field. Value lives in memory only — resets on reload."""

    def __init__(self, hass, config_entry, key, name, entity_category=None):
        self.hass = hass
        self._config_entry = config_entry
        self._key = key
        self._value = ""
        self._attr_unique_id = f"{config_entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_entity_category = entity_category
        self._attr_device_info = {"identifiers": {(DOMAIN, config_entry.entry_id)}}

    @property
    def native_value(self):
        return self._value

    async def async_set_value(self, value: str):
        self._value = value
        self.async_write_ha_state()


class CurrentIdentifierTextEntity(TextEntity):
    """Read-only field showing the active TV input — 'Apple TV (#9)' or 'Input 9'.
    Lives in CONFIG category so it's visible next to the input fields without
    expanding Diagnostics. Subscribes to the remote entity state changes."""

    _attr_should_poll = False
    _attr_mode = "text"

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._value = "Unknown"
        self._attr_unique_id = f"{config_entry.entry_id}_current_identifier_text"
        self._attr_name = "1i. Current Identifier"
        self._attr_icon = "mdi:television-play"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {"identifiers": {(DOMAIN, config_entry.entry_id)}}

    @property
    def native_value(self):
        return self._value

    def _parse_state(self, state):
        source = state.attributes.get("current_source")
        identifier = state.attributes.get("current_identifier")
        if identifier is not None:
            self._value = f"{source} (#{identifier})" if source else f"Input {identifier}"
        else:
            self._value = source or "Unknown"

    async def async_added_to_hass(self):
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_state_change_event

        remote_id = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("remote_entity", "remote.homekit_tv")
        )

        @callback
        def _changed(event):
            new = event.data.get("new_state")
            if new:
                self._parse_state(new)
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, remote_id, _changed)
        )

        state = self.hass.states.get(remote_id)
        if state:
            self._parse_state(state)
        self.async_write_ha_state()

    async def async_set_value(self, value: str):
        pass  # read-only
