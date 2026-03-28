"""Remote platform for HomeKit TV Remote - HAP communication layer."""
# Version: 1.2.1
#
# ROLE IN INTEGRATION:
# Core HAP communication layer. Connects to the TV via homekit_controller
# pairing for sending commands. State (on/off and current input) is derived
# by listening to the HomeKit Controller media_player entity selected during
# setup — no HAP polling or push subscription.
#
# On setup it:
#   1. Looks up the homekit_controller connection object for the paired TV
#   2. Scans the TV's accessory characteristic list for the 5 key characteristics:
#      RemoteKey, Active, VolumeSelector, ActiveIdentifier, Mute
#   3. Creates the TVRemote entity
#
# At runtime it:
#   - Listens to state changes of the HK Controller media_player entity
#   - On each change: reads state (on/off) and derives current_identifier
#     from the position of attributes.source in attributes.source_list (1-based:
#     first entry = identifier 1, second = identifier 2, etc.)
#   - Exposes current_source and current_identifier as state attributes
#     (read by media_player.py and text.py to display the current input)
#   - Sends all HAP commands (RemoteKey, Volume, Mute, Input switch) via
#     put_characteristics on the raw connection
#
# CHANGES FROM 1.1.0:
# - Removed HAP polling loop (get_characteristics timer for Active +
#   ActiveIdentifier) and push subscription attempt entirely.
# - Removed imports: timedelta, async_track_time_interval.
# - Removed methods: _try_native_subscription, _poll_active_identifier.
# - Removed attributes: _subscription_active, _change_reason.
# - Added: _hk_entity_id stored in __init__; async_added_to_hass now
#   subscribes to HK Controller media_player state changes only.
# - Added: _update_from_hk_state derives identifier from source_list
#   position (1-based). No friendly name fallback — source is always
#   present in source_list in normal operation.
# - _get_source_name_for_identifier: matches custom_inputs only;
#   added media_player_source to recognised command_types; falls back
#   to "Input N". No raw HK source name lookup anywhere.
# - extra_state_attributes: removed subscription_active and change_reason.
# - async_turn_on/off: added async_write_ha_state() after optimistic update.
# - TVRemote.__init__ signature: removed unused 'name' positional arg.
#
# Dependencies:
#   - Requires homekit_controller to be set up and paired with the TV
#   - hass.data["homekit_tv_remote"][entry_id]["remote_entity_ref"] is set here
#     so that switch.py can flip _debug_listen/_debug_send flags without a reload

import asyncio
from typing import Iterable

from aiohomekit.model.characteristics import CharacteristicsTypes as CT

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "homekit_tv_remote"

# Prefixes used in warning-level debug log lines so they can be grep'd
DEBUG_LISTEN = "HOMEKIT_TV_LISTEN"  # Logs about receiving/reading data from TV
DEBUG_SEND = "HOMEKIT_TV_SEND"      # Logs about sending commands to TV

# ─── HAP Error Status Codes ────────────────────────────────────────────────────
# Standard HAP protocol error codes returned by the TV accessory.
# Used in _handle_hap_error() to classify errors and set last_hap_error attribute.
HAP_STATUS_SUCCESS = 0
HAP_STATUS_INSUFFICIENT_PRIVILEGES = -70401
HAP_STATUS_SERVICE_COMMUNICATION_FAILURE = -70402
HAP_STATUS_RESOURCE_BUSY = -70403
HAP_STATUS_READ_ONLY_CHARACTERISTIC = -70404
HAP_STATUS_WRITE_ONLY_CHARACTERISTIC = -70405
HAP_STATUS_NOTIFICATION_NOT_SUPPORTED = -70406
HAP_STATUS_OUT_OF_RESOURCE = -70407
HAP_STATUS_OPERATION_TIMED_OUT = -70408
HAP_STATUS_RESOURCE_DOES_NOT_EXIST = -70409
HAP_STATUS_INVALID_VALUE = -70410

