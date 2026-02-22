"""Media Player platform for HomeKit TV Remote - HomeKit Bridge interface layer."""
# Version: 1.0.1
#
# CHANGES FROM 1.0.0:
# - Remote entity ID and media_player entity ID are now read from
#   hass.data[DOMAIN][entry_id] (set by __init__.py) instead of being
#   hardcoded to "remote.homekit_tv" / "media_player.homekit_tv".
#   This fixes unavailable entities when tv_name is anything other than
#   "Homekit TV" during setup.

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
    """
    Called by HA when setting up the media_player platform.
    Reads derived entity IDs from hass.data (set by __init__.py).
    """
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
    Media player entity that bridges iOS HomeKit remote button presses to HAP commands.

    Entity ID: derived from tv_name (e.g. media_player.sony_tv) — forced so
    HomeKit Bridge always finds this exact entity ID regardless of HA's auto-naming.

    State:  mirrors remote.<slug> state (on/off/idle)
    Source: mirrors remote.<slug> current_source attribute
    """

    _attr_should_poll = False

    def __init__(self, hass, hap_remote_entity_id, media_player_entity_id, config_entry):
        self.hass = hass
        self._hap_remote_entity = hap_remote_entity_id      # e.g. "remote.sony_tv"
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_media_player"

        # Force entity_id to match the slug so HomeKit Bridge finds it correctly
        self.entity_id = media_player_entity_id             # e.g. "media_player.sony_tv"

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

    # ─── Subscriptions ─────────────────────────────────────────────────────────

    async def async_added_to_hass(self):
        """Register state and key-press listeners."""

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
            Sends the command string (e.g. "input_9") to remote.<slug>
            which remote.py interprets as ActiveIdentifier=9.

        command_type="remote":
            Parses "remote.bravia.Hdmi2" as entity_id + command
            and calls remote.send_command on that entity.

        command_type="media_player":
            Parses "media_player.bravia|Cosmote|app" as
            entity_id | media_content_id | media_content_type and calls
            media_player.play_media on that entity.
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
    # All three send RemoteKey=11 (PlayPause) — TV has no separate Play/Pause/Stop.

    async def async_media_play(self):
        """Send PlayPause (RemoteKey=11) — TV does not have separate Play key."""
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending play: %s", e)

    async def async_media_pause(self):
        """Send PlayPause (RemoteKey=11) — same key as play on this TV."""
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending pause: %s", e)

    async def async_media_stop(self):
        """Send PlayPause (RemoteKey=11) — no dedicated stop key via HAP."""
        try:
            await self.hass.services.async_call(
                "remote", "send_command",
                {"entity_id": self._hap_remote_entity, "command": "11"},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error("Error sending stop: %s", e)
