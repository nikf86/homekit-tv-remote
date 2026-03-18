"""Remote platform for HomeKit TV Remote - HAP communication layer."""
# Version: 1.1.0
#
# ROLE IN INTEGRATION:
# This is the core HAP (HomeKit Accessory Protocol) communication layer.
# It connects DIRECTLY to the Sony TV via the existing homekit_controller pairing,
# bypassing the homekit_controller integration's own entities entirely.
#
# On setup it:
#   1. Looks up the homekit_controller connection object for the paired TV
#   2. Scans the TV's accessory characteristic list for the 5 key characteristics:
#      RemoteKey, Active, VolumeSelector, ActiveIdentifier, Mute
#   3. Creates remote.homekit_tv (TVRemote entity)
#
# At runtime it:
#   - Polls ActiveIdentifier (current input) + Active (on/off) every 2-5 seconds
#   - Optionally subscribes to push notifications if the TV supports them
#   - Exposes current_source and current_identifier as state attributes
#     (read by media_player.py and text.py to display the current input)
#   - Sends all HAP commands (RemoteKey, Volume, Mute, Input switch) via
#     put_characteristics on the raw connection
#
# Dependencies:
#   - Requires homekit_controller to be set up and paired with the TV
#   - hass.data["homekit_tv_remote"][entry_id]["remote_entity_ref"] is set here
#     so that switch.py can flip _debug_listen/_debug_send flags without a reload

import asyncio
from typing import Any, Iterable

from aiohomekit.model.characteristics import CharacteristicsTypes as CT

from datetime import timedelta

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_registry as er
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "homekit_tv_remote"

# Prefixes used in warning-level debug log lines so they can be grep'd
DEBUG_LISTEN = "HOMEKIT_TV_LISTEN"  # Logs about receiving/reading data from TV
DEBUG_SEND = "HOMEKIT_TV_SEND"      # Logs about sending commands to TV

