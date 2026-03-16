"""Input Type dropdown — lets the user choose hap / remote.* / media_player.*."""
# Version: 1.0.0

from homeassistant.components.select import SelectEntity
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
    """Create the dropdown and store a reference so button.py can read current_option."""
    input_type = InputTypeSelectEntity(hass, entry)
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["input_type"] = input_type
    async_add_entities([input_type])


class InputTypeSelectEntity(SelectEntity):
    """Dropdown for the command type when adding a new input.

    Options are built once at load time from all remote.* and media_player.*
    entities in HA. Selected value is in-memory only — resets to 'hap' on
    reload to avoid triggering a reload when the user changes the dropdown."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_input_type"
        self._attr_name = "1d. Input Type"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {"identifiers": {(DOMAIN, config_entry.entry_id)}}
        self._build_options()

    def _build_options(self):
        """Populate options list: hap first, then all external remote.* and media_player.*."""
        options = ["hap"]
        slug = self._config_entry.entry_id  # used to exclude our own entities
        tv_slug = self.hass.data.get(DOMAIN, {}).get(slug, {})
        own_remote = tv_slug.get("remote_entity", "")
        own_mp = tv_slug.get("media_player_entity", "")

        for state in self.hass.states.async_all("remote"):
            if state.entity_id != own_remote:
                options.append(state.entity_id)
        for state in self.hass.states.async_all("media_player"):
            if state.entity_id != own_mp:
                options.append(state.entity_id)

        self._attr_options = options
        self._attr_current_option = "hap"

    async def async_select_option(self, option: str):
        self._attr_current_option = option
        self.async_write_ha_state()
