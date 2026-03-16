"""HomeKit TV Remote integration."""
# Version: 1.0.3
#
# 1.0.0 — Initial release. Loads all platforms, registers async_reload_entry listener.
#
# 1.0.1 — Added _slugify() helper. Stores remote_entity and media_player_entity
#         in hass.data derived from tv_name so all platforms use correct entity
#         IDs regardless of the name chosen during setup.
#
# 1.0.2 — Attempted to guard async_reload_entry against non-custom_inputs writes.
#         Did not work reliably due to race conditions.
#
# 1.0.3 — Removed the update listener entirely. The listener fired on every
#         async_update_entry call including Include switch toggles and debug
#         switches, causing a full reload that wiped homekit_inputs immediately
#         after it was written. Reloads are now triggered explicitly by button.py
#         after saving or deleting inputs — the only operations that actually
#         require a reload.

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

    No update listener is registered — reloads are triggered explicitly by
    button.py after saving or deleting inputs.
    """
    _LOGGER.debug("Setting up HomeKit TV Remote integration")

    tv_name = entry.data.get("tv_name", "Homekit TV")
    slug = _slugify(tv_name)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "remote_entity": f"remote.{slug}",
        "media_player_entity": f"media_player.{slug}",
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unloads all platform entities and cleans up the shared data store."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
