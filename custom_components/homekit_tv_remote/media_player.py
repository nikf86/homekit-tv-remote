"""Media player — the entity you expose to HomeKit Bridge."""
# Version: 2.1.0
#
# WHAT THIS FILE IS RESPONSIBLE FOR
#   Being the TV that Apple Home sees. Expose this entity to HomeKit Bridge in
#   accessory mode and iOS gives you the Control Center remote widget. Every
#   button on that widget arrives here as a homekit_tv_remote_key_pressed event
#   and is translated into a HAP command.
#
#   It also owns the input list: source_list, select_source, and the input cycle
#   behind the widget's ⓘ Info button.
#
# WHAT CHANGED FROM 1.5.1
# - State and current input come straight from the HomeKit Device entity. 1.x
#   went HomeKit Device → remote entity attributes → here, so the same fact was
#   copied twice and could disagree with itself mid-update. One listener now.
# - state is a MediaPlayerState, not a raw string copied from another entity.
# - The Include-switch layer is gone. options["inputs"] is the list; if an input
#   is in it, it is in Apple Home and in the cycle. One list, one meaning.
# - The Apple TV special case is gone. Whether a media_player target needs
#   select_source or play_media is decided by looking at that entity's own
#   source_list at the moment the input runs, so it is right for Apple TV,
#   Bravia, or anything else without the user flagging it.
# - Input cycling starts from the input that is actually active rather than from
#   a free-running counter, so ⓘ always moves one step from where you are.
# - Volume, power and playback call the remote entity directly instead of going
#   back out through hass.services. Same effect, one layer less.

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import HomeKitTVConfigEntry
from .const import (
    ATTR_KEY_NAME,
    BRIDGE_KEY_MAP,
    CONF_HK_ENTITY,
    CONF_TV_NAME,
    DOMAIN,
    EVENT_HOMEKIT_KEY,
    IN_ACTION,
    IN_NAME,
    IN_SOURCE,
    IN_SOURCE_ID,
    IN_TARGET,
    KEY_PLAY_PAUSE,
    OPT_INPUTS,
)

_LOGGER = logging.getLogger(__name__)

# HomeKit Device entity state → our state.
# "standby" maps to OFF, not to MediaPlayerState.STANDBY: that enum member is
# deprecated and removed in HA Core 2026.8.0.
HK_STATE_MAP: dict[str, MediaPlayerState] = {
    "on": MediaPlayerState.ON,
    "off": MediaPlayerState.OFF,
    "standby": MediaPlayerState.OFF,
    "idle": MediaPlayerState.IDLE,
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "buffering": MediaPlayerState.BUFFERING,
}

