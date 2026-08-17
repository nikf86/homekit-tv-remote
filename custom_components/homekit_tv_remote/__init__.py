"""HomeKit TV Remote — integration entry point."""
# Version: 2.1.1
#
# WHAT CHANGED FROM 1.0.3
# - Config entry schema VERSION 1 → 2. async_migrate_entry() converts the old
#   custom_inputs / homekit_inputs option pair into the single unified
#   options["inputs"] list. Nothing the user configured is lost.
# - Platforms TEXT, SELECT and SENSOR are gone. All configuration moved into
#   the options flow (config_flow.py). A registry sweep on every setup deletes
#   the entities those platforms left behind, so no "Unavailable" ghosts.
# - hass.data replaced by entry.runtime_data (typed dataclass). Home Assistant
#   deletes runtime_data on unload, so async_unload_entry no longer has to
#   remember to pop anything — that was a leak source.
# - Still NO update listener. Options are written by exactly two things now:
#   the options flow (which reloads itself via OptionsFlowWithReload) and the
#   two debug switches (which must NOT reload). This is what 1.0.2 tried and
#   failed to achieve with a guarded listener; removing the listener entirely
#   and making the options flow own the reload is the clean version of that.

from __future__ import annotations

import contextlib
import logging
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation

from .const import (
    CONF_TV_NAME,
    DOMAIN,
    IN_ACTION,
    IN_ID,
    IN_NAME,
    IN_SOURCE_ID,
    IN_TARGET,
    OPT_DEBUG_LISTEN,
    OPT_DEBUG_SEND,
    OPT_INPUTS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.REMOTE,
    Platform.MEDIA_PLAYER,
    Platform.BUTTON,
    Platform.SWITCH,
]


# ─── Runtime data ──────────────────────────────────────────────────────────────


@dataclass
class RuntimeData:
    """Everything the platforms share for one config entry.

    Lives on entry.runtime_data. Home Assistant removes it automatically when
    the entry unloads, which is why there is no manual cleanup below.
    """

    remote_entity_id: str
    media_entity_id: str
    remote_ref: Any = None          # TVRemote            (set by remote.py)
    media_ref: Any = None           # HomeKitTVMediaPlayer (set by media_player.py)
    tv_inputs: dict[str, int] = field(default_factory=dict)
    # tv_inputs: {"HDMI 3": 4, "Apple TV": 8, ...}
    # Built once by remote.py from the accessory metadata homekit_controller
    # already holds in memory. Reading it costs nothing and never touches the TV.


type HomeKitTVConfigEntry = ConfigEntry[RuntimeData]


def _slugify(name: str) -> str:
    """'Sony KD-55' → 'sony_kd_55' — matches HA entity ID slug rules."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ─── Setup / unload ────────────────────────────────────────────────────────────


async def async_setup_entry(hass: HomeAssistant, entry: HomeKitTVConfigEntry) -> bool:
    """Derive entity IDs from tv_name, clean up dead entities, load platforms."""
    tv_name = entry.data.get(CONF_TV_NAME, "Homekit TV")
    slug = _slugify(tv_name)

    entry.runtime_data = RuntimeData(
        remote_entity_id=f"remote.{slug}",
        media_entity_id=f"media_player.{slug}",
    )

    _async_remove_stale_entities(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass, _log_translation_diagnostics(hass), "homekit_tv_remote translation check"
    )
    return True


async def _log_translation_diagnostics(hass: HomeAssistant) -> None:
    """Say in the log whether the Configure dialog will have any text in it.

    A blank Configure dialog produces no error anywhere in Home Assistant, which
    makes it very hard to diagnose. There are three separate ways to get one:

      1. The `translations` folder is missing from the integration directory.
         Integration.has_translations is literally `"translations" in
         top_level_files`, where top_level_files is `os.listdir()` of the folder
         taken when the integration is first discovered. No folder, no text.
      2. The folder was added while Home Assistant was already running. That
         listing is taken once per run, so a reload is not enough — it needs a
         full restart before the folder is even looked at.
      3. The folder and file are both fine and the backend has the strings, in
         which case the browser is serving a stale translation cache and a hard
         refresh fixes it.

    This asks Home Assistant's own translation cache what it actually holds for
    this integration, which separates case 3 from cases 1 and 2, and lists the
    files it can see, which separates case 1 from case 2.
    """
    folder = pathlib.Path(__file__).parent

    def _listdir() -> list[str]:
        return sorted(item.name for item in folder.iterdir())

    try:
        files = await hass.async_add_executor_job(_listdir)
        resources = await translation.async_get_translations(
            hass, hass.config.language, "options", integrations={DOMAIN}
        )
    except Exception as err:  # noqa: BLE001 — diagnostics must never break setup
        _LOGGER.debug("Translation diagnostics failed: %s", err)
        return

    prefix = f"component.{DOMAIN}.options."
    count = sum(1 for key in resources if key.startswith(prefix))

    if count:
        # Quiet on success — this only needs to speak up when something is wrong.
        _LOGGER.debug(
            "Configure dialog text OK — %s option strings loaded for language '%s'",
            count,
            hass.config.language,
        )
        return

    has_folder = "translations" in files
    _LOGGER.error(
        "Configure dialog will have no text: Home Assistant loaded 0 option "
        "strings for this integration. translations folder present: %s. Files in "
        "%s: %s. %s",
        has_folder,
        folder,
        ", ".join(files),
        (
            "The folder is there, so it was almost certainly added while Home "
            "Assistant was running — restart Home Assistant fully, a reload is "
            "not enough."
            if has_folder
            else "Copy the translations folder from the release into the "
            "integration folder and restart Home Assistant."
        ),
    )


async def async_unload_entry(hass: HomeAssistant, entry: HomeKitTVConfigEntry) -> bool:
    """Unload all platforms. runtime_data is dropped by HA automatically."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# ─── Stale entity cleanup ──────────────────────────────────────────────────────


