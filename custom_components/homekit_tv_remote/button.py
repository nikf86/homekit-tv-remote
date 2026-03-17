"""Button entities — test, save, delete inputs; cycle and reload."""
# Version: 1.7.0

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import logging

_LOGGER = logging.getLogger(__name__)
DOMAIN = "homekit_tv_remote"


# ─── Shared helpers ────────────────────────────────────────────────────────────

def _resolve_command(text_entities, input_type_entity, apple_tv_app_switch, apple_tv_input_switch):
    """
    Shared logic used by both TestCommandButton and AddCustomInputButton.

    Reads the config text fields and switch states to produce a
    (command_type, full_command) tuple, or raises ValueError.

    Mirrors the field-reading logic in AddCustomInputButton.async_press so
    both buttons behave identically — the only difference is Test does not save.

    Returns:
        (command_type: str, full_command: str)
    Raises:
        ValueError with a human-readable message on invalid input.
    """
    input_cmd  = text_entities.get("input_command")
    input_app  = text_entities.get("input_app")
    input_identifier = text_entities.get("hap_identifier")

    selected_type     = input_type_entity.current_option if input_type_entity else "hap"
    use_apple_tv_app  = apple_tv_app_switch._attr_is_on if apple_tv_app_switch else False
    use_apple_tv_input= apple_tv_input_switch._attr_is_on if apple_tv_input_switch else False

    if input_app and input_app.native_value:
        # ── App launch path ────────────────────────────────────────────────────
        if not selected_type.startswith("media_player."):
            raise ValueError(
                "App launching requires a media_player.* entity in Input Type"
            )
        command_type = "media_player_source" if use_apple_tv_app else "media_player"

        if command_type == "media_player_source":
            full_command = f"{selected_type}|{input_app.native_value}"
            if use_apple_tv_input and input_identifier and input_identifier.native_value:
                try:
                    hap_id = int(input_identifier.native_value)
                    full_command = f"{full_command}|input_{hap_id}"
                except ValueError:
                    raise ValueError(
                        f"HAP Identifier must be an integer, got: {input_identifier.native_value}"
                    )
        else:
            full_command = f"{selected_type}|{input_app.native_value}|app"

    elif input_cmd and input_cmd.native_value:
        # ── Command path ───────────────────────────────────────────────────────
        if selected_type == "hap":
            full_command = input_cmd.native_value
            command_type = "hap"
        elif selected_type.startswith("remote."):
            full_command = f"{selected_type}.{input_cmd.native_value}"
            command_type = "remote"
        else:
            raise ValueError(
                "For commands, Input Type must be 'hap' or a remote.* entity"
            )
    else:
        raise ValueError(
            "Fill in either 1b Command (for HAP/remote) or 1c App Name (for media_player)"
        )

    return command_type, full_command


