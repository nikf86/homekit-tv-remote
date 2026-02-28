"""Button entities for HomeKit TV Remote configuration."""
# Version: 1.1.0
#
# CHANGES FROM 1.0.0:
# - TestCommandButton now reads remote entity ID from hass.data[DOMAIN][entry_id]
#   instead of hardcoding "remote.homekit_tv".
# CHANGES FROM 1.1.0:
# - AddCustomInputButton now reads the AppleTVSwitch state from hass.data.
#   When Apple TV switch is ON and command type is media_player, saves
#   command_type = "media_player_source" instead of "media_player".
#   media_player_source uses select_source instead of play_media in
#   media_player.py _execute_input_command.

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

_LOGGER = logging.getLogger(__name__)
DOMAIN = "homekit_tv_remote"


# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create all four button entities for this config entry."""
    buttons = [
        ReloadHomeKitButton(hass, entry),
        TestCommandButton(hass, entry),
        AddCustomInputButton(hass, entry),
        DeleteCustomInputButton(hass, entry),
    ]
    async_add_entities(buttons)


# ─── Reload HomeKit Button ─────────────────────────────────────────────────────

class ReloadHomeKitButton(ButtonEntity):
    """Calls the homekit.reload service."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_reload_homekit"
        self._attr_name = "Reload HomeKit YAML"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "HomeKit TV Remote",
            "manufacturer": "HomeKit TV Remote",
            "model": "v2.0",
        }

    async def async_press(self):
        try:
            await self.hass.services.async_call("homekit", "reload", blocking=True)
            _LOGGER.info("HomeKit reloaded successfully")
        except Exception as e:
            _LOGGER.error("Failed to reload HomeKit: %s", e)


# ─── Test Command Button ───────────────────────────────────────────────────────

class TestCommandButton(ButtonEntity):
    """Sends the test command text field value to the TV remote entity."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_test_command"
        self._attr_name = "1b. Send Test Command"
        self._attr_icon = "mdi:test-tube"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "HomeKit TV Remote",
            "manufacturer": "HomeKit TV Remote",
            "model": "v2.0",
        }

    async def async_press(self):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        remote_entity_id = entry_data.get("remote_entity", "remote.homekit_tv")
        text_entities = entry_data.get("text_entities", {})
        test_cmd = text_entities.get("test_command")

        if test_cmd and test_cmd.native_value:
            try:
                await self.hass.services.async_call(
                    "remote",
                    "send_command",
                    {"entity_id": remote_entity_id, "command": test_cmd.native_value},
                    blocking=True
                )
                _LOGGER.info("Tested HAP command: %s", test_cmd.native_value)
            except Exception as e:
                _LOGGER.error("Test failed: %s", e)
        else:
            _LOGGER.error("Test command not set")


# ─── Add Custom Input Button ───────────────────────────────────────────────────

class AddCustomInputButton(ButtonEntity):
    """
    Reads all input fields and saves a new custom input to config_entry.options.

    When the Apple TV switch (switch "1. Apple TV") is ON and the selected type
    is a media_player entity, saves command_type = "media_player_source" instead
    of "media_player". This causes media_player.py to use select_source instead
    of play_media — the only working method for Apple TV app launching.
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_add_input"
        self._attr_name = "1e. Save Input"
        self._attr_icon = "mdi:television"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        entities = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        text_entities = entities.get("text_entities", {})
        input_type = entities.get("input_type")
        apple_tv_switch = entities.get("apple_tv_switch")

        input_name = text_entities.get("input_name")
        input_cmd = text_entities.get("input_command")
        input_app = text_entities.get("input_app")
        input_identifier = text_entities.get("hap_identifier")

        if not input_name or not input_name.native_value or not input_type:
            _LOGGER.error("Input name or type not set")
            return

        selected_type = input_type.current_option

        # Read Apple TV switch state — True means use select_source
        use_apple_tv_mode = apple_tv_switch._attr_is_on if apple_tv_switch else False

        if input_app and input_app.native_value:
            if not selected_type.startswith("media_player."):
                _LOGGER.error("App launching requires selecting a media_player entity in Type")
                return
            full_command = f"{selected_type}|{input_app.native_value}"
            # Use media_player_source if Apple TV switch is ON, else media_player
            command_type = "media_player_source" if use_apple_tv_mode else "media_player"
            # Append |app suffix only for standard play_media path
            if command_type == "media_player":
                full_command = f"{full_command}|app"

        elif input_cmd and input_cmd.native_value:
            if selected_type == "hap":
                full_command = input_cmd.native_value
                command_type = "hap"
            elif selected_type.startswith("remote."):
                full_command = f"{selected_type}.{input_cmd.native_value}"
                command_type = "remote"
            else:
                _LOGGER.error("For commands, Type must be 'hap' or a remote entity")
                return
        else:
            _LOGGER.error("Either Command (1b) or App Name (1c) must be filled")
            return

        new_input = {
            "name": input_name.native_value,
            "command_type": command_type,
            "command": full_command
        }

        if command_type in ("remote", "media_player", "media_player_source") and input_identifier and input_identifier.native_value:
            try:
                new_input["identifier"] = int(input_identifier.native_value)
            except ValueError:
                _LOGGER.error("HAP Identifier must be an integer, got: %s", input_identifier.native_value)
                return

        inputs = list(self._config_entry.options.get("custom_inputs", []))
        inputs.append(new_input)

        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "custom_inputs": inputs}
        )

        _LOGGER.info("Added input: %s (%s: %s)", input_name.native_value, command_type, full_command)


# ─── Delete Custom Input Button ────────────────────────────────────────────────

class DeleteCustomInputButton(ButtonEntity):
    """Removes the LAST entry from config_entry.options["custom_inputs"]."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_delete_input"
        self._attr_name = "1f. Delete Last Input"
        self._attr_icon = "mdi:delete"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        inputs = list(self._config_entry.options.get("custom_inputs", []))
        if inputs:
            deleted = inputs.pop()
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options={**self._config_entry.options, "custom_inputs": inputs}
            )
            _LOGGER.info("Deleted input: %s", deleted.get("name", "unknown"))
        else:
            _LOGGER.warning("No inputs to delete")