# ─── HAP Error Status Codes ────────────────────────────────────────────────────
# These are standard HAP protocol error codes returned by the TV accessory.
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
# These are the integer values written to the RemoteKey characteristic.
# Sent as integers via put_characteristics, or as strings ("4", "9" etc.)
# via async_send_command which parses them with int().
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
    1. Look up the homekit_controller media_player entity that was selected
       during config flow (stored in entry.data["media_player_entity_id"])
    2. Find the homekit_controller connection (device) that owns that entity
    3. Walk the TV's accessory/service/characteristic tree to find the 5
       characteristics we need: RemoteKey, Active, VolumeSelector,
       ActiveIdentifier, Mute — stored as (aid, iid) tuples for fast access
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
                    act = (aid, c.iid)         # Read/Write: 1=on, 0=standby
                elif not vol and t == CT.VOLUME_SELECTOR:
                    vol = (aid, c.iid)         # Write: 0=up, 1=down (2=mute on some TVs)
                elif not inp and t == CT.ACTIVE_IDENTIFIER:
                    inp = (aid, c.iid)         # Read/Write: current input index
                elif not mut and t == CT.MUTE:
                    mut = (aid, c.iid)         # Read/Write: bool mute state

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
        hass, entry.entry_id, entry.title, conn, rk, act, vol, inp, mut,
        debug_listen, debug_send, entry
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
    Remote entity that communicates directly with the Sony TV via HAP.

    Entity ID: remote.homekit_tv (hardcoded via unique_id = entry.entry_id)
    State:     on/off (polled from Active characteristic)
    Attributes: current_source, current_identifier, subscription_active,
                change_reason, last_hap_error
    
    Commands accepted by async_send_command():
      - Integer strings: "4" "5" "6" "7" "8" "9" "11" etc. → RemoteKey
      - "volume_up" / "vol_up"   → VolumeSelector = 0
      - "volume_down" / "vol_down" → VolumeSelector = 1
      - "mute"                    → toggle Mute characteristic (or VolumeSelector=2)
      - "input_N" / "hdmi_N"      → ActiveIdentifier = N
    """

    _attr_should_poll = False   # We do our own polling via async_track_time_interval
    _attr_assumed_state = False  # State is confirmed by polling Active characteristic every 2-5s

    def __init__(self, hass, uid, name, conn, rk, act, vol, inp, mut,
                 debug_listen, debug_send, config_entry):
        """Store all HAP characteristic tuples and initialize state."""
        self.hass = hass
        self._attr_unique_id = uid          # entry.entry_id → entity id: remote.homekit_tv
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
        self._act = act     # Active characteristic (on/off)
        self._vol = vol     # VolumeSelector characteristic
        self._inp = inp     # ActiveIdentifier characteristic (current input)
        self._mut = mut     # Mute characteristic

        # State
        self._attr_is_on = True             # Assumed on until first poll
        self._current_identifier = None     # Current TV input index (int)

        # Debug flags — flipped live by DebugListenSwitch / DebugSendSwitch
        self._debug_listen = debug_listen
        self._debug_send = debug_send

        self._config_entry = config_entry
        self._subscription_active = False   # Whether push subscription succeeded
        self._change_reason = None          # "POLL" or "EVENT" — how last update arrived
        self._last_error_status = None      # Last HAP error code (shown in attributes)

        # Lock prevents two commands running concurrently (e.g. rapid button presses)
        self._command_lock = asyncio.Lock()

    # ─── Debug Logging Helpers ─────────────────────────────────────────────────

    def _log_listen(self, message, *args):
        """
        Log a receive/listen event at WARNING level (so it appears without debug mode).
        Only logs if _debug_listen is True (toggled by DebugListenSwitch in switch.py).
        """
        if self._debug_listen:
            _LOGGER.warning(f"[{DEBUG_LISTEN}] {message}", *args)

    def _log_send(self, message, *args):
        """
        Log a send/command event at WARNING level.
        Only logs if _debug_send is True (toggled by DebugSendSwitch in switch.py).
        """
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
        """Return on/off state (updated by _poll_active_identifier via Active char)."""
        return self._attr_is_on

    @property
    def extra_state_attributes(self):
        """
        Expose diagnostic and source info as entity attributes.
        
        current_source:      Friendly name of the active TV input (from custom_inputs)
        current_identifier:  Raw integer from ActiveIdentifier HAP characteristic
        subscription_active: Whether push notification subscription succeeded
        change_reason:       "POLL" or "EVENT" — how the last update was received
        last_hap_error:      Last HAP error code (only present when an error occurred)
        
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
            "subscription_active": self._subscription_active,
            "change_reason": self._change_reason,
        }

        if self._last_error_status is not None:
            attrs["last_hap_error"] = self._last_error_status

        return attrs

    # ─── Subscription and Polling ──────────────────────────────────────────────

    async def async_added_to_hass(self):
        """
        Called by HA once the entity is registered.

        1. Do an immediate poll to get the current input and power state
        2. Attempt a single native push subscription via _try_native_subscription().
           If the TV/connection supports it, the callback updates state immediately
           on input change without waiting for the next poll.
        3. Always set up a polling fallback timer regardless of subscription result
           - 5s interval if subscription succeeded (subscription is primary)
           - 2s interval if subscription failed (polling is the only mechanism)
        """
        if not self._inp:
            # No ActiveIdentifier characteristic found — polling impossible
            return

        # Immediate initial read so entity shows correct state right away
        await self._poll_active_identifier()

        # Attempt push subscription via native aiohomekit callback.
        # Falls back to polling timer below if not supported.
        try:
            if await self._try_native_subscription():
                self._subscription_active = True
                self._log_listen("Successfully subscribed to ActiveIdentifier push notifications")
            else:
                self._log_listen("Native subscription not supported, using polling fallback")
        except Exception as e:
            self._log_listen("Native subscription failed, using polling fallback: %s", e)

        # Always register polling timer as safety net
        poll_interval = timedelta(seconds=5) if self._subscription_active else timedelta(seconds=2)
        self.async_on_remove(
            async_track_time_interval(self.hass, self._poll_active_identifier, poll_interval)
        )

    async def _try_native_subscription(self) -> bool:
        """
        Attempt to subscribe to ActiveIdentifier push notifications via
        the homekit_controller connection's subscribe_characteristics method.
        
        If the connection also supports add_char_subscription_callback, registers
        a callback that updates _current_identifier immediately when the TV
        sends a notification (e.g. user changes input via TV remote).
        
        Returns True if subscription + callback registration succeeded.
        Returns False if the connection does not support subscribe_characteristics
        or add_char_subscription_callback.
        """
        if not hasattr(self._conn, 'subscribe_characteristics'):
            return False

        await self._conn.subscribe_characteristics([(self._inp[0], self._inp[1])])

        if hasattr(self._conn, 'add_char_subscription_callback'):
            @callback
            def characteristic_changed(char_changes):
                """
                Callback fired by aiohomekit when a subscribed characteristic changes.
                char_changes: dict of {(aid, iid): value_or_dict}
                """
                for (aid, iid), data in char_changes.items():
                    if (aid, iid) == self._inp:
                        # data may be a raw value or a dict with "value" and "reason"
                        if isinstance(data, dict):
                            new_value = data.get("value")
                            self._change_reason = data.get("reason", "EVENT")
                        else:
                            new_value = data
                            self._change_reason = "EVENT"

                        if new_value is not None and new_value != self._current_identifier:
                            self._current_identifier = new_value
                            source_name = self._get_source_name_for_identifier(new_value)
                            self._log_listen(
                                "ActiveIdentifier changed via subscription: %s → %s (reason: %s)",
                                new_value, source_name, self._change_reason
                            )
                            self.async_write_ha_state()

            self._conn.add_char_subscription_callback(characteristic_changed)
            return True

        return False

    async def _poll_active_identifier(self, now=None):
        """
        Read ActiveIdentifier (current input) and Active (on/off) from the TV via HAP.
        Called on a timer (every 2s or 5s) and once immediately on startup.
        
        Only calls async_write_ha_state() if a value actually changed,
        to avoid unnecessary state updates.
        
        now: passed by async_track_time_interval, ignored (signature required by HA).
        """
        try:
            # Build list of chars to read in a single get_characteristics call
            chars_to_read = [(self._inp[0], self._inp[1])]
            if self._act:
                chars_to_read.append((self._act[0], self._act[1]))

            result = await self._conn.get_characteristics(chars_to_read)

            # ── Update current input (ActiveIdentifier) ────────────────────────
            value = result.get((self._inp[0], self._inp[1]), {}).get("value")
            if value is not None and value != self._current_identifier:
                self._current_identifier = value
                self._change_reason = "POLL"
                source_name = self._get_source_name_for_identifier(value)
                self._log_listen(
                    "ActiveIdentifier updated via poll: %s → %s", value, source_name
                )
                self.async_write_ha_state()

            # ── Update power state (Active) ────────────────────────────────────
            if self._act:
                active_value = result.get((self._act[0], self._act[1]), {}).get("value")
                if active_value is not None:
                    new_state = bool(active_value)
                    if new_state != self._attr_is_on:
                        self._attr_is_on = new_state
                        self._log_listen(
                            "Active state updated via poll: %s", "ON" if new_state else "OFF"
                        )
                        self.async_write_ha_state()

        except Exception as e:
            self._handle_hap_error(e, "poll Active/ActiveIdentifier")

    # ─── Source Name Resolution ────────────────────────────────────────────────

    def _get_source_name_for_identifier(self, identifier):
        """
        Resolve an ActiveIdentifier integer to a friendly source name.
        
        Looks through custom_inputs (saved by the user via button.py) and matches:
          - hap inputs:   parses the number from command like "input_9" → 9
          - remote/media_player inputs: matches the explicit "identifier" field
            saved when the user filled in the HAP Identifier field in text.py
        
        Falls back to "Input N" if no match found.
        
        Called by extra_state_attributes, _poll_active_identifier, and
        the push subscription callback.
        """
        custom_inputs = self._config_entry.options.get("custom_inputs", [])

        for inp in custom_inputs:
            command = inp.get("command", "")
            command_type = inp.get("command_type", "")

            if command_type == "hap" and (command.startswith("input_") or command.startswith("hdmi_")):
                # Extract integer from "input_9" → 9
                try:
                    input_num = int(command.split("_")[1])
                    if input_num == identifier:
                        return inp["name"]
                except (ValueError, IndexError):
                    pass
            elif command_type in ("remote", "media_player"):
                # Match via explicit identifier field set by user
                explicit_id = inp.get("identifier")
                if explicit_id is not None and int(explicit_id) == identifier:
                    return inp["name"]

        return f"Input {identifier}"

    # ─── Power Control ─────────────────────────────────────────────────────────

    async def async_turn_on(self, **_):
        """
        Turn TV on by writing Active=1 to the Active characteristic.
        Updates local state optimistically on success.
        """
        if self._act:
            try:
                self._log_send("Turning TV ON (Active=1)")
                await self._conn.put_characteristics([(self._act[0], self._act[1], 1)])
                self._attr_is_on = True
                self._last_error_status = HAP_STATUS_SUCCESS
            except Exception as e:
                self._handle_hap_error(e, "turn on")

    async def async_turn_off(self, **_):
        """
        Turn TV off by writing Active=0 to the Active characteristic.
        Updates local state optimistically on success.
        """
        if self._act:
            try:
                self._log_send("Turning TV OFF (Active=0)")
                await self._conn.put_characteristics([(self._act[0], self._act[1], 0)])
                self._attr_is_on = False
                self._last_error_status = HAP_STATUS_SUCCESS
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
          "4" .. "16"          → RemoteKey integer (HAP navigation keys)
          "volume_up"/"vol_up" → VolumeSelector = 0
          "volume_down"/"vol_down" → VolumeSelector = 1
          "mute"               → toggle Mute char; fallback to VolumeSelector=2
          "input_N"/"hdmi_N"   → ActiveIdentifier = N (switch TV input)
        
        kwargs:
          delay_secs: float — delay between commands when sending multiple (default 0.05s)
          hold_secs:  float — hold time for button press (default 0 = instant)
        
        Called with lock already held by async_send_command.
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
                            # Read current state then toggle (true mute toggle)
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