# ─── HAP RemoteKey Integer Values ──────────────────────────────────────────────
# Written to RemoteKey characteristic via put_characteristics.
# 0: Rewind          1: FastForward    2: NextTrack      3: PreviousTrack
# 4: ArrowUp         5: ArrowDown      6: ArrowLeft      7: ArrowRight
# 8: Select          9: Back           10: Exit          11: PlayPause
# 12: PlayPause(ATV) 13: Unknown       14: TV Settings   15: Information
# 16: TV Home

# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Called by HA when setting up the remote platform for this config entry.

    Steps:
    1. Look up the homekit_controller media_player entity selected during setup
       (stored in entry.data["media_player_entity_id"])
    2. Find the homekit_controller connection (device) that owns that entity
    3. Walk the TV's accessory/service/characteristic tree to find the 5
       characteristics needed: RemoteKey, Active, VolumeSelector,
       ActiveIdentifier, Mute — stored as (aid, iid) tuples.
       ActiveIdentifier is still found for input switching (put) but is
       never read — the HK Controller entity is the sole source of truth
       for on/off state and current input.
    4. Create the TVRemote entity and register it in hass.data so switch.py
       can update debug flags without triggering a reload
    """

    # ── Step 1: Resolve the homekit_controller entity from config ──────────────
    entity_id = entry.data.get("media_player_entity_id")
    if not entity_id:
        _LOGGER.error("remote.py: no media_player_entity_id in config entry")
        return

    e = er.async_get(hass).async_get(entity_id)
    if not e:
        _LOGGER.error("remote.py: entity %s not found in registry", entity_id)
        return

    # ── Step 2: Find the homekit_controller connection object ──────────────────
    # hass.data["homekit_controller-devices"] is a dict of device connections
    # maintained by the homekit_controller integration. We match on config_entry_id.
    conn = None
    for d in hass.data.get("homekit_controller-devices", {}).values():
        if getattr(getattr(d, 'config_entry', None), 'entry_id', None) == e.config_entry_id:
            conn = d
            break

    if not conn:
        _LOGGER.error("remote.py: no homekit_controller connection found for %s", entity_id)
        return

    # ── Step 3: Walk the accessory tree to find HAP characteristics ────────────
    # Try three possible locations for the accessories list depending on
    # the version of aiohomekit / homekit_controller in use.
    acc = (
        getattr(getattr(conn, 'entity_map', None), 'accessories', None)
        or getattr(conn, 'accessories', None)
        or getattr(getattr(conn, 'pairing', None), 'accessories', None)
    )

    if not acc:
        _LOGGER.error("remote.py: no accessories found on connection (type=%s)", type(conn).__name__)
        return

    # Scan all accessories → services → characteristics for the 5 we need.
    # Store each as (aid, iid) tuple — the minimal info needed for put/get calls.
    rk = act = vol = inp = mut = None

    for a in acc:
        aid = a.aid
        for s in a.services:
            for c in s.characteristics:
                t = c.type
                if not rk and t == CT.REMOTE_KEY:
                    rk = (aid, c.iid)         # Write: RemoteKey integer → TV navigation
                elif not act and t == CT.ACTIVE:
                    act = (aid, c.iid)         # Write: 1=on, 0=standby
                elif not vol and t == CT.VOLUME_SELECTOR:
                    vol = (aid, c.iid)         # Write: 0=up, 1=down (2=mute on some TVs)
                elif not inp and t == CT.ACTIVE_IDENTIFIER:
                    inp = (aid, c.iid)         # Write: switch input by identifier number
                elif not mut and t == CT.MUTE:
                    mut = (aid, c.iid)         # Read/Write: mute toggle

    # RemoteKey is mandatory — without it the integration has no purpose
    if not rk:
        _LOGGER.error(
            "remote.py: RemoteKey characteristic not found on TV — rk=%s act=%s vol=%s inp=%s",
            rk, act, vol, inp
        )
        return

    # ── Step 4: Create entity and register reference in shared data ────────────
    debug_listen = entry.options.get("debug_listen", False)
    debug_send = entry.options.get("debug_send", False)

    entity = TVRemote(
        hass, entry.entry_id, conn, rk, act, vol, inp, mut,
        debug_listen, debug_send, entry,
        hk_entity_id=entity_id
    )

    # Store reference so DebugListenSwitch / DebugSendSwitch in switch.py
    # can flip _debug_listen / _debug_send on the live entity without a reload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["remote_entity_ref"] = entity

    async_add_entities([entity], True)


# ─── TVRemote Entity ───────────────────────────────────────────────────────────

class TVRemote(RemoteEntity):
    """
    Remote entity that sends HAP commands directly to the TV but derives its
    state (on/off and current input) from the HomeKit Controller media_player
    entity — no HAP polling or push subscription.

    State source:
      The HomeKit Controller media_player (hk_entity_id) is listened to via
      async_track_state_change_event. On each change:
        - state string → is_on (True if "on", False otherwise)
        - attributes.source looked up in attributes.source_list:
          identifier = source_list.index(source) + 1  (1-based)
          → self._current_identifier (integer)

    Entity ID: remote.<slug> (derived from tv_name in __init__.py)
    Attributes: current_source, current_identifier, last_hap_error

    Commands accepted by async_send_command():
      - Integer strings: "4" "5" "6" "7" "8" "9" "11" etc. → RemoteKey
      - "volume_up" / "vol_up"   → VolumeSelector = 0
      - "volume_down" / "vol_down" → VolumeSelector = 1
      - "mute"                    → toggle Mute characteristic (or VolumeSelector=2)
      - "input_N" / "hdmi_N"      → ActiveIdentifier = N
    """

    _attr_should_poll = False
    _attr_assumed_state = False

    def __init__(self, hass, uid, conn, rk, act, vol, inp, mut,
                 debug_listen, debug_send, config_entry, hk_entity_id):
        """Store all HAP characteristic tuples and initialize state."""
        self.hass = hass
        self._attr_unique_id = uid
        self._attr_name = config_entry.data.get("tv_name", "Homekit TV")
        self._attr_device_info = {
            "identifiers": {("homekit_tv_remote", uid)},
            "name": config_entry.data.get("tv_name", "Homekit TV"),
            "manufacturer": "Anthropic",
            "model": "HomeKit TV Remote Control",
        }
        # HAP connection and characteristic (aid, iid) tuples
        self._conn = conn   # homekit_controller connection object
        self._rk = rk       # RemoteKey characteristic
        self._act = act     # Active characteristic (write only — on/off)
        self._vol = vol     # VolumeSelector characteristic
        self._inp = inp     # ActiveIdentifier characteristic (write only — input switch)
        self._mut = mut     # Mute characteristic

        # HK Controller media_player entity ID to listen to for state + source
        self._hk_entity_id = hk_entity_id

        # State
        self._attr_is_on = True             # Assumed on until first HK entity read
        self._current_identifier = None     # Integer derived from source_list position

        # Debug flags — flipped live by DebugListenSwitch / DebugSendSwitch
        self._debug_listen = debug_listen
        self._debug_send = debug_send

        self._config_entry = config_entry
        self._last_error_status = None      # Last HAP error code (shown in attributes)

        # Lock prevents concurrent non-RemoteKey commands (volume, mute, input switch)
        self._command_lock = asyncio.Lock()

    # ─── Debug Logging Helpers ─────────────────────────────────────────────────

    def _log_listen(self, message, *args):
        """Log a listen/receive event. Only logs if _debug_listen is True."""
        if self._debug_listen:
            _LOGGER.warning(f"[{DEBUG_LISTEN}] {message}", *args)

    def _log_send(self, message, *args):
        """Log a send/command event. Only logs if _debug_send is True."""
        if self._debug_send:
            _LOGGER.warning(f"[{DEBUG_SEND}] {message}", *args)

    # ─── HAP Error Handling ────────────────────────────────────────────────────

    def _handle_hap_error(self, error: Exception, operation: str) -> None:
        """
        Classify a HAP exception by matching error string patterns against
        known HAP status codes, set self._last_error_status, and log appropriately.
        Called from all put_characteristics / get_characteristics try/except blocks.
        """
        error_str = str(error).lower()

        if "timeout" in error_str or "-70408" in error_str:
            self._last_error_status = HAP_STATUS_OPERATION_TIMED_OUT
            _LOGGER.error("HAP timeout during %s - TV may be sleeping or unreachable", operation)
        elif "busy" in error_str or "-70403" in error_str:
            self._last_error_status = HAP_STATUS_RESOURCE_BUSY
            _LOGGER.warning("HAP busy during %s - TV is processing another request", operation)
        elif "communication" in error_str or "-70402" in error_str:
            self._last_error_status = HAP_STATUS_SERVICE_COMMUNICATION_FAILURE
            _LOGGER.error("HAP communication failure during %s - check network", operation)
        elif "not supported" in error_str or "-70406" in error_str:
            self._last_error_status = HAP_STATUS_NOTIFICATION_NOT_SUPPORTED
            _LOGGER.error("HAP operation not supported: %s", operation)
        elif "invalid" in error_str or "-70410" in error_str:
            self._last_error_status = HAP_STATUS_INVALID_VALUE
            _LOGGER.error("HAP invalid value during %s", operation)
        elif "does not exist" in error_str or "-70409" in error_str:
            self._last_error_status = HAP_STATUS_RESOURCE_DOES_NOT_EXIST
            _LOGGER.error("HAP resource does not exist: %s", operation)
        else:
            _LOGGER.error("HAP error during %s: %s", operation, error)

    # ─── HA Entity Properties ──────────────────────────────────────────────────

    @property
    def is_on(self):
        """Return on/off state (updated by _update_from_hk_state)."""
        return self._attr_is_on

    @property
    def extra_state_attributes(self):
        """
        Expose source info and diagnostics as entity attributes.

        current_source:     User's custom name for the active input (from custom_inputs),
                            or "Input N" if no custom name is saved for this identifier.
        current_identifier: Integer derived from source_list position (1-based).
        last_hap_error:     Last HAP error code (only present when an error occurred).

        current_source and current_identifier are read by:
          - media_player.py (remote_state_changed callback) to update self._source
          - text.py (CurrentIdentifierTextEntity) to display the current input
        """
        source = None
        if self._current_identifier is not None:
            source = self._get_source_name_for_identifier(self._current_identifier)

        attrs = {
            "current_source": source,
            "current_identifier": self._current_identifier,
        }

        if self._last_error_status is not None:
            attrs["last_hap_error"] = self._last_error_status

        return attrs

    # ─── HK Entity State Listener ──────────────────────────────────────────────

    async def async_added_to_hass(self):
        """
        Subscribe to HomeKit Controller media_player state changes.
        Reads current state immediately so entity reflects reality on startup.
        No HAP polling or push subscription is set up here.
        """

        @callback
        def hk_state_changed(event):
            """Called whenever the HK Controller media_player changes state."""
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            self._update_from_hk_state(new_state)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._hk_entity_id, hk_state_changed
            )
        )

        # Immediate read on startup
        hk_state = self.hass.states.get(self._hk_entity_id)
        if hk_state:
            self._update_from_hk_state(hk_state)
            self.async_write_ha_state()

    def _update_from_hk_state(self, hk_state) -> None:
        """
        Extract on/off state and current input identifier from a HK Controller
        media_player state object.

        Power state:
          "on"  → is_on = True
          anything else (off, standby, unavailable) → is_on = False

        Identifier:
          source_list is 1-based: identifier = source_list.index(source) + 1
          e.g. source_list = ["TV", "HDMI 1", ..., "Apple TV", ...]
               source = "Apple TV" at position 8 (1-based) → identifier = 8
          If source or source_list is absent (TV unavailable), identifier
          is left unchanged.
        """
        # ── Power state ────────────────────────────────────────────────────────
        new_is_on = hk_state.state == "on"
        if new_is_on != self._attr_is_on:
            self._attr_is_on = new_is_on
            self._log_listen(
                "Power state updated from HK entity: %s", "ON" if new_is_on else "OFF"
            )
            self.async_write_ha_state()

        # ── Current input identifier ───────────────────────────────────────────
        source = hk_state.attributes.get("source")
        source_list = hk_state.attributes.get("source_list", [])

        if source and source_list:
            try:
                # 1-based: first item in list = identifier 1
                identifier = source_list.index(source) + 1
                if identifier != self._current_identifier:
                    self._current_identifier = identifier
                    self._log_listen(
                        "Input updated from HK entity: '%s' → input_%s",
                        source, identifier
                    )
                    self.async_write_ha_state()
            except ValueError:
                # source not found in source_list — should not happen in normal operation
                _LOGGER.warning(
                    "remote.py: source '%s' not found in source_list, identifier unchanged",
                    source
                )

    # ─── Source Name Resolution ────────────────────────────────────────────────

    def _get_source_name_for_identifier(self, identifier):
        """
        Resolve a HAP identifier integer to the user's custom name from custom_inputs.

        Matching rules:
          - hap inputs: parses identifier from command string e.g. "input_9" → 9
          - remote / media_player / media_player_source inputs: matches the
            explicit "identifier" field saved when the user configured the input

        Falls back to "Input N" if no custom_inputs entry matches.
        No raw HK source name is used here.
        """
        custom_inputs = self._config_entry.options.get("custom_inputs", [])

        for inp in custom_inputs:
            command = inp.get("command", "")
            command_type = inp.get("command_type", "")

            if command_type == "hap" and (command.startswith("input_") or command.startswith("hdmi_")):
                try:
                    input_num = int(command.split("_")[1])
                    if input_num == identifier:
                        return inp["name"]
                except (ValueError, IndexError):
                    pass
            elif command_type in ("remote", "media_player", "media_player_source"):
                explicit_id = inp.get("identifier")
                if explicit_id is not None and int(explicit_id) == identifier:
                    return inp["name"]

        return f"Input {identifier}"

    # ─── Power Control ─────────────────────────────────────────────────────────

    async def async_turn_on(self, **_):
        """Turn TV on by writing Active=1 to the Active characteristic."""
        if self._act:
            try:
                self._log_send("Turning TV ON (Active=1)")
                await self._conn.put_characteristics([(self._act[0], self._act[1], 1)])
                self._attr_is_on = True
                self._last_error_status = HAP_STATUS_SUCCESS
                self.async_write_ha_state()
            except Exception as e:
                self._handle_hap_error(e, "turn on")

    async def async_turn_off(self, **_):
        """Turn TV off by writing Active=0 to the Active characteristic."""
        if self._act:
            try:
                self._log_send("Turning TV OFF (Active=0)")
                await self._conn.put_characteristics([(self._act[0], self._act[1], 0)])
                self._attr_is_on = False
                self._last_error_status = HAP_STATUS_SUCCESS
                self.async_write_ha_state()
            except Exception as e:
                self._handle_hap_error(e, "turn off")

    # ─── Button Press ──────────────────────────────────────────────────────────

    async def _send_button_press(self, button_value: int, hold_time: float = 0) -> bool:
        """Send a RemoteKey press. Fire and forget for instant presses — no waiting
        for TV acknowledgement so rapid presses don't queue behind each other.
        Hold presses still await completion since timing matters."""
        try:
            if hold_time > 0:
                self._log_send("Pressing button %s (hold for %.1fs)", button_value, hold_time)
                await self._conn.put_characteristics([(self._rk[0], self._rk[1], button_value)])
                await asyncio.sleep(hold_time)
            else:
                self._log_send("Sending RemoteKey: %s", button_value)
                # Fire and forget — don't await acknowledgement from TV.
                # TCP ordering guarantees the TV receives rapid presses in sequence.
                asyncio.ensure_future(
                    self._conn.put_characteristics([(self._rk[0], self._rk[1], button_value)])
                )
            self._last_error_status = HAP_STATUS_SUCCESS
            return True
        except Exception as e:
            self._handle_hap_error(e, f"button press {button_value}")
            return False

    # ─── Command Dispatch ──────────────────────────────────────────────────────

    async def async_send_command(self, command: Iterable[str], **kw) -> None:
        """HA service handler for remote.send_command.
        Pure RemoteKey integer commands skip the lock — they fire and forget
        so rapid D-pad/back/play presses don't queue.
        All other commands (volume, mute, input switch) keep the lock."""
        cmds = list(command)
        # Skip lock only for single pure integer commands (RemoteKey presses)
        if len(cmds) == 1 and not kw.get("hold_secs", 0):
            try:
                int(cmds[0])
                # It's a plain integer — fire directly without lock
                await self._send_command_internal(cmds, **kw)
                return
            except (ValueError, TypeError):
                pass
        # All other commands go through the lock
        async with self._command_lock:
            await self._send_command_internal(cmds, **kw)

    async def _send_command_internal(self, command: Iterable[str], **kw) -> None:
        """
        Parse and dispatch a list of command strings.

        Supported command formats:
          "4" .. "16"            → RemoteKey integer (HAP navigation keys)
          "volume_up"/"vol_up"   → VolumeSelector = 0
          "volume_down"/"vol_down" → VolumeSelector = 1
          "mute"                 → toggle Mute char; fallback to VolumeSelector=2
          "input_N"/"hdmi_N"     → ActiveIdentifier = N (switch TV input)

        kwargs:
          delay_secs: float — delay between commands when sending multiple (default 0.05s)
          hold_secs:  float — hold time for button press (default 0 = instant)

        Called with lock already held by async_send_command (except plain int commands).
        """
        delay = kw.get("delay_secs", 0.05)   # 50ms between multiple commands
        hold_time = kw.get("hold_secs", 0)    # 0 = instant press
        cmds = list(command)
        n = len(cmds)
        put = self._conn.put_characteristics   # Shorthand for repeated calls

        for i, cmd in enumerate(cmds):
            c = cmd.lower() if isinstance(cmd, str) else str(cmd)
            success = False

            # ── Try integer first → RemoteKey ──────────────────────────────────
            try:
                key_value = int(c)
                success = await self._send_button_press(key_value, hold_time)
            except ValueError:
                # Not an integer — check named commands
                try:
                    # ── Volume ─────────────────────────────────────────────────
                    if self._vol and c in ("volume_up", "vol_up"):
                        self._log_send("Sending Volume Up")
                        await put([(self._vol[0], self._vol[1], 0)])  # 0 = VolumeUp
                        success = True
                    elif self._vol and c in ("volume_down", "vol_down"):
                        self._log_send("Sending Volume Down")
                        await put([(self._vol[0], self._vol[1], 1)])  # 1 = VolumeDown
                        success = True

                    # ── Mute ───────────────────────────────────────────────────
                    elif c == "mute":
                        if self._mut:
                            # Read current mute state then toggle
                            self._log_send("Sending Mute Toggle via MUTE characteristic")
                            result = await self._conn.get_characteristics(
                                [(self._mut[0], self._mut[1])]
                            )
                            current = result.get((self._mut[0], self._mut[1]), {}).get("value", False)
                            await put([(self._mut[0], self._mut[1], not current)])
                            success = True
                        elif self._vol:
                            # Non-standard fallback: some TVs accept VolumeSelector=2 as mute
                            self._log_send("Sending Mute via VolumeSelector fallback")
                            await put([(self._vol[0], self._vol[1], 2)])
                            success = True
                        else:
                            _LOGGER.warning(
                                "Mute requested but no MUTE or VolumeSelector characteristic found"
                            )

                    # ── Input Switch ───────────────────────────────────────────
                    elif self._inp and (c.startswith('input_') or c.startswith('hdmi_')):
                        # Parse "input_9" → 9, "hdmi_3" → 3
                        try:
                            input_num = int(c.split("_")[1])
                            source_name = self._get_source_name_for_identifier(input_num)
                            self._log_send("Switching to input %s (%s)", input_num, source_name)
                            await put([(self._inp[0], self._inp[1], input_num)])
                            success = True
                        except Exception as e:
                            self._handle_hap_error(e, f"input switch to {c}")

                except Exception as e:
                    self._handle_hap_error(e, f"command {c}")

            # ── Inter-command delay ────────────────────────────────────────────
            # Only delays when sending multiple commands, and only after success
            if success and n > 1 and i < n - 1:
                await asyncio.sleep(delay)
