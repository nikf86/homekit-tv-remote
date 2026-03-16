"""One read-only sensor per saved input — shows the saved input list on the device page."""
# Version: 1.0.0

import re
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

DOMAIN = "homekit_tv_remote"


def _slug(name: str) -> str:
    """'Apple TV (HDMI4)' → 'apple_tv_hdmi4' — safe unique_id suffix."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _state(inp: dict) -> str:
    """Format: 'Apple TV (input_9)[hap]' or 'Portal TV (remote.bravia.Hdmi2)[6]'."""
    bracket = str(inp.get("identifier", "")) or inp.get("command_type", "")
    return f"{inp.get('name','')} ({inp.get('command','')})[{bracket}]"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Rebuild sensor list on every reload. Remove orphans for deleted inputs first."""
    inputs = entry.options.get("custom_inputs", [])
    valid_ids = {f"{entry.entry_id}_input_{_slug(i.get('name',''))}" for i in inputs}

    registry = er.async_get(hass)
    for e in list(registry.entities.values()):
        if (e.config_entry_id == entry.entry_id
                and e.domain == "sensor"
                and e.unique_id not in valid_ids):
            registry.async_remove(e.entity_id)

    if inputs:
        async_add_entities([
            SavedInputSensor(hass, entry, inp, i + 1)
            for i, inp in enumerate(inputs)
        ])


class SavedInputSensor(SensorEntity):
    """Read-only sensor for one saved input. State = formatted summary string.
    Recreated on every reload — state never changes between reloads."""

    _attr_should_poll = False
    _attr_icon = "mdi:television-play"

    def __init__(self, hass, config_entry, inp: dict, index: int):
        self._inp = inp
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_input_{_slug(inp.get('name',''))}"
        self._attr_name = f"Input {index}"
        self._attr_native_value = _state(inp)
        self._attr_device_info = {"identifiers": {(DOMAIN, config_entry.entry_id)}}

    @property
    def extra_state_attributes(self):
        return {
            "index": self._index,
            "command_type": self._inp.get("command_type", ""),
            "command": self._inp.get("command", ""),
        }