# How long after the last cycle step we go back to trusting the TV's reported
# input as the starting point. Inside this window the counter wins, because a
# TV that is still switching still reports the old input.
CYCLE_RESYNC_SECONDS = 4.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeKitTVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the media player that HomeKit Bridge will publish."""
    hk_entity_id = entry.data.get(CONF_HK_ENTITY)
    if not hk_entity_id:
        return

    entity = HomeKitTVMediaPlayer(hass, entry, hk_entity_id)
    entry.runtime_data.media_ref = entity
    async_add_entities([entity])


class HomeKitTVMediaPlayer(MediaPlayerEntity):
    """The TV as Apple Home sees it."""

    _attr_should_poll = False
    _attr_has_entity_name = False       # this entity IS the device
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
    )

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeKitTVConfigEntry,
        hk_entity_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._hk_entity_id = hk_entity_id

        tv_name = entry.data.get(CONF_TV_NAME, "Homekit TV")
        self.entity_id = entry.runtime_data.media_entity_id
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._attr_name = tv_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=tv_name,
            manufacturer="HomeKit TV Remote",
            model="HAP Television Remote",
        )

        self._state = MediaPlayerState.OFF
        self._tv_source: str | None = None    # raw HomeKit input name
        self._cycle_index = 0
        self._last_cycle = 0.0                # loop clock of the last cycle step

        # HAP does volume in steps, not levels. A non-None dummy level is what
        # keeps the volume controls visible in the HA media card; without it the
        # card hides them entirely.
        self._attr_volume_level = 0.5
        self._attr_is_volume_muted = False

    # ─── Inputs ────────────────────────────────────────────────────────────────

    @property
    def _inputs(self) -> list[dict[str, Any]]:
        """The configured input list, read live so edits apply on reload."""
        return list(self._entry.options.get(OPT_INPUTS, []))

    @property
    def source_list(self) -> list[str]:
        return [item[IN_NAME] for item in self._inputs if item.get(IN_NAME)]

    @property
    def source(self) -> str | None:
        """Our name for whatever input the TV is actually on.

        Returns None rather than the raw HomeKit name when the active input is
        not one the user configured — a source that is not in source_list
        confuses both the HA media card and Apple Home. The raw name is always
        available as the tv_source attribute.
        """
        if self._tv_source is None:
            return None
        identifier = self._entry.runtime_data.tv_inputs.get(self._tv_source)
        for item in self._inputs:
            if item.get(IN_SOURCE) == self._tv_source:
                return item[IN_NAME]
            if identifier is not None and item.get(IN_SOURCE_ID) == identifier:
                return item[IN_NAME]
        return None

    @property
    def state(self) -> MediaPlayerState:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"tv_source": self._tv_source}

    # ─── Subscriptions ─────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Follow the HomeKit Device entity, and listen for widget presses."""

        @callback
        def hk_changed(event) -> None:
            new_state = event.data.get("new_state")
            if new_state is not None:
                self._apply_hk_state(new_state)

        self.async_on_remove(
            async_track_state_change_event(self.hass, self._hk_entity_id, hk_changed)
        )

        @callback
        def key_pressed(event) -> None:
            """Handle one press on the iOS Control Center remote widget."""
            if event.data.get("entity_id") != self.entity_id:
                return
            key_name = event.data.get(ATTR_KEY_NAME, "")

            if key_name == "information":
                # ⓘ is the input cycler — that is the whole trick that makes the
                # widget useful, since Apple gives no other input control there.
                self.hass.async_create_task(self.async_cycle_input())
            elif (key := BRIDGE_KEY_MAP.get(key_name)) is not None:
                self.hass.async_create_task(self._press(key))
            else:
                _LOGGER.debug("Unhandled HomeKit key: %s", key_name)

        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_HOMEKIT_KEY, key_pressed)
        )

        if (state := self.hass.states.get(self._hk_entity_id)) is not None:
            self._apply_hk_state(state, write=False)

    @callback
    def _apply_hk_state(self, hk_state, write: bool = True) -> None:
        """Copy state and current input across from the HomeKit Device entity."""
        raw = hk_state.state
        if raw in (STATE_UNAVAILABLE, STATE_UNKNOWN, None):
            new_state = MediaPlayerState.OFF
        else:
            new_state = HK_STATE_MAP.get(raw, MediaPlayerState.ON)
        if raw == STATE_OFF:
            new_state = MediaPlayerState.OFF

        source = hk_state.attributes.get("source")

        if new_state != self._state or source != self._tv_source:
            self._state = new_state
            self._tv_source = source
            if write:
                self.async_write_ha_state()

    # ─── Access to the remote entity ───────────────────────────────────────────

    @property
    def _remote(self):
        """The TVRemote instance. None only if the remote platform failed."""
        return self._entry.runtime_data.remote_ref

    async def _press(self, key: int) -> None:
        if (remote := self._remote) is not None:
            await remote._press(key)

    # ─── Power, volume, playback ───────────────────────────────────────────────

    async def async_turn_on(self) -> None:
        if (remote := self._remote) is not None:
            await remote.async_turn_on()

    async def async_turn_off(self) -> None:
        if (remote := self._remote) is not None:
            await remote.async_turn_off()

    async def async_volume_up(self) -> None:
        if (remote := self._remote) is not None:
            await remote.async_send_command(["volume_up"])

    async def async_volume_down(self) -> None:
        if (remote := self._remote) is not None:
            await remote.async_send_command(["volume_down"])

    async def async_mute_volume(self, mute: bool) -> None:
        """Apple Home sends an explicit on/off here, so pass it straight down."""
        if (remote := self._remote) is not None:
            await remote.async_set_mute(mute)
            self._attr_is_volume_muted = mute
            self.async_write_ha_state()

    async def async_media_play(self) -> None:
        await self._press(KEY_PLAY_PAUSE)

    async def async_media_pause(self) -> None:
        await self._press(KEY_PLAY_PAUSE)

    async def async_media_stop(self) -> None:
        await self._press(KEY_PLAY_PAUSE)

    # ─── Source selection ──────────────────────────────────────────────────────

    async def async_select_source(self, source: str) -> None:
        for item in self._inputs:
            if item.get(IN_NAME) == source:
                await self.async_run_input(item)
                return
        _LOGGER.error("No configured input named '%s'", source)

    async def async_run_input(
        self, item: dict[str, Any], *, blocking: bool = False
    ) -> None:
        """Execute one configured input. The single place this logic lives.

        blocking controls only the call into the *other* integration. It is False
        for anything user-facing, because waiting on it is what made the ⓘ button
        and Next input feel dead: media_player.select_source on an Apple TV does
        not return until the app has actually launched, several seconds later,
        and until then every caller up the chain is stuck. Home Assistant runs
        the service either way — blocking only decides whether we wait for it.

        The options flow's Test box passes blocking=True, because there the whole
        point is to find out whether the call raised.

        Three shapes, decided by what the input has rather than by a flag the
        user had to set:

          no target                 → switch the TV's own input over HAP
          target + a TV input       → switch the TV's input first, then act
          target, no TV input       → just act

        For a media_player target, the action is a source name if that entity
        lists it in its own source_list (Apple TV apps, Bravia apps), otherwise
        it is treated as media content. That check is what replaced the two
        Apple TV switches.
        """
        name = item.get(IN_NAME, "?")
        target: str = item.get(IN_TARGET) or ""
        action: str = item.get(IN_ACTION) or ""

        identifier = self._identifier_for(item)
        if identifier is not None:
            if (remote := self._remote) is not None:
                await remote.async_select_input(identifier)
            if not target:
                return
        elif not target:
            _LOGGER.error(
                "Input '%s' has no TV input and no target — nothing to run. "
                "Known TV inputs: %s",
                name,
                ", ".join(self._entry.runtime_data.tv_inputs) or "none discovered",
            )
            return

        if not action:
            _LOGGER.error("Input '%s' targets %s but has no action", name, target)
            return

        domain = target.split(".")[0]

        if domain == "remote":
            await self.hass.services.async_call(
                "remote",
                "send_command",
                {"entity_id": target, "command": action},
                blocking=blocking,
            )
            return

        if domain == "media_player":
            target_state = self.hass.states.get(target)
            sources = (target_state.attributes.get("source_list") or []) if target_state else []
            if action in sources:
                await self.hass.services.async_call(
                    "media_player",
                    "select_source",
                    {"entity_id": target, "source": action},
                    blocking=blocking,
                )
            else:
                if sources:
                    _LOGGER.debug(
                        "'%s' is not in %s source_list — using play_media",
                        action,
                        target,
                    )
                await self.hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": target,
                        "media_content_id": action,
                        "media_content_type": "app",
                    },
                    blocking=blocking,
                )
            return

        _LOGGER.error("Input '%s' has an unsupported target: %s", name, target)

    def _identifier_for(self, item: dict[str, Any]) -> int | None:
        """HAP identifier for an input's TV source, by name or legacy number."""
        if source := item.get(IN_SOURCE):
            identifier = self._entry.runtime_data.tv_inputs.get(source)
            if identifier is None and (remote := self._remote) is not None:
                identifier = remote.identifier_for_source(source)
            if identifier is None:
                _LOGGER.warning(
                    "Input '%s' refers to TV input '%s', which this TV no longer "
                    "reports. Re-pick it under Configure → TV inputs",
                    item.get(IN_NAME),
                    source,
                )
            return identifier
        # Migrated from 1.x, where the identifier was typed in by hand.
        raw = item.get(IN_SOURCE_ID)
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    # ─── Input cycling (ⓘ Info button and the Next Input button) ───────────────

    async def async_cycle_input(self) -> None:
        """Advance one step through the configured inputs.

        Returns as soon as the next input has been chosen. The command itself is
        dispatched as a background task, so pressing ⓘ or Next input twice in a
        row always moves two steps, immediately, no matter how slow the thing on
        the other end is.

        This is the fix for the lockup. Before, the whole chain — HomeKit key
        event, or the button.press service call — awaited async_run_input, which
        awaited a blocking media_player.select_source on the Apple TV. An app
        launch takes several seconds, and for that whole window Next input sat
        disabled in the UI and further ⓘ presses did nothing visible. It came
        back on its own once the call returned, which is exactly the "annoying,
        clears after a few seconds" behaviour.

        Where the cycle starts from:
          After a quiet period, from whichever input is actually active, so the
          cycle follows the TV even when the input was changed by its own remote,
          an automation, or wake-on-HDMI.
          While cycling, from our own counter. Re-reading the live input during
          rapid presses would read the input we have not switched away from yet
          and hand back the same target twice, which looks like a stuck button.
        """
        inputs = self._inputs
        if not inputs:
            _LOGGER.warning(
                "No inputs configured — add some under Configure → TV inputs"
            )
            return

        now = self.hass.loop.time()
        if now - self._last_cycle > CYCLE_RESYNC_SECONDS:
            current = self.source
            if current is not None:
                for index, item in enumerate(inputs):
                    if item.get(IN_NAME) == current:
                        self._cycle_index = index
                        break
        self._last_cycle = now

        self._cycle_index = (self._cycle_index + 1) % len(inputs)
        target = inputs[self._cycle_index]
        _LOGGER.info(
            "Cycling to %s (%s/%s)",
            target.get(IN_NAME),
            self._cycle_index + 1,
            len(inputs),
        )

        self._entry.async_create_background_task(
            self.hass,
            self.async_run_input(target),
            f"{DOMAIN} run input {target.get(IN_NAME)}",
        )
