"""Remote platform — the HAP command layer."""
# Version: 2.4.0
#
# WHAT THIS FILE IS RESPONSIBLE FOR
#   Sending. Every command that reaches the TV goes out from here, written
#   straight onto HAP characteristics over the pairing homekit_controller
#   already maintains. That is the fast path and it is deliberately kept.
#
# WHAT THIS FILE NO LONGER DOES
#   Asking. 1.2.x already dropped the polling loop and the push subscription,
#   but three queries were still left:
#     - "mute" did a get_characteristics round-trip to read the current mute
#       state before toggling it. Gone — mute is tracked locally and written
#       explicitly, so it is one write instead of a read plus a write.
#     - the current input was reconstructed as source_list.index(source) + 1.
#       That is a guess. HomeKit input identifiers are arbitrary integers, not
#       positions (see homekit_controller/media_player.py, which matches on the
#       IDENTIFIER characteristic). On a TV that numbers its inputs 3, 7, 12 the
#       old maths was silently wrong.
#     - is_on was `state == "on"`, so a TV reporting "playing" or "paused"
#       registered as OFF.
#   All three are fixed by reading the HomeKit Device media_player entity that
#   is already in Home Assistant's state machine, plus the accessory metadata
#   homekit_controller holds in memory. Neither costs a single packet.
#
# THE INPUT NAME → IDENTIFIER MAP
#   Built once at setup by walking the INPUT_SOURCE services linked to the TV's
#   TELEVISION service and reading their CONFIGURED_NAME and IDENTIFIER
#   characteristics. This is what removes the "1e. HAP Identifier" field the
#   user used to have to look up and type. Published on runtime_data so the
#   options flow and media_player.py can use it.
#   If the accessory tree cannot be walked for any reason, the map falls back to
#   source_list position + 1 — the old 1.x behaviour — so nothing breaks.

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from aiohomekit.model.characteristics import CharacteristicsTypes as CT
from aiohomekit.model.services import ServicesTypes as ST
from homeassistant.components.remote import RemoteEntity
from homeassistant.const import (
    STATE_OFF,
    STATE_STANDBY,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import HomeKitTVConfigEntry
from .const import (
    COMMAND_ALIASES,
    CONF_HK_ENTITY,
    CONF_TV_NAME,
    DEBUG_LISTEN,
    DEBUG_SEND,
    DOMAIN,
    HKC_DEVICES,
    OPT_DEBUG_LISTEN,
    OPT_DEBUG_SEND,
    VOLUME_DOWN,
    VOLUME_MUTE_FALLBACK,
    VOLUME_UP,
)

_LOGGER = logging.getLogger(__name__)

# States of the HomeKit Device entity that mean "the TV is not on".
# Everything else — on, playing, paused, idle, buffering — counts as on.
#
# 2.4.0: unavailable and unknown are NOT in this set any more. They mean the
# connection dropped, which is not the same as the TV being off, and Sony sets
# drop their HAP session routinely. Treating a blip as OFF made this entity —
# and the media_player beside it — flap, which in turn made HomeKit Bridge
# write Active = 0 and iOS hide the D-pad. See _apply_hk_state.
OFF_STATES = {STATE_OFF, STATE_STANDBY}

# States that mean "we do not currently know", handled separately.
UNKNOWN_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN, None}

# HAP status codes, used to classify errors for the last_hap_error attribute.
HAP_SUCCESS = 0
HAP_UNKNOWN_ERROR = -1   # a failure we could not classify — still a failure
HAP_ERRORS: dict[str, int] = {
    "timeout": -70408,
    "-70408": -70408,
    "busy": -70403,
    "-70403": -70403,
    "communication": -70402,
    "-70402": -70402,
    "not supported": -70406,
    "-70406": -70406,
    "invalid": -70410,
    "-70410": -70410,
    "does not exist": -70409,
    "-70409": -70409,
}


# ─── Accessory discovery ───────────────────────────────────────────────────────


