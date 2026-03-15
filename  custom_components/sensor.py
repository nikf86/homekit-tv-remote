"""Sensor entities — one per saved custom input."""
# Version: 1.0.0
#
# ROLE IN INTEGRATION:
# Creates one SensorEntity per entry in config_entry.options["custom_inputs"].
# These sensors are purely for visibility — they let the user see their saved
# inputs in the HA device page without clicking into the integration.
#
# Entity naming:  "Input 1", "Input 2", etc. (index-based display name)
# Entity state:   "Apple TV (input_9)[hap]"
#                 "Portal TV CEC (remote.bravia.Hdmi2)[6]"
#                 Format: "{name} ({command})[{identifier or command_type}]"
# Entity attributes: index, command_type, command (full detail for inspection)
#
# Unique IDs are slug-based on the input NAME (not index) so renaming the
# same input triggers a new entity rather than silently updating the old one,
# but deleting an input removes exactly that entity.
#
# Orphan cleanup:
#   On every reload, async_setup_entry computes the set of valid unique_ids
#   from the current custom_inputs list and removes any sensor entities
#   from the registry that are no longer in that set. This ensures deleted
#   inputs don't leave "Unavailable" ghost entities in the device page.

import re
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

DOMAIN = "homekit_tv_remote"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """
    Convert an input name to a safe unique_id suffix.
    Replaces any non-alphanumeric characters with underscores and strips
    leading/trailing underscores.
    Example: "HDMI2 (Portal TV)" → "hdmi2_portal_tv"
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _format_state(inp: dict) -> str:
    """
    Format the sensor state string for a saved input.
    
    For hap inputs (no explicit identifier):
        "Apple TV (input_9)[hap]"
    For remote/media_player inputs (with HAP identifier integer):
        "Portal TV CEC (remote.bravia_kd_55xg9505.Hdmi2)[6]"
    
    bracket shows the identifier integer if available, otherwise command_type.
    This fits within HA's 255-character state limit for all reasonable input names.
    """
    name = inp.get("name", "")
    cmd = inp.get("command", "")
    cmd_type = inp.get("command_type", "")
    identifier = inp.get("identifier", "")   # Integer (remote/media_player) or "" (hap)
    bracket = str(identifier) if identifier != "" else cmd_type
    return f"{name} ({cmd})[{bracket}]"


# ─── Platform Setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Called on every reload. Two steps:

    1. Orphan cleanup: compare registered sensor entity unique_ids against the
       current custom_inputs list and remove any that are no longer valid.
       This handles the case where the user deleted an input — after reload,
       the old sensor would otherwise sit as "Unavailable" in the registry.

    2. Entity creation: create one SavedInputSensor per current custom_input.
    """
    inputs = entry.options.get("custom_inputs", [])

    # ── Step 1: Compute valid unique_ids for the current input list ────────────
    valid_unique_ids = {
        f"{entry.entry_id}_input_{_slug(inp.get('name', ''))}"
        for inp in inputs
    }

    # ── Step 2: Remove orphaned sensor entities from the entity registry ───────
    # Iterates all registered entities, finds sensors belonging to this config
    # entry whose unique_id is no longer valid, and removes them from the registry.
    # HA will then remove them from the state machine automatically.
    registry = er.async_get(hass)
    for entity_entry in list(registry.entities.values()):
        if (
            entity_entry.config_entry_id == entry.entry_id
            and entity_entry.domain == "sensor"
            and entity_entry.unique_id not in valid_unique_ids
        ):
            registry.async_remove(entity_entry.entity_id)

    # ── Step 3: Create sensors for current inputs ──────────────────────────────
    entities = [
        SavedInputSensor(hass, entry, inp, i + 1)
        for i, inp in enumerate(inputs)
    ]
    if entities:
        async_add_entities(entities)


# ─── SavedInputSensor ──────────────────────────────────────────────────────────

class SavedInputSensor(SensorEntity):
    """
    Read-only sensor representing one saved custom input.

    Entity name:  "Input N" (N = 1-based index in custom_inputs list)
    Entity state: formatted string (see _format_state)
    Attributes:   index, command_type, command

    State is set once at __init__ and never updated — the sensor is recreated
    on every reload (which happens whenever inputs are added or deleted).
    Polling is disabled since the state never changes between reloads.
    """

    _attr_should_poll = False       # State is static between reloads
    _attr_icon = "mdi:television-play"

    def __init__(self, hass, config_entry, inp: dict, index: int):
        """
        inp:   the custom_input dict (name, command_type, command, optional identifier)
        index: 1-based position in the custom_inputs list (for display name)
        """
        self.hass = hass
        self._config_entry = config_entry
        self._inp = inp
        self._index = index
        name = inp.get("name", "")
        # Unique ID is slug of the name so renaming creates a new entity
        self._attr_unique_id = f"{config_entry.entry_id}_input_{_slug(name)}"
        # Display name uses index only — full detail is in the state string
        self._attr_name = f"Input {index}"
        # State is the formatted summary string
        self._attr_native_value = _format_state(inp)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }

    @property
    def extra_state_attributes(self):
        """
        Expose full input detail as attributes for inspection.
        Attributes have no 255-character limit, so full command strings
        (which may exceed 255 chars) are safe to store here.
        """
        return {
            "index": self._index,
            "command_type": self._inp.get("command_type", ""),
            "command": self._inp.get("command", ""),
        }
