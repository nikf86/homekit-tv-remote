"""Media Player platform for HomeKit TV Remote - HomeKit Bridge interface layer."""
# Version: 1.4.0
#
# 1.0.0 — Initial release. Bridges iOS HomeKit remote key events to HAP
#         commands. Reads entity IDs from hass.data instead of hardcoding.
#
# 1.1.0 — Added media_player_source command_type in _execute_input_command.
#         Uses select_source instead of play_media — required for Apple TV
#         app launching.
#
# 1.2.0 — _execute_input_command for media_player_source supports optional
#         third |input_N segment. When present, sends HAP input switch to
#         remote entity before calling select_source, automatically switching
#         the TV HDMI input to the Apple TV port.
#
# 1.3.0 — Stores self in hass.data[media_player_entity_ref] during
#         async_added_to_hass so NextSavedInputButton in button.py can call
#         _cycle_custom_inputs() directly. Both the iOS Info button and the
#         device page button share the same _current_input_index.
#
# 1.4.0 — source_list property and _cycle_custom_inputs() now filter
#         custom_inputs to only those whose name appears in
#         options["homekit_inputs"] — the list maintained by HomeKitInputSwitch
#         in switch.py. Inputs not in that list are hidden from the HomeKit /
#         HA source list and skipped by the cycle entirely.
#         _current_input_index is reset to 0 whenever the filtered list is
#         shorter than the current index to avoid out-of-range errors after
#         an input is excluded mid-session.

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "homekit_tv_remote"


# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entity_id = entry.data.get("media_player_entity_id")
    if not entity_id:
        return

    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    hap_remote_entity_id = data.get("remote_entity", "remote.homekit_tv")
    media_player_entity_id = data.get("media_player_entity", "media_player.homekit_tv")

    async_add_entities(
        [HomeKitTVMediaPlayer(hass, hap_remote_entity_id, media_player_entity_id, entry)],
        True
    )


# ─── HomeKitTVMediaPlayer Entity ──────────────────────────────────────────────