@dataclass
class TVAccessory:
    """The handful of (aid, iid) pairs and the name→identifier map we need."""

    remote_key: tuple[int, int] | None = None
    active: tuple[int, int] | None = None
    volume: tuple[int, int] | None = None
    active_identifier: tuple[int, int] | None = None
    mute: tuple[int, int] | None = None
    inputs: dict[str, int] | None = None   # {"Apple TV": 8, ...}


def _char(service, aid: int, char_type: str) -> tuple[int, int] | None:
    """Return (aid, iid) for a characteristic on a service, or None."""
    if service is not None and service.has(char_type):
        return (aid, service[char_type].iid)
    return None


def _discover(conn: Any, hk_unique_id: str | None) -> TVAccessory:
    """Locate the TELEVISION service and everything hanging off it.

    Preferred route: homekit_controller's media_player unique_id is
    "<pairing id>_<aid>_<service iid>", which points straight at the TELEVISION
    service. That gives an exact match with no scanning.

    Fallback route: walk every accessory and take the first of each
    characteristic we find — this is what 1.x did. It is kept because the
    unique_id format belongs to another integration and could change.
    """
    found = TVAccessory()

    entity_map = (
        getattr(conn, "entity_map", None)
        or getattr(conn, "accessories", None)
        or getattr(getattr(conn, "pairing", None), "accessories", None)
    )
    if entity_map is None:
        _LOGGER.error("No accessory map on the homekit_controller connection")
        return found

    # ── Preferred: resolve the exact TELEVISION service ────────────────────────
    tv_service = None
    accessory = None
    if hk_unique_id:
        parts = hk_unique_id.split("_")
        if len(parts) >= 3:
            try:
                aid, sid = int(parts[-2]), int(parts[-1])
                accessory = entity_map.aid(aid)
                candidate = accessory.services.iid(sid)
                if candidate is not None and candidate.type == ST.TELEVISION:
                    tv_service = candidate
            except (ValueError, KeyError, AttributeError):
                tv_service = None
                accessory = None

    # ── Still nothing? Find the first TELEVISION service anywhere ──────────────
    accessories = getattr(entity_map, "accessories", entity_map)
    if tv_service is None:
        for acc in accessories:
            candidate = acc.services.first(service_type=ST.TELEVISION)
            if candidate is not None:
                accessory, tv_service = acc, candidate
                break

    if tv_service is not None and accessory is not None:
        aid = accessory.aid
        found.remote_key = _char(tv_service, aid, CT.REMOTE_KEY)
        found.active = _char(tv_service, aid, CT.ACTIVE)
        found.active_identifier = _char(tv_service, aid, CT.ACTIVE_IDENTIFIER)

        # Volume and mute live on the linked speaker service, not the TV service.
        for service in accessory.services.filter(parent_service=tv_service):
            if found.volume is None:
                found.volume = _char(service, aid, CT.VOLUME_SELECTOR)
            if found.mute is None:
                found.mute = _char(service, aid, CT.MUTE)
        # Some accessories do not link the speaker — sweep the whole accessory.
        for service in accessory.services:
            if found.volume is None:
                found.volume = _char(service, aid, CT.VOLUME_SELECTOR)
            if found.mute is None:
                found.mute = _char(service, aid, CT.MUTE)

        # Real input identifiers, straight from the accessory description.
        inputs: dict[str, int] = {}
        for source in accessory.services.filter(
            service_type=ST.INPUT_SOURCE, parent_service=tv_service
        ):
            name = source.value(CT.CONFIGURED_NAME) or source.value(CT.NAME)
            identifier = source.value(CT.IDENTIFIER)
            if name and identifier is not None:
                inputs[str(name)] = int(identifier)
        if inputs:
            found.inputs = inputs

    # ── Last resort: the 1.x brute-force scan ──────────────────────────────────
    if found.remote_key is None:
        for acc in accessories:
            for service in acc.services:
                for char in service.characteristics:
                    pair = (acc.aid, char.iid)
                    if found.remote_key is None and char.type == CT.REMOTE_KEY:
                        found.remote_key = pair
                    elif found.active is None and char.type == CT.ACTIVE:
                        found.active = pair
                    elif found.volume is None and char.type == CT.VOLUME_SELECTOR:
                        found.volume = pair
                    elif (
                        found.active_identifier is None
                        and char.type == CT.ACTIVE_IDENTIFIER
                    ):
                        found.active_identifier = pair
                    elif found.mute is None and char.type == CT.MUTE:
                        found.mute = pair

    return found


