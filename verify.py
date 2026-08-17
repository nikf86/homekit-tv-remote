"""Behavioural checks for the 2.0.0 rewrite. Run with the HA venv."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from aiohomekit.model import Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes as CT
from aiohomekit.model.services import ServicesTypes as ST

from custom_components.homekit_tv_remote import (
    RuntimeData,
    _migrate_options_v1_to_v2,
)
from custom_components.homekit_tv_remote.remote import TVRemote, _discover
from custom_components.homekit_tv_remote.media_player import HomeKitTVMediaPlayer

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        FAILURES.append(label)


# ─── 1. Migration from the 1.x option schema ───────────────────────────────────

print("\n1. Migration v1 → v2")

old_options = {
    "custom_inputs": [
        {"name": "Sky", "command_type": "hap", "command": "input_9"},
        {
            "name": "Portal CEC",
            "command_type": "remote",
            "command": "remote.bravia_kd_55xg9505.Hdmi2",
            "identifier": 6,
        },
        {
            "name": "Bravia Netflix",
            "command_type": "media_player",
            "command": "media_player.bravia_kd_55xg9505|Netflix|app",
        },
        {
            "name": "ATV Netflix",
            "command_type": "media_player_source",
            "command": "media_player.ng_apple_tv|Netflix|input_8",
        },
        {
            "name": "ATV Disney",
            "command_type": "media_player_source",
            "command": "media_player.ng_apple_tv|Disney+",
        },
    ],
    "homekit_inputs": ["Sky", "ATV Netflix", "ATV Disney"],
    "debug_send": True,
}

new = _migrate_options_v1_to_v2(old_options)
inputs = new["inputs"]

check("all five inputs migrated", len(inputs), 5)
check("hap input keeps its identifier", inputs[0].get("source_id"), 9)
check("hap input has no target", inputs[0].get("target"), None)
check("remote target split", inputs[1].get("target"), "remote.bravia_kd_55xg9505")
check("remote action split", inputs[1].get("action"), "Hdmi2")
check("explicit identifier kept", inputs[1].get("source_id"), 6)
check("play_media target", inputs[2].get("target"), "media_player.bravia_kd_55xg9505")
check("play_media action", inputs[2].get("action"), "Netflix")
check("'app' marker not stored as identifier", inputs[2].get("source_id"), None)
check("apple tv hdmi segment kept", inputs[3].get("source_id"), 8)
check("apple tv app only", inputs[4].get("action"), "Disney+")
check("debug flag carried over", new["debug_send"], True)
check("old keys dropped", "custom_inputs" in new or "homekit_inputs" in new, False)
check("ids are unique", len({i["id"] for i in inputs}), 5)


# ─── 2. Identifier discovery from the accessory tree ───────────────────────────

print("\n2. Reading real input identifiers from HAP")


def build_tv() -> Accessory:
    """A TV whose inputs are numbered 3, 7 and 12 — not 1, 2, 3."""
    acc = Accessory.create_with_info(
        1,
        name="Sony TV",
        manufacturer="Sony",
        model="KD-55XG9505",
        serial_number="X",
        firmware_revision="1",
    )
    tv = acc.add_service(ST.TELEVISION)
    tv.add_char(CT.REMOTE_KEY)
    tv.add_char(CT.ACTIVE)
    tv.add_char(CT.ACTIVE_IDENTIFIER)

    speaker = acc.add_service(ST.SPEAKER)
    speaker.add_char(CT.VOLUME_SELECTOR)
    speaker.add_char(CT.MUTE)
    tv.add_linked_service(speaker)

    for name, ident in (("TV", 3), ("HDMI 2", 7), ("Apple TV", 12)):
        source = acc.add_service(ST.INPUT_SOURCE)
        source.add_char(CT.CONFIGURED_NAME, value=name)
        source.add_char(CT.IDENTIFIER, value=ident)
        tv.add_linked_service(source)
    return acc


class FakeAccessories(list):
    @property
    def accessories(self):
        return self

    def aid(self, aid):
        for acc in self:
            if acc.aid == aid:
                return acc
        raise KeyError(aid)


accessory = build_tv()
conn = SimpleNamespace(entity_map=FakeAccessories([accessory]))
tv_service = accessory.services.first(service_type=ST.TELEVISION)

found = _discover(conn, f"00:11:22_1_{tv_service.iid}")
check("input map read from HAP", found.inputs, {"TV": 3, "HDMI 2": 7, "Apple TV": 12})
check("this is NOT index+1", found.inputs != {"TV": 1, "HDMI 2": 2, "Apple TV": 3}, True)
check("RemoteKey found", found.remote_key is not None, True)
check("Active found", found.active is not None, True)
check("ActiveIdentifier found", found.active_identifier is not None, True)
check("VolumeSelector found on linked speaker", found.volume is not None, True)
check("Mute found on linked speaker", found.mute is not None, True)

# Fallback route: no usable unique_id, must still find the TV by scanning.
found_scan = _discover(conn, None)
check("scan fallback finds inputs", found_scan.inputs, {"TV": 3, "HDMI 2": 7, "Apple TV": 12})


# ─── 3. Command routing in the remote entity ───────────────────────────────────

print("\n3. remote.send_command routing")

writes: list[tuple] = []


class FakeConn:
    async def put_characteristics(self, chars):
        writes.extend(chars)


class FakeBus:
    def async_listen(self, *a, **k):
        return lambda: None


class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.bus = FakeBus()
        self.services = FakeServices()
        self.loop = asyncio.get_event_loop()

    def async_create_background_task(self, coro, name=None, **k):
        return asyncio.get_event_loop().create_task(coro)

    def async_create_task(self, coro, *a, **k):
        return asyncio.get_event_loop().create_task(coro)


class FakeStates:
    def __init__(self):
        self._states = {}

    def set(self, entity_id, state, **attrs):
        self._states[entity_id] = SimpleNamespace(
            entity_id=entity_id, state=state, attributes=attrs
        )

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeServices:
    def __init__(self):
        self.calls = []
        self.blocking_flags = []
        self.delay = 0.0

    async def async_call(self, domain, service, data, blocking=False):
        self.blocking_flags.append(blocking)
        if blocking and self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append((domain, service, data))

    def has_service(self, domain, service):
        return True


def make_entry(options=None):
    entry = SimpleNamespace(
        entry_id="abc123",
        data={"media_player_entity_id": "media_player.hk_tv", "tv_name": "Sony TV"},
        options=options or {},
    )
    entry.runtime_data = RuntimeData(
        remote_entity_id="remote.sony_tv",
        media_entity_id="media_player.sony_tv",
        tv_inputs={"TV": 3, "HDMI 2": 7, "Apple TV": 12},
    )
    entry.background = []

    def _bg(hass, coro, name):
        task = asyncio.get_event_loop().create_task(coro)
        entry.background.append(task)
        return task

    entry.async_create_background_task = _bg
    return entry


async def main() -> None:
    hass = FakeHass()
    entry = make_entry()
    remote = TVRemote(hass, entry, FakeConn(), found, "media_player.hk_tv")
    remote.async_write_ha_state = lambda: None
    entry.runtime_data.remote_ref = remote

    rk_iid = found.remote_key[1]
    ai_iid = found.active_identifier[1]
    vol_iid = found.volume[1]
    mute_iid = found.mute[1]

    writes.clear()
    await remote.async_send_command(["8"])
    await asyncio.sleep(0)
    check("raw integer → RemoteKey 8", writes, [(1, rk_iid, 8)])

    writes.clear()
    await remote.async_send_command(["back"])
    await asyncio.sleep(0)
    check("alias 'back' → RemoteKey 9", writes, [(1, rk_iid, 9)])

    writes.clear()
    await remote.async_send_command(["home"])
    await asyncio.sleep(0)
    check("alias 'home' → RemoteKey 16", writes, [(1, rk_iid, 16)])

    writes.clear()
    await remote.async_send_command(["volume_up"])
    check("volume_up → VolumeSelector 0", writes, [(1, vol_iid, 0)])

    writes.clear()
    await remote.async_send_command(["mute"])
    check("mute toggles on", writes, [(1, mute_iid, True)])
    writes.clear()
    await remote.async_send_command(["mute"])
    check("mute toggles back off", writes, [(1, mute_iid, False)])
    writes.clear()
    await remote.async_send_command(["mute_on"])
    check("mute_on is explicit", writes, [(1, mute_iid, True)])

    writes.clear()
    await remote.async_send_command(["input:Apple TV"])
    check("input by name uses the real identifier 12", writes, [(1, ai_iid, 12)])

    writes.clear()
    await remote.async_send_command(["input:apple tv"])
    check("input by name is case-insensitive", writes, [(1, ai_iid, 12)])

    writes.clear()
    await remote.async_send_command(["input_7"])
    check("legacy input_N still works", writes, [(1, ai_iid, 7)])

    writes.clear()
    await remote.async_send_command(["4", "8"], delay_secs=0)
    await asyncio.sleep(0)
    check("multi-command sequence", writes, [(1, rk_iid, 4), (1, rk_iid, 8)])

    # ── Power state from the HomeKit Device entity ─────────────────────────────
    print("\n4. State mirrored from the HomeKit Device entity")

    hass.states.set("media_player.hk_tv", "playing", source="Apple TV")
    remote._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("'playing' counts as ON (1.x said OFF)", remote.is_on, True)
    check("current source tracked", remote.extra_state_attributes["current_source"], "Apple TV")

    hass.states.set("media_player.hk_tv", "standby", source="TV")
    remote._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("'standby' counts as OFF", remote.is_on, False)

    hass.states.set("media_player.hk_tv", "on", source="TV")
    remote._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("'on' counts as ON", remote.is_on, True)

    # ── Input execution ────────────────────────────────────────────────────────
    print("\n5. Running configured inputs")

    options = {
        "inputs": [
            {"id": "1", "name": "TV", "source": "TV"},
            {"id": "2", "name": "Apple TV", "source": "Apple TV"},
            {
                "id": "3",
                "name": "Netflix",
                "target": "media_player.ng_apple_tv",
                "action": "Netflix",
                "source": "Apple TV",
            },
            {
                "id": "4",
                "name": "Bravia YouTube",
                "target": "media_player.bravia",
                "action": "YouTube",
            },
            {
                "id": "5",
                "name": "Portal CEC",
                "target": "remote.bravia",
                "action": "Hdmi2",
            },
            {"id": "6", "name": "Legacy", "source_id": 7},
        ]
    }
    entry.options = options

    media = HomeKitTVMediaPlayer(hass, entry, "media_player.hk_tv")
    media.async_write_ha_state = lambda: None
    entry.runtime_data.media_ref = media

    # Apple TV lists its apps as sources; the Bravia does not.
    hass.states.set(
        "media_player.ng_apple_tv", "on", source_list=["Netflix", "Disney+", "TV"]
    )
    hass.states.set("media_player.bravia", "on", source_list=["HDMI 1", "HDMI 2"])

    check(
        "source_list is the configured names",
        media.source_list,
        ["TV", "Apple TV", "Netflix", "Bravia YouTube", "Portal CEC", "Legacy"],
    )

    writes.clear()
    hass.services.calls.clear()
    await media.async_select_source("Apple TV")
    check("plain TV input → HAP write only", writes, [(1, ai_iid, 12)])
    check("plain TV input makes no service calls", hass.services.calls, [])

    writes.clear()
    hass.services.calls.clear()
    await media.async_select_source("Netflix")
    check("app shortcut switches TV input first", writes, [(1, ai_iid, 12)])
    check(
        "app in target's source_list → select_source",
        hass.services.calls,
        [
            (
                "media_player",
                "select_source",
                {"entity_id": "media_player.ng_apple_tv", "source": "Netflix"},
            )
        ],
    )

    writes.clear()
    hass.services.calls.clear()
    await media.async_select_source("Bravia YouTube")
    check("no TV input configured → no HAP write", writes, [])
    check(
        "app NOT in source_list → play_media",
        hass.services.calls,
        [
            (
                "media_player",
                "play_media",
                {
                    "entity_id": "media_player.bravia",
                    "media_content_id": "YouTube",
                    "media_content_type": "app",
                },
            )
        ],
    )

    hass.services.calls.clear()
    await media.async_select_source("Portal CEC")
    check(
        "remote target → send_command",
        hass.services.calls,
        [
            (
                "remote",
                "send_command",
                {"entity_id": "remote.bravia", "command": "Hdmi2"},
            )
        ],
    )

    writes.clear()
    await media.async_select_source("Legacy")
    check("migrated numeric identifier still switches", writes, [(1, ai_iid, 7)])

    # ── Cycling ────────────────────────────────────────────────────────────────
    print("\n6. Input cycling")

    hass.states.set("media_player.hk_tv", "on", source="Apple TV")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("source resolves to our name", media.source, "Apple TV")

    async def cycle_and_settle():
        """Cycling dispatches in the background now — wait for it in tests."""
        entry.background.clear()
        await media.async_cycle_input()
        await asyncio.gather(*entry.background)

    writes.clear()
    hass.services.calls.clear()
    media._last_cycle = 0.0
    await cycle_and_settle()
    check(
        "cycle from the live input goes to the next one",
        hass.services.calls[0][2]["entity_id"],
        "media_player.ng_apple_tv",
    )

    hass.states.set("media_player.hk_tv", "on", source="TV")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    writes.clear()
    hass.services.calls.clear()
    media._last_cycle = 0.0
    await cycle_and_settle()
    check("cycle resyncs after an external input change", writes, [(1, ai_iid, 12)])

    # Unknown input → source is None, not a name outside source_list.
    hass.states.set("media_player.hk_tv", "on", source="HDMI 4")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("unconfigured input reports source None", media.source, None)
    check("raw name still visible", media.extra_state_attributes["tv_source"], "HDMI 4")

    # ── The cycling lockup ─────────────────────────────────────────────────────
    print("\n7. Cycling stays responsive when the target is slow")

    # An Apple TV select_source that takes 3s to return — the real-world case
    # that made the ⓘ button and Next input feel dead in 2.0.x.
    hass.services.delay = 3.0
    hass.states.set("media_player.hk_tv", "on", source="TV")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    media._last_cycle = 0.0
    hass.services.calls.clear()
    hass.services.blocking_flags.clear()
    entry.background.clear()

    loop = asyncio.get_event_loop()
    start = loop.time()
    await media.async_cycle_input()
    first = media._cycle_index
    await media.async_cycle_input()
    second = media._cycle_index
    await media.async_cycle_input()
    third = media._cycle_index
    elapsed = loop.time() - start

    check("three presses return without waiting", elapsed < 0.2, True)
    check("each press advances one step", [first, second, third], [1, 2, 3])
    check("commands dispatched in the background", len(entry.background), 3)
    check(
        "third-party calls are non-blocking",
        any(hass.services.blocking_flags) if hass.services.blocking_flags else False,
        False,
    )

    await asyncio.gather(*entry.background)
    hass.services.delay = 0.0

    # After a pause, the cycle continues from whatever was last selected — even
    # a shortcut the TV cannot report, like an app launch that leaves the TV on
    # the same input. Three cycles above landed on index 3.
    entry.background.clear()
    hass.services.blocking_flags.clear()
    media._last_cycle = 0.0
    await media.async_cycle_input()
    check("after a pause it continues from the last thing selected",
          media._cycle_index, 4)

    # But when the TV genuinely moves elsewhere — someone picked up its own
    # remote — the anchor is dropped and the cycle follows the TV again.
    entry.background.clear()
    media._last_cycle = 0.0
    hass.states.set("media_player.hk_tv", "on", source="Apple TV")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("a real TV move clears the remembered selection", media._active_id, None)
    check("source follows the TV again", media.source, "Apple TV")
    await media.async_cycle_input()
    check("and the cycle resyncs to it", media._cycle_index, 2)

    # A power change on its own must not clear it — the TV has not moved.
    entry.background.clear()
    await media.async_select_source("Bravia YouTube")
    await asyncio.gather(*entry.background)
    hass.states.set("media_player.hk_tv", "playing", source="Apple TV")
    media._apply_hk_state(hass.states.get("media_player.hk_tv"))
    check("a state change with no input change keeps it", media.source, "Bravia YouTube")

    # Test from the options flow still blocks, so failures surface.
    hass.services.blocking_flags.clear()
    await media.async_run_input(
        {"name": "t", "target": "media_player.ng_apple_tv", "action": "Netflix"},
        blocking=True,
    )
    check("options-flow Test still blocks", hass.services.blocking_flags, [True])

    # ── Bridge key events ──────────────────────────────────────────────────────
    print("\n8. iOS remote widget keys")
    from custom_components.homekit_tv_remote.const import BRIDGE_KEY_MAP

    check("d-pad up mapped", BRIDGE_KEY_MAP["arrow_up"], 4)
    check("select mapped", BRIDGE_KEY_MAP["select"], 8)
    check("back mapped", BRIDGE_KEY_MAP["back"], 9)
    check("play/pause mapped", BRIDGE_KEY_MAP["play_pause"], 11)
    check("exit newly mapped", BRIDGE_KEY_MAP["exit"], 10)
    check("rewind newly mapped", BRIDGE_KEY_MAP["rewind"], 0)
    check("information NOT a key press", "information" in BRIDGE_KEY_MAP, False)


asyncio.run(main())


# ─── 9. Configure changes must reach the frontend immediately ──────────────────
#
# Regression guard for the bug where a saved shortcut stayed invisible until the
# TV next changed state — sometimes half an hour. The data was right; nothing
# published it. Writing options and publishing the new state are two steps.

print("\n9. Saving an input publishes the new source list")


async def _config_flow_checks() -> None:
    from custom_components.homekit_tv_remote.config_flow import HomeKitTVOptionsFlow

    hass = FakeHass()
    entry = make_entry({"inputs": [{"id": "a", "name": "TV", "source": "TV"}]})

    class Entries:
        @staticmethod
        def async_update_entry(target, options=None, **_):
            target.options = options

    hass.config_entries = Entries()

    media = HomeKitTVMediaPlayer(hass, entry, "media_player.hk_tv")
    entry.runtime_data.media_ref = media
    writes = []
    media.async_write_ha_state = lambda: writes.append(1)

    class Flow(HomeKitTVOptionsFlow):
        def __init__(self, cfg_entry, hass_):
            self._e, self.hass = cfg_entry, hass_

        @property
        def config_entry(self):
            return self._e

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_show_menu(self, **kwargs):
            return {"type": "menu", **kwargs}

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

        def add_suggested_values_to_schema(self, schema, _values):
            return schema

    flow = Flow(entry, hass)

    await flow.async_step_shortcut(
        {"name": "Netflix", "target": "media_player.atv", "action": "Netflix"}
    )
    check("the shortcut is stored", [i["name"] for i in flow._inputs], ["TV", "Netflix"])
    check("source_list includes it straight away", media.source_list, ["TV", "Netflix"])
    check("and the new state was published", len(writes), 1)

    writes.clear()
    await flow.async_step_rename({"target_input": "a", "new_name": "Television"})
    check("renaming publishes too", len(writes), 1)
    check("under the new name", media.source_list[0], "Television")

    writes.clear()
    await flow.async_step_remove({"remove": ["a"]})
    check("removing publishes too", len(writes), 1)
    check("and it is gone from the source list", media.source_list, ["Netflix"])

    menu = await flow.async_step_init()
    check("Manual entry removed from the menu", menu["menu_options"],
          ["tv_inputs", "shortcut", "manage"])

    # Two entries with one name give a source_list with duplicates, and
    # select_source then picks whichever comes first. The shortcut form already
    # refuses a duplicate; ticking a TV input must refuse it from the other side.
    entry.options = {"inputs": [
        {"id": "s", "name": "Apple TV", "target": "media_player.atv", "action": "Netflix"},
    ]}
    entry.runtime_data.tv_inputs = {"TV": 1, "Apple TV": 8}
    result = await flow.async_step_tv_inputs({"sources": ["Apple TV"]})
    check("a TV input clashing with a shortcut is refused",
          result.get("errors"), {"base": "name_clash"})
    check("and nothing was saved", [i["name"] for i in flow._inputs], ["Apple TV"])
    result = await flow.async_step_tv_inputs({"sources": ["TV"]})
    check("a non-clashing tick still saves", result["type"], "menu")
    check("names stay unique", sorted(i["name"] for i in flow._inputs),
          ["Apple TV", "TV"])


asyncio.run(_config_flow_checks())

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): " + "; ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
