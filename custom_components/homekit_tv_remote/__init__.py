"""HomeKit TV Remote — integration entry point."""
# Version: 1.0.3

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
    """'Sony KD-55' → 'sony_kd_55' — matches HA entity ID slug rules."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load all platforms. Derive entity IDs from tv_name and store in hass.data
    so every platform file uses the same IDs regardless of what name was chosen."""
    tv_name = entry.data.get("tv_name", "Homekit TV")
    slug = _slugify(tv_name)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "remote_entity": f"remote.{slug}",
        "media_player_entity": f"media_player.{slug}",
        # remote.py adds:   "remote_entity_ref"      → TVRemote instance
        # media_player.py adds: "media_player_entity_ref" → HomeKitTVMediaPlayer instance
        # select.py adds:   "input_type"             → InputTypeSelectEntity instance
        # text.py adds:     "text_entities"          → {key: ConfigTextEntity} dict
        # switch.py adds:   "apple_tv_switch"        → AppleTVAppSwitch instance
        #                   "apple_tv_input_switch"  → AppleTVInputSwitch instance
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload all platforms and clean up shared data."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