# ─── Platform setup ────────────────────────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitTVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Find the paired TV, discover its characteristics, create the entity."""
    hk_entity_id = entry.data.get(CONF_HK_ENTITY)
    if not hk_entity_id:
        _LOGGER.error("No HomeKit Device entity stored in the config entry")
        return

    registry_entry = er.async_get(hass).async_get(hk_entity_id)
    if registry_entry is None:
        _LOGGER.error("HomeKit Device entity %s is not in the registry", hk_entity_id)
        return

    conn = None
    for device in hass.data.get(HKC_DEVICES, {}).values():
        owner = getattr(getattr(device, "config_entry", None), "entry_id", None)
        if owner == registry_entry.config_entry_id:
            conn = device
            break

    if conn is None:
        _LOGGER.error(
            "No homekit_controller connection owns %s — is the TV still paired?",
            hk_entity_id,
        )
        return

    accessory = _discover(conn, registry_entry.unique_id)

    if accessory.remote_key is None:
        _LOGGER.error(
            "This accessory exposes no RemoteKey characteristic — it cannot be "
            "driven as a TV remote"
        )
        return

    # Publish the input map so media_player.py and the options flow can use it.
    if accessory.inputs:
        entry.runtime_data.tv_inputs = accessory.inputs
        _LOGGER.debug("TV inputs discovered from HAP: %s", accessory.inputs)
    else:
        # Fallback: derive from the HomeKit Device entity's source_list, using
        # position + 1 the way 1.x did. Less exact but better than nothing.
        state = hass.states.get(hk_entity_id)
        source_list = (state.attributes.get("source_list") or []) if state else []
        entry.runtime_data.tv_inputs = {
            name: index + 1 for index, name in enumerate(source_list)
        }
        _LOGGER.warning(
            "Could not read input identifiers from the accessory; falling back "
            "to source_list order. Input switching may pick the wrong input if "
            "your TV does not number its inputs 1..N"
        )

    entity = TVRemote(hass, entry, conn, accessory, hk_entity_id)
    entry.runtime_data.remote_ref = entity
    async_add_entities([entity])


# ─── TVRemote ──────────────────────────────────────────────────────────────────