class HomeKitTVMediaPlayer(MediaPlayerEntity):
    """
    Media player entity bridging iOS HomeKit remote button presses to HAP commands.
    Entity ID is derived from tv_name so HomeKit Bridge always finds the correct entity.
    """

    _attr_should_poll = False

    def __init__(self, hass, hap_remote_entity_id, media_player_entity_id, config_entry):
        self.hass = hass
        self._hap_remote_entity = hap_remote_entity_id
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_media_player"
        self.entity_id = media_player_entity_id
        self._attr_name = config_entry.data.get("tv_name", "Homekit TV")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": config_entry.data.get("tv_name", "Homekit TV"),
            "manufacturer": "Anthropic",
            "model": "HomeKit TV Remote Control",
        }
        self._state = None
        self._source = None
        self._volume_level = None
        self._is_volume_muted = None
        self._current_input_index = 0

    # ─── Helpers ───────────────────────────────────────────────────────────────

    def _included_inputs(self) -> list:
        """
        Return only the custom_inputs whose name is in options["homekit_inputs"].

        Called by source_list and _cycle_custom_inputs. Reads options live on
        every call so toggling a HomeKitInputSwitch takes effect immediately
        without a reload.
        """
        all_inputs = self._config_entry.options.get("custom_inputs", [])
        included_names = set(self._config_entry.options.get("homekit_inputs", []))
        return [inp for inp in all_inputs if inp.get("name") in included_names]

    # ─── Subscriptions ─────────────────────────────────────────────────────────

    async def async_added_to_hass(self):
        """
        Called once the entity is registered in HA.

        Stores self in hass.data so NextSavedInputButton (button.py) can call
        _cycle_custom_inputs() on this instance directly, sharing the same
        _current_input_index counter as the iOS remote Info button path.
        """
        # Store reference for NextSavedInputButton in button.py
        self.hass.data.setdefault(DOMAIN, {})
        self.hass.data[DOMAIN].setdefault(self._config_entry.entry_id, {})
        self.hass.data[DOMAIN][self._config_entry.entry_id]["media_player_entity_ref"] = self

        @callback
        def remote_state_changed(event):
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            self._state = new_state.state
            hap_source = new_state.attributes.get("current_source")
            if hap_source is not None:
                self._source = hap_source
                _LOGGER.debug("Source updated from HAP: %s", self._source)
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._hap_remote_entity, remote_state_changed
            )
        )

        button_to_key = {
            "arrow_up":    "4",
            "arrow_down":  "5",
            "arrow_left":  "6",
            "arrow_right": "7",
            "select":      "8",
            "back":        "9",
            "play_pause":  "11",
        }

        @callback
        def homekit_key_pressed(event):
            entity_id = event.data.get("entity_id")
            if entity_id != self.entity_id:
                return
            key_name = event.data.get("key_name", "")
            _LOGGER.debug("HomeKit key pressed: %s", key_name)
            if key_name == "information":
                self.hass.async_create_task(self._cycle_custom_inputs())
            elif key_name in button_to_key:
                command = button_to_key[key_name]
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "remote",
                        "send_command",
                        {"entity_id": self._hap_remote_entity, "command": command},
                        blocking=True
                    )
                )

        self.async_on_remove(
            self.hass.bus.async_listen(
                "homekit_tv_remote_key_pressed", homekit_key_pressed
            )
        )

        remote_state = self.hass.states.get(self._hap_remote_entity)
        if remote_state:
            self._state = remote_state.state
            hap_source = remote_state.attributes.get("current_source")
            if hap_source:
                self._source = hap_source

    # ─── HA Entity Properties ──────────────────────────────────────────────────

    @property
    def state(self):
        return self._state

    @property
    def source(self):
        return self._source

    @property
    def source_list(self):
        """
        Return only inputs enabled via their HomeKitInputSwitch.
        This is what HomeKit Bridge and the HA media player card display.
        Inputs with their switch OFF are invisible to HomeKit and HA.
        """
        return [inp["name"] for inp in self._included_inputs()]

    @property
    def volume_level(self):
        return self._volume_level

    @property
    def is_volume_muted(self):
        return self._is_volume_muted

    @property
    def supported_features(self):
        return (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.PLAY_MEDIA
        )

    @property
    def device_class(self):
        return "tv"

    # ─── Power Control ─────────────────────────────────────────────────────────

    async def async_turn_on(self):
        try:
            await self.hass.services.async_call(
                "remote", "turn_on",
                {"entity_id": self._hap_remote_entity},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error turning on TV: %s", e)

    async def async_turn_off(self):
        try:
            await self.hass.services.async_call(
                "remote", "turn_off",
                {"entity_id": self._hap_remote_entity},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error turning off TV: %s", e)

    # ─── Volume Control ────────────────────────────────────────────────────────

    async def async_volume_up(self):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "volume_up"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error volume up: %s", e)

    async def async_volume_down(self):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "volume_down"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error volume down: %s", e)

    async def async_mute_volume(self, mute):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "mute"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error muting volume: %s", e)

    # ─── Source Selection ──────────────────────────────────────────────────────

    async def async_select_source(self, source):
        """
        Execute a saved input by name.
        Searches all custom_inputs (not just included ones) so that direct
        selection via the HA UI always works even if the input is excluded
        from the cycle.
        """
        custom_inputs = self._config_entry.options.get("custom_inputs", [])
        for inp in custom_inputs:
            if inp["name"] == source:
                await self._execute_input_command(inp)
                return

    async def _execute_input_command(self, input_config):
        """
        Execute a saved custom input command based on its command_type.

        command_type="hap":
            Sends command string (e.g. "input_9") to remote.<slug>
            → remote.py interprets as ActiveIdentifier=9.

        command_type="remote":
            Parses "remote.entity_id.CommandName" → calls remote.send_command.

        command_type="media_player":
            Parses "media_player.entity_id|content_id|content_type"
            → calls media_player.play_media.

        command_type="media_player_source":
            Parses "media_player.entity_id|app_name" (two segments)
            or    "media_player.entity_id|app_name|input_N" (three segments).

            Two-segment form: calls media_player.select_source only.
            Three-segment form: sends HAP input switch first, then select_source.
        """
        command_type = input_config.get("command_type", "hap")
        command = input_config.get("command", "")

        if command_type == "hap":
            await self.hass.services.async_call(
                "remote",
                "send_command",
                {"entity_id": self._hap_remote_entity, "command": command},
                blocking=True
            )

        elif command_type == "remote":
            if "." in command:
                parts = command.rsplit(".", 1)
                if len(parts) == 2:
                    entity_id, cmd = parts
                    await self.hass.services.async_call(
                        "remote",
                        "send_command",
                        {"entity_id": entity_id, "command": cmd},
                        blocking=True
                    )

        elif command_type == "media_player":
            if "|" in command:
                parts = command.split("|")
                if len(parts) == 3:
                    entity_id, content_id, content_type = parts
                    await self.hass.services.async_call(
                        "media_player",
                        "play_media",
                        {
                            "entity_id": entity_id.strip(),
                            "media_content_id": content_id.strip(),
                            "media_content_type": content_type.strip()
                        },
                        blocking=True
                    )

        elif command_type == "media_player_source":
            if "|" in command:
                parts = command.split("|")
                if len(parts) >= 2:
                    entity_id = parts[0].strip()
                    app_name = parts[1].strip()
                    hap_input = parts[2].strip() if len(parts) >= 3 else None

                    if hap_input:
                        _LOGGER.debug(
                            "Apple TV Input: switching TV to %s before launching app", hap_input
                        )
                        try:
                            await self.hass.services.async_call(
                                "remote",
                                "send_command",
                                {
                                    "entity_id": self._hap_remote_entity,
                                    "command": hap_input
                                },
                                blocking=True
                            )
                        except Exception as e:
                            _LOGGER.error(
                                "Error switching TV input to %s before Apple TV app launch: %s",
                                hap_input, e
                            )

                    await self.hass.services.async_call(
                        "media_player",
                        "select_source",
                        {
                            "entity_id": entity_id,
                            "source": app_name
                        },
                        blocking=True
                    )

    # ─── Info Button / Next Saved Input: Input Cycling ─────────────────────────

    async def _cycle_custom_inputs(self):
        """
        Execute the next included input in the cycle and advance the index.

        Only inputs enabled via their HomeKitInputSwitch ("Include: <name>")
        are considered. The index is reset to 0 if the filtered list has
        shrunk since the last press (e.g. an input was excluded mid-session).

        Called by:
          - homekit_key_pressed callback (iOS remote Info button)
          - NextSavedInputButton.async_press() (device page button)

        Both share this instance's _current_input_index.
        """
        included = self._included_inputs()
        if not included:
            _LOGGER.warning("No included inputs configured — cycle has no effect")
            return

        # Guard against index going out of range if inputs were excluded
        if self._current_input_index >= len(included):
            self._current_input_index = 0

        current_input = included[self._current_input_index]
        _LOGGER.info(
            "Cycling to input: %s (index %d of %d included)",
            current_input["name"], self._current_input_index + 1, len(included)
        )
        await self._execute_input_command(current_input)
        self._current_input_index = (self._current_input_index + 1) % len(included)

    # ─── Playback Control ──────────────────────────────────────────────────────

    async def async_media_play(self):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending play: %s", e)

    async def async_media_pause(self):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending pause: %s", e)

    async def async_media_stop(self):
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending stop: %s", e)