def _async_remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete registry entries this version no longer creates.

    Version 1 created one sensor and one "Include:" switch per saved input, five
    text fields, a select and five buttons. Version 2 creates exactly six
    entities. Anything else still registered against this config entry is a
    leftover and would otherwise sit in the UI as "Unavailable" forever.

    Allow-list rather than deny-list: future removals clean themselves up.
    """
    valid = {
        entry.entry_id,                             # remote
        f"{entry.entry_id}_media_player",           # media_player
        f"{entry.entry_id}_reload_homekit",         # button
        f"{entry.entry_id}_next_saved_input",       # button (unique_id kept from
                                                    # 1.x so the entity, its ID
                                                    # and its history survive)
        f"{entry.entry_id}_debug_listen",           # switch
        f"{entry.entry_id}_debug_send",             # switch
    }

    registry = er.async_get(hass)
    # Indexed lookup rather than a scan of registry.entities.values(). On a large
    # install that scan walked every entity in Home Assistant on every setup and
    # every reload, to find at most a handful belonging to this entry.
    removed = 0
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id in valid:
            continue
        registry.async_remove(reg_entry.entity_id)
        removed += 1

    if removed:
        _LOGGER.info(
            "Removed %s entity/entities left over from a previous version", removed
        )


# ─── Migration: config entry version 1 → 2 ─────────────────────────────────────


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Convert version 1 options to the version 2 schema."""
    if entry.version > 2:
        # Downgrade from a newer version is not supported.
        return False

    if entry.version == 1:
        _LOGGER.info("Migrating HomeKit TV Remote config entry from version 1 to 2")
        new_options = _migrate_options_v1_to_v2(dict(entry.options))
        hass.config_entries.async_update_entry(entry, options=new_options, version=2)

    return True


def _migrate_options_v1_to_v2(old: dict[str, Any]) -> dict[str, Any]:
    """Fold custom_inputs + homekit_inputs into the single `inputs` list.

    Version 1 stored every saved input in `custom_inputs` and separately kept a
    list of names in `homekit_inputs` for the ones whose "Include:" switch was
    on. Version 2 has no include flag: being in the list *is* being included.

    Every input is migrated, included or not, so nothing silently disappears.
    Anything that was previously excluded is named in the log — remove it in
    Configure → Manage saved inputs if you do not want it in Apple Home.

    Command string formats being unpacked here (all produced by button.py 1.x):
      hap                  "input_9"
      remote               "remote.bravia_kd_55xg9505.Hdmi2"
      media_player         "media_player.bravia|Netflix|app"
      media_player_source  "media_player.ng_apple_tv|Netflix"
      media_player_source  "media_player.ng_apple_tv|Netflix|input_8"
    """
    custom_inputs: list[dict[str, Any]] = list(old.get("custom_inputs", []))
    included: set[str] = set(old.get("homekit_inputs", []))

    inputs: list[dict[str, Any]] = []
    was_excluded: list[str] = []

    for index, item in enumerate(custom_inputs):
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        command_type = item.get("command_type", "hap")
        command = str(item.get("command", ""))
        new: dict[str, Any] = {IN_ID: f"m{index}", IN_NAME: name}

        if command_type == "hap":
            # "input_9" / "hdmi_9" → numeric HAP identifier.
            source_id = _parse_input_number(command)
            if source_id is not None:
                new[IN_SOURCE_ID] = source_id

        elif command_type == "remote":
            # "remote.entity_id.CommandName" — split off the last dot segment.
            target, _, action = command.rpartition(".")
            if target and action:
                new[IN_TARGET] = target
                new[IN_ACTION] = action

        elif command_type in ("media_player", "media_player_source"):
            parts = [p.strip() for p in command.split("|")]
            if len(parts) >= 2:
                new[IN_TARGET] = parts[0]
                new[IN_ACTION] = parts[1]
            # 3rd segment is "app" (play_media marker, now auto-detected) or
            # "input_N" (switch the TV to this input first — that we keep).
            if len(parts) == 3:
                source_id = _parse_input_number(parts[2])
                if source_id is not None:
                    new[IN_SOURCE_ID] = source_id

        # An explicit identifier saved alongside a remote/media_player input in
        # 1.x wins over anything parsed out of the command string.
        if item.get("identifier") not in (None, ""):
            with contextlib.suppress(TypeError, ValueError):
                new[IN_SOURCE_ID] = int(item["identifier"])

        inputs.append(new)
        if name not in included:
            was_excluded.append(name)

    if was_excluded:
        _LOGGER.warning(
            "Migrated %s input(s) that had their 'Include' switch off: %s. "
            "They are now visible in Apple Home. Remove them under "
            "Configure → Manage saved inputs if you do not want them",
            len(was_excluded),
            ", ".join(was_excluded),
        )

    return {
        OPT_INPUTS: inputs,
        OPT_DEBUG_LISTEN: bool(old.get(OPT_DEBUG_LISTEN, False)),
        OPT_DEBUG_SEND: bool(old.get(OPT_DEBUG_SEND, False)),
    }


def _parse_input_number(command: str) -> int | None:
    """'input_9' / 'hdmi_3' → 9 / 3. Anything else → None."""
    match = re.fullmatch(r"(?:input|hdmi)_(\d+)", command.strip().lower())
    return int(match.group(1)) if match else None
