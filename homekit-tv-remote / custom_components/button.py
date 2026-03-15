"""Button entities for HomeKit TV Remote configuration."""
# Version: 1.4.0
#
# 1.0.0 — Initial release. ReloadHomeKitButton, TestCommandButton (reads remote
#         entity ID from hass.data), AddCustomInputButton, DeleteCustomInputButton.
#
# 1.1.0 — AddCustomInputButton reads AppleTVAppSwitch state. When ON and command
#         type is media_player, saves command_type=media_player_source so
#         media_player.py uses select_source instead of play_media.
#
# 1.2.0 — AddCustomInputButton reads AppleTVInputSwitch state. When ON and
#         command_type is media_player_source, embeds HAP identifier as |input_N
#         third segment in command string. Graceful degradation if HAP Identifier
#         field is empty.
#
# 1.3.0 — Added NextSavedInputButton ("Next Saved Input", CONFIG category).
#         Reads media_player_entity_ref from hass.data and calls
#         _cycle_custom_inputs() directly — same logic and shared index counter
#         as the iOS remote Info button.
#
# 1.4.0 — NextSavedInputButton now logs a specific warning when no inputs are
#         enabled via their HomeKitInputSwitch, matching the updated message
#         from _cycle_custom_inputs() in media_player.py 1.4.0.

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
    """Create all button entities for this config entry."""
    buttons = [
        ReloadHomeKitButton(hass, entry),
        TestCommandButton(hass, entry),
        AddCustomInputButton(hass, entry),
        DeleteCustomInputButton(hass, entry),
        NextSavedInputButton(hass, entry),
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

    Apple TV App switch ("1. Apple TV App") ON + media_player entity selected:
      Saves command_type = "media_player_source" so media_player.py uses
      select_source instead of play_media — required for Apple TV app launching.

    Apple TV Input switch ("1. Apple TV Input") ON + command_type is
    "media_player_source" + HAP Identifier field filled:
      Appends "|input_N" to the command string so media_player.py switches the
      TV HDMI input to the Apple TV port before launching the app.
      If HAP Identifier is empty, the switch is silently ignored (graceful
      degradation — input is saved without the HDMI switching segment).

    Note: newly saved inputs are excluded from HomeKit/cycle by default.
    The user must enable the corresponding "Include: <name>" switch on the
    device page after saving.
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
        apple_tv_app_switch = entities.get("apple_tv_switch")         # "1. Apple TV App"
        apple_tv_input_switch = entities.get("apple_tv_input_switch") # "1. Apple TV Input"

        input_name = text_entities.get("input_name")
        input_cmd = text_entities.get("input_command")
        input_app = text_entities.get("input_app")
        input_identifier = text_entities.get("hap_identifier")

        if not input_name or not input_name.native_value or not input_type:
            _LOGGER.error("Input name or type not set")
            return

        selected_type = input_type.current_option

        # Read switch states
        use_apple_tv_app_mode = apple_tv_app_switch._attr_is_on if apple_tv_app_switch else False
        use_apple_tv_input = apple_tv_input_switch._attr_is_on if apple_tv_input_switch else False

        if input_app and input_app.native_value:
            if not selected_type.startswith("media_player."):
                _LOGGER.error("App launching requires selecting a media_player entity in Type")
                return

            command_type = "media_player_source" if use_apple_tv_app_mode else "media_player"

            if command_type == "media_player_source":
                full_command = f"{selected_type}|{input_app.native_value}"

                if use_apple_tv_input and input_identifier and input_identifier.native_value:
                    try:
                        hap_id = int(input_identifier.native_value)
                        full_command = f"{full_command}|input_{hap_id}"
                        _LOGGER.debug(
                            "Apple TV Input switch ON — embedding HAP input switch: input_%s",
                            hap_id
                        )
                    except ValueError:
                        _LOGGER.warning(
                            "Apple TV Input switch is ON but HAP Identifier is not an integer (%s) "
                            "— saving without HDMI switching segment",
                            input_identifier.native_value
                        )
                elif use_apple_tv_input:
                    _LOGGER.warning(
                        "Apple TV Input switch is ON but HAP Identifier is empty "
                        "— saving without HDMI switching segment"
                    )
            else:
                full_command = f"{selected_type}|{input_app.native_value}|app"

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

        _LOGGER.info(
            "Added input: %s (%s: %s) — enable its 'Include: %s' switch to add it to HomeKit",
            input_name.native_value, command_type, full_command, input_name.native_value
        )


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
            # Also remove from homekit_inputs if present
            homekit_inputs = list(self._config_entry.options.get("homekit_inputs", []))
            deleted_name = deleted.get("name", "")
            if deleted_name in homekit_inputs:
                homekit_inputs.remove(deleted_name)
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options={
                    **self._config_entry.options,
                    "custom_inputs": inputs,
                    "homekit_inputs": homekit_inputs,
                }
            )
            _LOGGER.info("Deleted input: %s", deleted_name or "unknown")
        else:
            _LOGGER.warning("No inputs to delete")


# ─── Next Saved Input Button ───────────────────────────────────────────────────

class NextSavedInputButton(ButtonEntity):
    """
    Advances the included input cycle by one step.

    Calls _cycle_custom_inputs() on the live HomeKitTVMediaPlayer instance
    (stored in hass.data["media_player_entity_ref"] by media_player.py).
    Only inputs enabled via their "Include: <name>" switch are cycled.

    Logs a warning if no inputs are included or the media player reference
    is not yet available.
    Category: CONFIG
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_next_saved_input"
        self._attr_name = "Next Saved Input"
        self._attr_icon = "mdi:skip-next"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        media_player_ref = entry_data.get("media_player_entity_ref")

        if not media_player_ref:
            _LOGGER.warning(
                "Next Saved Input: media player entity reference not available yet"
            )
            return

        included_names = self._config_entry.options.get("homekit_inputs", [])
        if not included_names:
            _LOGGER.warning(
                "Next Saved Input: no inputs are enabled — "
                "turn on an 'Include: <name>' switch on the device page"
            )
            return

        await media_player_ref._cycle_custom_inputs()
