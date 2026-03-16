"""HomeKit TV Remote integration."""
# Version: 1.0.2
#
# CHANGES FROM 1.0.1:
# - async_reload_entry now skips reload when only homekit_inputs, debug_listen,
#   or debug_send change. Previously any options write (including toggling an
#   Include switch) triggered a full reload, which recreated all switch instances
#   with fresh empty options and immediately wiped the homekit_inputs write.
#   Now only custom_inputs changes (inputs added/deleted) trigger a reload.
#
# CHANGES FROM 1.0.0:
# - Added _slugify() helper to derive entity IDs from tv_name at runtime
# - Stores "remote_entity" and "media_player_entity" in hass.data so all
#   platforms reference the correct entity IDs regardless of the tv_name
#   chosen during setup. Previously these were hardcoded to "remote.homekit_tv"
#   and "media_player.homekit_tv", which broke when any other name was used.

import re
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "homekit_tv_remote"

PLATFORMS = [
    Platform.REMOTE,
    Platform.MEDIA_PLAYER,
    Platform.BUTTON,
    Platform.TEXT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def _slugify(name: str) -> str:
    """
    Convert a tv_name string to the slug HA uses for entity IDs.
    HA replaces non-alphanumeric characters with underscores and lowercases.
    Example: "Sony KD-55" → "sony_kd_55"
    Example: "Homekit TV"  → "homekit_tv"
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Called by HA for YAML-based setup (legacy). No-op — config entries only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Called by HA when a config entry is loaded (on HA start or after reload).

    Derives remote and media_player entity IDs from tv_name and stores them
    in hass.data so all platform files use consistent, correct entity IDs.
    """
    _LOGGER.debug("Setting up HomeKit TV Remote integration")

    tv_name = entry.data.get("tv_name", "Homekit TV")
    slug = _slugify(tv_name)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        # Derived from tv_name — used by media_player.py, button.py, text.py
        "remote_entity": f"remote.{slug}",
        "media_player_entity": f"media_player.{slug}",
        # remote.py will add:  "remote_entity_ref" → TVRemote instance
        # select.py will add:  "input_type"        → InputTypeSelectEntity instance
        # text.py will add:    "text_entities"     → {key: ConfigTextEntity} dict
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unloads all platform entities and cleans up the shared data store."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Called automatically whenever config_entry.options change.

    Only reloads when custom_inputs changes (inputs added or deleted).
    Skips reload for homekit_inputs, debug_listen, debug_send — those are
    handled live without a reload. Without this guard, toggling an Include
    switch triggers a full reload which recreates all switch instances with
    fresh empty options, wiping the homekit_inputs write immediately after
    it is saved.
    """
    prev = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("last_custom_inputs")
    current = entry.options.get("custom_inputs", [])

    if prev is not None and prev == current:
        return

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["last_custom_inputs"] = current

    await hass.config_entries.async_reload(entry.entry_id)
