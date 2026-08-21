"""Shared constants for HomeKit TV Remote."""
# Version: 2.4.0
#
# NEW IN 2.0.0 — this file did not exist before. Every platform file used to
# redeclare DOMAIN and its own magic strings, which is how the option keys
# drifted apart between switch.py, button.py and media_player.py. Everything
# shared now lives here and is imported.

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homekit_tv_remote"

# The documentation URL lives only in manifest.json. That single field is what
# puts the ? icon in every dialog header and the Documentation item in the
# integration's menu, so a separate Manual step would only have duplicated a
# link the dialog already carries.

# ─── Config entry: data (static, written once by the config flow) ─────────────
CONF_HK_ENTITY: Final = "media_player_entity_id"   # HomeKit Device media_player
CONF_TV_NAME: Final = "tv_name"

# ─── Config entry: options (written only by the options flow) ─────────────────
OPT_INPUTS: Final = "inputs"                # list[InputDict] — order = cycle order
OPT_DEBUG_LISTEN: Final = "debug_listen"
OPT_DEBUG_SEND: Final = "debug_send"

# ─── One input dict ───────────────────────────────────────────────────────────
# {
#   "id":        "3f9c1a",        unique, generated on create, never reused
#   "name":      "Apple TV",      shown in Apple Home + HA source_list
#   "source":    "Apple TV",      TV input (HomeKit configured name) or "" / absent
#   "source_id": 8,               legacy numeric HAP identifier (migrated setups)
#   "target":    "media_player.ng_apple_tv" | "remote.bravia" | "" / absent
#   "action":    "Netflix" | "Hdmi2",   app name or vendor remote command
# }
#
# Resolution rules (single place: media_player._run_input):
#   target empty            → TV input only: HAP ActiveIdentifier write
#   target set, source set  → switch TV input first, then run the target action
#   target set, source not  → run the target action only
#   target is media_player. → select_source if `action` is in that entity's
#                             source_list, else play_media   (auto-detected)
#   target is remote.       → remote.send_command
IN_ID: Final = "id"
IN_NAME: Final = "name"
IN_SOURCE: Final = "source"
IN_SOURCE_ID: Final = "source_id"
IN_TARGET: Final = "target"
IN_ACTION: Final = "action"

# Shared state lives on entry.runtime_data (see RuntimeData in __init__.py) as
# typed attributes, so there are no string keys to declare here any more. The
# four DATA_* constants that used to sit at this spot were left over from the
# hass.data era and referenced by nothing.

# ─── homekit_controller internals we read (documented, defensive) ─────────────
HKC_DEVICES: Final = "homekit_controller-devices"

# ─── HomeKit Bridge remote-widget event ───────────────────────────────────────
# Mirrors homeassistant.components.homekit.const — copied rather than imported
# so this integration never hard-depends on the bridge being loaded.
EVENT_HOMEKIT_KEY: Final = "homekit_tv_remote_key_pressed"
ATTR_KEY_NAME: Final = "key_name"

# ─── HAP RemoteKey values (aiohomekit RemoteKeyValues) ────────────────────────
KEY_REWIND: Final = 0
KEY_FAST_FORWARD: Final = 1
KEY_NEXT_TRACK: Final = 2
KEY_PREVIOUS_TRACK: Final = 3
KEY_ARROW_UP: Final = 4
KEY_ARROW_DOWN: Final = 5
KEY_ARROW_LEFT: Final = 6
KEY_ARROW_RIGHT: Final = 7
KEY_SELECT: Final = 8
KEY_BACK: Final = 9
KEY_EXIT: Final = 10
KEY_PLAY_PAUSE: Final = 11
KEY_INFORMATION: Final = 15
# Not in the HAP spec — vendor extensions seen on Sony. Kept because they work
# there; sent as plain integers so unsupported TVs simply ignore them.
KEY_TV_SETTINGS: Final = 14
KEY_TV_HOME: Final = 16

# Friendly command aliases accepted by remote.send_command, in addition to the
# raw integers. Automations no longer have to remember that Back is "9".
COMMAND_ALIASES: Final[dict[str, int]] = {
    "up": KEY_ARROW_UP,
    "down": KEY_ARROW_DOWN,
    "left": KEY_ARROW_LEFT,
    "right": KEY_ARROW_RIGHT,
    "select": KEY_SELECT,
    "ok": KEY_SELECT,
    "enter": KEY_SELECT,
    "back": KEY_BACK,
    "exit": KEY_EXIT,
    "play_pause": KEY_PLAY_PAUSE,
    "play": KEY_PLAY_PAUSE,
    "pause": KEY_PLAY_PAUSE,
    "rewind": KEY_REWIND,
    "fast_forward": KEY_FAST_FORWARD,
    "next_track": KEY_NEXT_TRACK,
    "previous_track": KEY_PREVIOUS_TRACK,
    "info": KEY_INFORMATION,
    "information": KEY_INFORMATION,
    "home": KEY_TV_HOME,
    "settings": KEY_TV_SETTINGS,
}

# Bridge key_name (from the iOS remote widget) → HAP RemoteKey value.
# "information" is handled separately: it cycles inputs instead.
BRIDGE_KEY_MAP: Final[dict[str, int]] = {
    "arrow_up": KEY_ARROW_UP,
    "arrow_down": KEY_ARROW_DOWN,
    "arrow_left": KEY_ARROW_LEFT,
    "arrow_right": KEY_ARROW_RIGHT,
    "select": KEY_SELECT,
    "back": KEY_BACK,
    "exit": KEY_EXIT,
    "play_pause": KEY_PLAY_PAUSE,
    "rewind": KEY_REWIND,
    "fast_forward": KEY_FAST_FORWARD,
    "next_track": KEY_NEXT_TRACK,
    "previous_track": KEY_PREVIOUS_TRACK,
}

# ─── VolumeSelector values ────────────────────────────────────────────────────
VOLUME_UP: Final = 0
VOLUME_DOWN: Final = 1
VOLUME_MUTE_FALLBACK: Final = 2   # non-standard; only used if no Mute char

# ─── Debug log prefixes ───────────────────────────────────────────────────────
DEBUG_LISTEN: Final = "HOMEKIT_TV_LISTEN"
DEBUG_SEND: Final = "HOMEKIT_TV_SEND"
