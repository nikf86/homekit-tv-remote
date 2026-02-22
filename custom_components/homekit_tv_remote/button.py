"""Button entities for HomeKit TV Remote configuration."""
# Version: 1.0.1
#
# CHANGES FROM 1.0.0:
# - TestCommandButton now reads remote entity ID from hass.data[DOMAIN][entry_id]
#   instead of hardcoding "remote.homekit_tv". This fixes the test command
#   button when tv_name is anything other than "Homekit TV".

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
    """
    Calls the homekit.reload service.
    Must be pressed after Save Input / Delete Input to reconnect the
    HomeKit Bridge to the updated media player entity.
    """

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
    """
    Reads the value typed in the "1a. Test Command" text entity and sends it
    to the TV remote entity via remote.send_command.

    Remote entity ID is read from hass.data (derived from tv_name in __init__.py)
    rather than hardcoded, so it works with any tv_name entered during setup.
    """

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
        """
        Read the test_command text entity value and send it to the remote entity.
        Remote entity ID is looked up from hass.data to support any tv_name.
        """
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
    Reads the input name, command/app, type, and optional HAP identifier from
    the text and select entities, constructs a new input dict, and appends it
    to config_entry.options["custom_inputs"].
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

        input_name = text_entities.get("input_name")
        input_cmd = text_entities.get("input_command")
        input_app = text_entities.get("input_app")
        input_identifier = text_entities.get("hap_identifier")

        if not input_name or not input_name.native_value or not input_type:
            _LOGGER.error("Input name or type not set")
            return

        selected_type = input_type.current_option

        if input_app and input_app.native_value:
            if not selected_type.startswith("media_player."):
                _LOGGER.error("App launching requires selecting a media_player entity in Type (3d)")
                return
            full_command = f"{selected_type}|{input_app.native_value}|app"
            command_type = "media_player"

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
            _LOGGER.error("Either Command (3b) or App Name (3c) must be filled")
            return

        new_input = {
            "name": input_name.native_value,
            "command_type": command_type,
            "command": full_command
        }

        if command_type in ("remote", "media_player") and input_identifier and input_identifier.native_value:
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