async def _execute_command(hass, hap_remote_entity_id, command_type, full_command):
    """
    Execute a resolved command immediately without saving.

    Mirrors the dispatch logic in media_player.py _execute_input_command
    so that testing produces exactly the same behaviour as a real input switch.

    command_type="hap":
        remote.send_command on hap_remote_entity_id, command = full_command

    command_type="remote":
        Parses "remote.entity_id.CommandName"
        → remote.send_command on the named remote entity

    command_type="media_player":
        Parses "media_player.entity_id|content_id|app"
        → media_player.play_media

    command_type="media_player_source":
        Parses "media_player.entity_id|app_name[|input_N]"
        → media_player.select_source (ignores optional |input_N for testing)
    """
    if command_type == "hap":
        await hass.services.async_call(
            "remote", "send_command",
            {"entity_id": hap_remote_entity_id, "command": full_command},
            blocking=True
        )

    elif command_type == "remote":
        # format: "remote.entity_id.CommandName"
        parts = full_command.rsplit(".", 1)
        if len(parts) == 2:
            entity_id, cmd = parts
            await hass.services.async_call(
                "remote", "send_command",
                {"entity_id": entity_id, "command": cmd},
                blocking=True
            )
        else:
            raise ValueError(f"Cannot parse remote command: {full_command}")

    elif command_type == "media_player":
        # format: "media_player.entity_id|content_id|content_type"
        parts = full_command.split("|")
        if len(parts) == 3:
            entity_id, content_id, content_type = parts
            await hass.services.async_call(
                "media_player", "play_media",
                {
                    "entity_id": entity_id.strip(),
                    "media_content_id": content_id.strip(),
                    "media_content_type": content_type.strip(),
                },
                blocking=True
            )
        else:
            raise ValueError(f"Cannot parse media_player command: {full_command}")

    elif command_type == "media_player_source":
        # format: "media_player.entity_id|app_name" or
        #         "media_player.entity_id|app_name|input_N"
        # For testing, use only the first two segments (ignore HDMI switch segment)
        parts = full_command.split("|")
        if len(parts) >= 2:
            entity_id = parts[0]
            source    = parts[1]
            await hass.services.async_call(
                "media_player", "select_source",
                {"entity_id": entity_id.strip(), "source": source.strip()},
                blocking=True
            )
        else:
            raise ValueError(f"Cannot parse media_player_source command: {full_command}")


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
    """Reloads the integration then reloads HomeKit Bridge.
    Applies all pending changes (saved inputs, Include switches) and
    re-registers the TV accessory with Apple Home in one press."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_reload_homekit"
        self._attr_name = "Reload HomeKit YAML"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        import asyncio
        # Step 1: reload integration to apply all pending changes
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
        # Step 2: wait 1 second then reload HomeKit Bridge
        await asyncio.sleep(1)
        try:
            await self.hass.services.async_call("homekit", "reload", blocking=True)
            _LOGGER.info("HomeKit reloaded successfully")
        except Exception as e:
            _LOGGER.error("Failed to reload HomeKit: %s", e)


# ─── Test Command Button ───────────────────────────────────────────────────────

class TestCommandButton(ButtonEntity):
    """
    Execute the command described by the current config fields WITHOUT saving.

    Reads the same fields as AddCustomInputButton:
      1b. Command  (for hap / remote inputs)
      1c. App Name (for media_player inputs)
      1d. Input Type (select entity — hap / remote.* / media_player.*)
      1. Apple TV App switch
      1. Apple TV Input switch

    Supports all four command types:
      hap               → remote.send_command on the integration's HAP remote
      remote            → remote.send_command on any remote.* entity
      media_player      → media_player.play_media
      media_player_source → media_player.select_source (Apple TV)

    The 1a. Input Name field is intentionally NOT required — you can test a
    command before deciding on a name.

    Category: CONFIG — appears in the Configuration section alongside the
    other input fields, not in a separate Diagnostics section.
    """

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_test_command"
        self._attr_name = "1f. Test Command"
        self._attr_icon = "mdi:test-tube"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        text_entities      = entry_data.get("text_entities", {})
        input_type         = entry_data.get("input_type")
        apple_tv_app_sw    = entry_data.get("apple_tv_switch")
        apple_tv_input_sw  = entry_data.get("apple_tv_input_switch")
        hap_remote_entity  = entry_data.get("remote_entity", "remote.homekit_tv")

        try:
            command_type, full_command = _resolve_command(
                text_entities, input_type, apple_tv_app_sw, apple_tv_input_sw
            )
        except ValueError as e:
            _LOGGER.error("Test Command: %s", e)
            return

        try:
            await _execute_command(self.hass, hap_remote_entity, command_type, full_command)
            _LOGGER.info(
                "Test Command executed: type=%s command=%s", command_type, full_command
            )
        except Exception as e:
            _LOGGER.error("Test Command failed: %s", e)


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
        self._attr_name = "1g. Save Input"
        self._attr_icon = "mdi:television"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    async def async_press(self):
        entities          = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        text_entities     = entities.get("text_entities", {})
        input_type        = entities.get("input_type")
        apple_tv_app_sw   = entities.get("apple_tv_switch")
        apple_tv_input_sw = entities.get("apple_tv_input_switch")

        input_name       = text_entities.get("input_name")
        input_identifier = text_entities.get("hap_identifier")

        if not input_name or not input_name.native_value or not input_type:
            _LOGGER.error("Save Input: Input name (1a) or Input Type (1d) not set")
            return

        try:
            command_type, full_command = _resolve_command(
                text_entities, input_type, apple_tv_app_sw, apple_tv_input_sw
            )
        except ValueError as e:
            _LOGGER.error("Save Input: %s", e)
            return

        new_input = {
            "name": input_name.native_value,
            "command_type": command_type,
            "command": full_command,
        }

        # Persist HAP identifier for source-name resolution in remote.py
        if (
            command_type in ("remote", "media_player", "media_player_source")
            and input_identifier
            and input_identifier.native_value
        ):
            try:
                new_input["identifier"] = int(input_identifier.native_value)
            except ValueError:
                _LOGGER.error(
                    "Save Input: HAP Identifier must be an integer, got: %s",
                    input_identifier.native_value
                )
                return

        inputs = list(self._config_entry.options.get("custom_inputs", []))
        inputs.append(new_input)

        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options={**self._config_entry.options, "custom_inputs": inputs}
        )

        _LOGGER.info(
            "Saved input: %s (%s: %s) — enable 'Include: %s' switch to add to HomeKit",
            input_name.native_value, command_type, full_command, input_name.native_value
        )
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)


# ─── Delete Custom Input Button ────────────────────────────────────────────────

class DeleteCustomInputButton(ButtonEntity):
    """Removes the LAST entry from config_entry.options["custom_inputs"]."""

    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_delete_input"
        self._attr_name = "1h. Delete Last Input"
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
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
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
