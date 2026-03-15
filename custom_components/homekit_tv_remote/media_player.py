"""Media Player platform for HomeKit TV Remote - HomeKit Bridge interface layer."""
# Version: 1.3.0
#
# CHANGES FROM 1.3.0:
# - Fixed media_player_source execution when Apple TV Input switch was ON.
#   button.py saves a 3-segment command: "media_player.entity|app_name|input_N".
#   Old split("|", 1) passed "app_name|input_N" as the source — broken.
#   Now: if 3 segments, sends HAP input switch first, then select_source with
#   just the app name. Falls back to 2-segment if no input switch segment.
#
# CHANGES FROM 1.0.0:
# - Remote entity ID and media_player entity ID are now read from
#   hass.data[DOMAIN][entry_id] (set by __init__.py) instead of being
#   hardcoded to "remote.homekit_tv" / "media_player.homekit_tv".
# CHANGES FROM 1.1.0:
# - Added "media_player_source" command_type branch in _execute_input_command.
#   Uses media_player.select_source instead of media_player.play_media.
#   Required for Apple TV integration where play_media is broken for app launching.
#   Command format: "media_player.entity_id|app_name"
# CHANGES FROM 1.2.0:
# - _volume_level initialised to 0.5 (dummy, non-None) and _is_volume_muted
#   initialised to False (dummy, non-None). HA hides volume and mute controls
#   in the integration card whenever these properties return None, regardless
#   of what is declared in supported_features. Since this integration uses
#   HAP step commands (no absolute volume tracking), a static dummy value is
#   the correct approach to keep the controls visible at all times.

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
        self._volume_level = 0.5        # Dummy non-None value — HAP uses step commands,
        self._is_volume_muted = False   # not absolute levels. None hides the controls.
        self._current_input_index = 0

    # ─── Subscriptions ─────────────────────────────────────────────────────────

    async def async_added_to_hass(self):

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
        custom_inputs = self._config_entry.options.get("custom_inputs", [])
        return [inp["name"] for inp in custom_inputs] if custom_inputs else []

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
            Parses "media_player.entity_id|app_name"
            → calls media_player.select_source.
            Used for Apple TV where play_media is broken for app launching.
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
            # Apple TV path — uses select_source instead of play_media.
            #
            # Two possible formats saved by button.py:
            #   2 segments: "media_player.entity_id|app_name"
            #     → Apple TV Input switch was OFF — just launch the app.
            #   3 segments: "media_player.entity_id|app_name|input_N"
            #     → Apple TV Input switch was ON — switch the TV HDMI input
            #       to input_N first, then launch the app.
            #
            # The HAP input switch is sent to the integration's own remote entity
            # (self._hap_remote_entity) since input_N is a HAP ActiveIdentifier
            # command, not an Apple TV command. Both commands are fired immediately
            # with no delay — they go to two separate devices (TV and Apple TV)
            # so there is no conflict or sequencing dependency.
            if "|" not in command:
                return
            parts = command.split("|")
            if len(parts) == 3:
                # 3-segment: switch HDMI input first, then launch app
                entity_id, app_name, hap_input_cmd = parts
                await self.hass.services.async_call(
                    "remote",
                    "send_command",
                    {
                        "entity_id": self._hap_remote_entity,
                        "command": hap_input_cmd.strip()
                    },
                    blocking=True
                )
                await self.hass.services.async_call(
                    "media_player",
                    "select_source",
                    {
                        "entity_id": entity_id.strip(),
                        "source": app_name.strip()
                    },
                    blocking=True
                )
            elif len(parts) == 2:
                # 2-segment: just launch the app
                entity_id, app_name = parts
                await self.hass.services.async_call(
                    "media_player",
                    "select_source",
                    {
                        "entity_id": entity_id.strip(),
                        "source": app_name.strip()
                    },
                    blocking=True
                )

    # ─── Info Button: Input Cycling ────────────────────────────────────────────

    async def _cycle_custom_inputs(self):
        """Cycle through saved custom_inputs when the iOS remote Info button is pressed."""
        custom_inputs = self._config_entry.options.get("custom_inputs", [])
        if not custom_inputs:
            _LOGGER.warning("No custom inputs configured, Info button has no effect")
            return
        current_input = custom_inputs[self._current_input_index]
        _LOGGER.info(
            "Cycling to input: %s (index %d of %d)",
            current_input["name"], self._current_input_index + 1, len(custom_inputs)
        )
        await self._execute_input_command(current_input)
        self._current_input_index = (self._current_input_index + 1) % len(custom_inputs)

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