class TVRemote(RemoteEntity):
    """Sends HAP commands. Reads its state from the HomeKit Device entity.

    Accepted remote.send_command values
      raw integers      "4" "8" "9" "11" …  written to RemoteKey as-is
      named keys        up, down, left, right, select/ok, back, exit,
                        play_pause, rewind, fast_forward, next_track,
                        previous_track, info, home, settings
      volume            volume_up / volume_down / vol_up / vol_down
      mute              mute (toggle), mute_on, mute_off
      inputs            input_9 / hdmi_9      by HAP identifier
                        input:Apple TV        by name (resolved from the map)
    """

    _attr_should_poll = False
    _attr_assumed_state = False
    _attr_has_entity_name = False   # this entity IS the device

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeKitTVConfigEntry,
        conn: Any,
        accessory: TVAccessory,
        hk_entity_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._conn = conn
        self._acc = accessory
        self._hk_entity_id = hk_entity_id

        tv_name = entry.data.get(CONF_TV_NAME, "Homekit TV")
        self.entity_id = entry.runtime_data.remote_entity_id
        self._attr_unique_id = entry.entry_id      # unchanged from 1.x
        self._attr_name = tv_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=tv_name,
            manufacturer="HomeKit TV Remote",
            model="HAP Television Remote",
        )

        self._attr_is_on = False
        self._current_source: str | None = None     # raw HomeKit input name
        self._muted = False                         # optimistic, see async_mute
        self._last_error: int | None = None

        self._debug_listen = entry.options.get(OPT_DEBUG_LISTEN, False)
        self._debug_send = entry.options.get(OPT_DEBUG_SEND, False)

        # Paces multi-command sequences only. Single commands bypass it — see
        # async_send_command.
        self._lock = asyncio.Lock()

        # Every characteristic write goes through one queue drained by one
        # worker. Callers never wait on the wire, but writes still reach the TV
        # in the order they were made.
        #
        # 2.3.x fired a separate background task per press. That returned fast
        # but gave no ordering — rapid taps raced each other onto the connection
        # and could land reordered — and the try/except around task *creation*
        # never saw an exception raised inside the task, so a failed write was
        # silently recorded as a success.
        self._queue: asyncio.Queue[tuple[tuple[int, int], Any, str]] = asyncio.Queue()
        self._sender_task: asyncio.Task | None = None

    # ─── Logging ───────────────────────────────────────────────────────────────

    def _log_listen(self, message: str, *args: Any) -> None:
        if self._debug_listen:
            _LOGGER.warning("[%s] " + message, DEBUG_LISTEN, *args)

    def _log_send(self, message: str, *args: Any) -> None:
        if self._debug_send:
            _LOGGER.warning("[%s] " + message, DEBUG_SEND, *args)

    def _handle_error(self, error: Exception, operation: str) -> None:
        """Classify a HAP exception and record it on the entity."""
        text = str(error).lower()
        for needle, code in HAP_ERRORS.items():
            if needle in text:
                self._last_error = code
                _LOGGER.error("HAP %s during %s: %s", code, operation, error)
                return
        # Unrecognised, but still a failure. None would drop last_hap_error from
        # the attributes entirely, making an error look like nothing happened.
        self._last_error = HAP_UNKNOWN_ERROR
        _LOGGER.error("HAP error during %s: %s", operation, error)

    # ─── Properties ────────────────────────────────────────────────────────────

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "current_source": self._current_source,
            "is_muted": self._muted,
            "tv_inputs": self._entry.runtime_data.tv_inputs,
        }
        if self._last_error is not None:
            attrs["last_hap_error"] = self._last_error
        return attrs

    # ─── State: mirrored from the HomeKit Device entity ────────────────────────

    async def async_added_to_hass(self) -> None:
        """Follow the HomeKit Device entity. No polling, no subscription."""

        @callback
        def hk_changed(event) -> None:
            new_state = event.data.get("new_state")
            if new_state is not None:
                self._apply_hk_state(new_state)

        self.async_on_remove(
            async_track_state_change_event(self.hass, self._hk_entity_id, hk_changed)
        )

        # One worker drains the write queue for the life of the entity.
        self._ensure_sender()

        if (state := self.hass.states.get(self._hk_entity_id)) is not None:
            self._apply_hk_state(state, write=False)

    async def async_will_remove_from_hass(self) -> None:
        """Stop the sender so it does not outlive the entity."""
        if self._sender_task is not None:
            self._sender_task.cancel()
            self._sender_task = None

    # ─── The single write path ─────────────────────────────────────────────────

    async def _sender(self) -> None:
        """Drain the write queue, one write at a time, in order.

        This is the only place put_characteristics is called for user-facing
        commands. Errors are handled here because there is no caller left to
        raise into by the time the write actually happens.
        """
        while True:
            target, value, operation = await self._queue.get()
            try:
                await self._conn.put_characteristics([(*target, value)])
                self._last_error = HAP_SUCCESS
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 — aiohomekit raises many types
                self._handle_error(err, operation)
            finally:
                self._queue.task_done()

    def _ensure_sender(self) -> None:
        """Start the sender if it is not already running.

        Called from _write rather than only from async_added_to_hass. A queue
        with no worker swallows every command silently, which is the same class
        of failure the queue was introduced to remove — so the worker is started
        on demand and restarted if it ever dies.
        """
        if self._sender_task is not None and not self._sender_task.done():
            return
        self._sender_task = self._entry.async_create_background_task(
            self.hass, self._sender(), f"{DOMAIN} sender"
        )

    def _write(self, target: tuple[int, int] | None, value: Any, operation: str) -> bool:
        """Queue one characteristic write. Returns immediately."""
        if target is None:
            return False
        self._ensure_sender()
        self._queue.put_nowait((target, value, operation))
        return True

    @callback
    def _apply_hk_state(self, hk_state, write: bool = True) -> None:
        """Copy power and current input across from the HomeKit Device entity.

        Power: anything other than off/standby counts as on, so a TV reporting
        "playing" or "paused" is correctly on. 1.x compared against the literal
        string "on" and got this wrong.

        Unreachable is not off. When the HomeKit Device entity goes unavailable
        or unknown we hold whatever we last knew rather than asserting OFF, and
        we leave the input alone — the source attribute is absent during a blip,
        and treating that as "the TV moved" is wrong.
        """
        if hk_state.state in UNKNOWN_STATES:
            self._log_listen("HomeKit Device unreachable — holding last state")
            return

        changed = False

        is_on = hk_state.state not in OFF_STATES
        if is_on != self._attr_is_on:
            self._attr_is_on = is_on
            self._log_listen("Power from HomeKit Device: %s", "ON" if is_on else "OFF")
            changed = True

        source = hk_state.attributes.get("source")
        if source != self._current_source:
            self._current_source = source
            self._log_listen("Input from HomeKit Device: %s", source)
            changed = True

        if changed and write:
            self.async_write_ha_state()

    # ─── Power ─────────────────────────────────────────────────────────────────

    async def async_turn_on(self, **_: Any) -> None:
        await self._write_active(1, "turn on")

    async def async_turn_off(self, **_: Any) -> None:
        await self._write_active(0, "turn off")

    async def _write_active(self, value: int, operation: str) -> None:
        if self._acc.active is None:
            _LOGGER.warning("TV exposes no Active characteristic — cannot %s", operation)
            return
        try:
            self._log_send("Active = %s", value)
            await self._conn.put_characteristics([(*self._acc.active, value)])
            self._last_error = HAP_SUCCESS
            # Optimistic. The HomeKit Device entity corrects us within a second.
            self._attr_is_on = bool(value)
            self.async_write_ha_state()
        except Exception as err:  # noqa: BLE001 — aiohomekit raises many types
            self._handle_error(err, operation)

    # ─── Input switching ───────────────────────────────────────────────────────

    async def async_select_input(self, identifier: int) -> bool:
        """Write ActiveIdentifier. Called by media_player.py."""
        if self._acc.active_identifier is None:
            _LOGGER.warning("TV exposes no ActiveIdentifier — cannot switch inputs")
            return False
        try:
            self._log_send("ActiveIdentifier = %s", identifier)
            await self._conn.put_characteristics(
                [(*self._acc.active_identifier, identifier)]
            )
            self._last_error = HAP_SUCCESS
            return True
        except Exception as err:  # noqa: BLE001
            self._handle_error(err, f"input switch to {identifier}")
            return False

    def identifier_for_source(self, name: str) -> int | None:
        """Resolve an input name to its HAP identifier, case-insensitively."""
        inputs = self._entry.runtime_data.tv_inputs
        if name in inputs:
            return inputs[name]
        folded = name.casefold()
        for key, value in inputs.items():
            if key.casefold() == folded:
                return value
        return None

    # ─── Volume and mute ───────────────────────────────────────────────────────

    async def async_set_mute(self, mute: bool) -> None:
        """Queue an explicit mute state — no read-back round trip.

        The HomeKit Device entity does not expose mute, so this value is
        optimistic: it is what we last told the TV, not what the TV reports.
        Use mute_on / mute_off rather than mute in automations if you need the
        result to be deterministic.

        The flag is set here, on the caller's stack, rather than in the sender.
        That keeps a rapid mute_on / mute_off pair in the order it was issued
        even though the writes are dispatched asynchronously.
        """
        if self._acc.mute is not None:
            target, value = self._acc.mute, mute
            self._log_send("Mute = %s", mute)
        elif self._acc.volume is not None:
            # Non-standard, but some TVs read VolumeSelector 2 as mute.
            target, value = self._acc.volume, VOLUME_MUTE_FALLBACK
            self._log_send("Mute via VolumeSelector fallback")
        else:
            _LOGGER.warning("TV exposes neither Mute nor VolumeSelector")
            return

        self._muted = mute
        self.async_write_ha_state()
        self._write(target, value, "mute")

    async def _write_volume(self, direction: int) -> None:
        if self._acc.volume is None:
            _LOGGER.warning("TV exposes no VolumeSelector characteristic")
            return
        self._log_send("VolumeSelector = %s", direction)
        self._write(self._acc.volume, direction, "volume")

    # ─── Button presses ────────────────────────────────────────────────────────

    async def _press(self, key: int, **_: Any) -> None:
        """Queue a RemoteKey write.

        Returns as soon as the press is queued, so rapid D-pad taps never wait
        on the wire — but the queue preserves order, so five arrows arrive as
        five arrows in the order they were pressed.

        hold_secs is accepted and ignored. HAP's RemoteKey characteristic is a
        single write of an enum value: there is no press/release pair and no
        duration, so there is nothing underneath it to hold. 2.3.x slept locally
        for the duration, which delayed the caller and never reached the TV, and
        as a side effect pushed the press off the fast path.
        """
        if self._acc.remote_key is None:
            _LOGGER.warning("TV exposes no RemoteKey characteristic")
            return
        self._log_send("RemoteKey %s", key)
        self._write(self._acc.remote_key, key, f"button press {key}")

    # ─── Command dispatch ──────────────────────────────────────────────────────

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Handler for remote.send_command."""
        commands = [str(item) for item in command]
        hold_secs = float(kwargs.get("hold_secs", 0) or 0)
        if hold_secs:
            _LOGGER.debug(
                "hold_secs is ignored: HomeKit's RemoteKey characteristic has no "
                "press-and-hold. Use delay_secs to pace a sequence"
            )
        delay_secs = float(kwargs.get("delay_secs", 0.05) or 0)

        # Nothing in the key / volume / mute path waits on the wire any more —
        # they queue and return — so the lock's only remaining job is pacing a
        # multi-command sequence. A single command skips it entirely.
        #
        # hold_secs no longer disqualifies the fast path, because it no longer
        # does anything (see _press).
        if len(commands) == 1:
            await self._dispatch(commands[0], hold_secs)
            return

        async with self._lock:
            for index, raw in enumerate(commands):
                await self._dispatch(raw, hold_secs)
                if delay_secs and index < len(commands) - 1:
                    await asyncio.sleep(delay_secs)

    @staticmethod
    def _as_key(raw: str) -> int | None:
        """Return the RemoteKey integer for a command, or None if it isn't one."""
        text = raw.strip().lower()
        if text.lstrip("-").isdigit():
            return int(text)
        return COMMAND_ALIASES.get(text)

    async def _dispatch(self, raw: str, hold_secs: float) -> None:
        """Route one command string."""
        text = raw.strip()
        lowered = text.lower()

        if (key := self._as_key(text)) is not None:
            await self._press(key)
            return

        if lowered in ("volume_up", "vol_up"):
            await self._write_volume(VOLUME_UP)
            return
        if lowered in ("volume_down", "vol_down"):
            await self._write_volume(VOLUME_DOWN)
            return

        if lowered == "mute":
            await self.async_set_mute(not self._muted)
            return
        if lowered == "mute_on":
            await self.async_set_mute(True)
            return
        if lowered == "mute_off":
            await self.async_set_mute(False)
            return

        # "input:Apple TV" — switch by name, resolved through the input map.
        if lowered.startswith("input:"):
            name = text.split(":", 1)[1].strip()
            identifier = self.identifier_for_source(name)
            if identifier is None:
                _LOGGER.error(
                    "Unknown input '%s'. Known inputs: %s",
                    name,
                    ", ".join(self._entry.runtime_data.tv_inputs) or "none discovered",
                )
                return
            await self.async_select_input(identifier)
            return

        # "input_9" / "hdmi_9" — switch by HAP identifier.
        if lowered.startswith(("input_", "hdmi_")):
            _, _, number = lowered.partition("_")
            if number.isdigit():
                await self.async_select_input(int(number))
                return

        _LOGGER.error("Unknown command: %s", raw)
