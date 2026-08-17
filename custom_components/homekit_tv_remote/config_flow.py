"""Config flow and options flow for HomeKit TV Remote."""
# Version: 2.2.0
#
# WHAT THIS FILE IS RESPONSIBLE FOR
#   All user input. Every field that used to be an entity on the device page
#   lives here, in Settings → Devices & Services → HomeKit TV Remote →
#   Configure.
#
# WHY IT MOVED
#   1.x spread configuration across 5 text entities, a select, 5 buttons, 2
#   Apple TV switches and one Include switch per input — 15+ entities whose only
#   job was to hold a value until a button read it. That is what forced the
#   fixed "1a. / 1b. / 1c." naming (entities sort alphabetically), what made
#   every field reset on reload, and what caused the reload races that 1.0.2,
#   1.0.3, 1.5.1, 1.6.0, 1.7.0 and switch 1.3.5 were all trying to fix.
#
# NEW IN 2.1.0 — EDITS APPLY IMMEDIATELY, THE DIALOG STAYS OPEN
#   Every step now writes options with async_update_entry and returns to the
#   menu, instead of ending the flow with async_create_entry. Two reasons:
#
#     - Nothing needs a reload. media_player.py reads options["inputs"] live on
#       every source_list access and every cycle step, so a rename or a reorder
#       is in effect the moment it is written. The only thing that does need a
#       nudge is Apple Home, which caches the accessory's input list — that is
#       what the Reload HomeKit Bridge button is for, pressed once at the end.
#     - Ending the flow closed the dialog after every single change. Renaming
#       three inputs meant opening Configure three times.
#
#   Consequence: OptionsFlowWithReload never fires, because the flow does not end
#   with changed options. That is intentional and correct here. The class is kept
#   as the base so the behaviour is explicit rather than accidental.
#
# WHAT THE USER FILLS IN
#   TV inputs        checkbox list, pre-filled with the TV's real inputs, plus a
#                    Test dropdown that switches the TV to one without saving.
#   Add a shortcut   name, target entity, what to send, optional TV input first,
#                    and a Test box that fires it without saving.
#   Manage           rename, reorder, remove.
#   Manual           link to the documentation.

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_HK_ENTITY,
    CONF_TV_NAME,
    DOCS_URL,
    DOMAIN,
    IN_ACTION,
    IN_ID,
    IN_NAME,
    IN_SOURCE,
    IN_SOURCE_ID,
    IN_TARGET,
    OPT_INPUTS,
)
from .remote_art import REMOTE_SVG

_LOGGER = logging.getLogger(__name__)

CONF_ACTION = "action"
CONF_DIRECTION = "direction"
CONF_NEW_NAME = "new_name"
CONF_REMOVE = "remove"
CONF_SOURCES = "sources"
CONF_TARGET_INPUT = "target_input"
CONF_TEST = "test"
CONF_TEST_INPUT = "test_input"
CONF_TV_SOURCE = "tv_source"

MOVE_TOP = "top"
MOVE_UP = "up"
MOVE_DOWN = "down"
MOVE_BOTTOM = "bottom"


# ─── Config flow ───────────────────────────────────────────────────────────────


class HomeKitTVRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """One step: pick the paired TV, name it, done."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a dropdown of TVs paired through the HomeKit Device integration."""
        registry = er.async_get(self.hass)
        televisions: dict[str, str] = {
            entry.entity_id: entry.name or entry.original_name or entry.entity_id
            for entry in registry.entities.values()
            if entry.platform == "homekit_controller" and entry.domain == "media_player"
        }

        if not televisions:
            return self.async_abort(reason="no_homekit_tv")

        if user_input is not None:
            entity_id = user_input[CONF_HK_ENTITY]
            tv_name = (user_input.get(CONF_TV_NAME) or "Homekit TV").strip()

            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"TV Remote ({tv_name})",
                data={CONF_HK_ENTITY: entity_id, CONF_TV_NAME: tv_name},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HK_ENTITY): vol.In(televisions),
                    vol.Optional(CONF_TV_NAME, default="Homekit TV"): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        return HomeKitTVOptionsFlow()


# ─── Options flow ──────────────────────────────────────────────────────────────


class HomeKitTVOptionsFlow(OptionsFlowWithReload):
    """Everything the user configures after setup."""

    # No __init__: no base class defines one, and no state is carried between
    # steps. Every step reads options fresh and writes them whole.

    # ─── Reading ───────────────────────────────────────────────────────────────

    @property
    def _inputs(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.config_entry.options.get(OPT_INPUTS, [])]

    @property
    def _media(self):
        """The live media player entity, or None if the entry is not loaded."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        return getattr(runtime, "media_ref", None) if runtime else None

    def _tv_sources(self) -> list[str]:
        """The TV's real input names.

        Preferred source is the name→identifier map remote.py built from the
        accessory metadata. If the entry is not loaded, fall back to the
        HomeKit Device entity's source_list attribute.
        """
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None and getattr(runtime, "tv_inputs", None):
            return list(runtime.tv_inputs)

        hk_entity_id = self.config_entry.data.get(CONF_HK_ENTITY)
        state = self.hass.states.get(hk_entity_id) if hk_entity_id else None
        return list(state.attributes.get("source_list") or []) if state else []

    @staticmethod
    def _is_tv_input(item: dict[str, Any]) -> bool:
        """True for entries the TV-inputs checkbox list owns."""
        return bool(item.get(IN_SOURCE)) and not item.get(IN_TARGET)

    def _describe(self, item: dict[str, Any]) -> str:
        """One line saying what an input actually does."""
        name = item.get(IN_NAME, "?")
        if self._is_tv_input(item):
            return f"{name}  —  TV input “{item[IN_SOURCE]}”"
        if item.get(IN_TARGET):
            prefix = f"{item[IN_SOURCE]} → " if item.get(IN_SOURCE) else ""
            return f"{name}  —  {prefix}{item[IN_TARGET]} → {item.get(IN_ACTION, '')}"
        if item.get(IN_SOURCE_ID) is not None:
            return f"{name}  —  TV input #{item[IN_SOURCE_ID]} (migrated)"
        return name

    def _input_options(self) -> list[selector.SelectOptionDict]:
        """Dropdown options for the saved inputs, numbered in cycle order."""
        return [
            selector.SelectOptionDict(
                value=item[IN_ID], label=f"{index}.  {self._describe(item)}"
            )
            for index, item in enumerate(self._inputs, start=1)
        ]

    # ─── Writing ───────────────────────────────────────────────────────────────

    @callback
    def _apply(self, inputs: list[dict[str, Any]]) -> None:
        """Persist the input list without ending the flow.

        No reload is triggered and none is needed: media_player.py reads
        options["inputs"] live. Apple Home is the exception — press Reload
        HomeKit Bridge once when finished.
        """
        entry = self.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, OPT_INPUTS: inputs}
        )

    # ─── Menu ──────────────────────────────────────────────────────────────────

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["tv_inputs", "shortcut", "hap_commands", "manage", "manual"],
        )

    # ─── TV inputs ─────────────────────────────────────────────────────────────

    async def async_step_tv_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tick the TV inputs to expose, and try one out before committing.

        The Test dropdown is the whole "does HDMI 3 actually mean the Xbox"
        question answered in one press: pick an input, submit, the TV switches,
        the form stays open. Nothing is saved on a test.
        """
        sources = self._tv_sources()
        if not sources:
            return self.async_abort(reason="no_sources")

        existing = self._inputs
        errors: dict[str, str] = {}

        if user_input is not None:
            if test_source := user_input.get(CONF_TEST_INPUT):
                errors["base"] = await self._test_tv_input(test_source)
            else:
                chosen = list(user_input.get(CONF_SOURCES, []))
                # Keep everything the checkbox list does not own — shortcuts, and
                # inputs migrated from 1.x that still carry a numeric identifier.
                others = [item for item in existing if not self._is_tv_input(item)]
                by_source = {
                    item[IN_SOURCE]: item
                    for item in existing
                    if self._is_tv_input(item)
                }
                # Rebuild in the TV's own order, reusing existing entries so an
                # input that was already ticked keeps its id and its name.
                tv_inputs = [
                    by_source.get(
                        source,
                        {IN_ID: uuid4().hex[:8], IN_NAME: source, IN_SOURCE: source},
                    )
                    for source in sources
                    if source in chosen
                ]
                self._apply(tv_inputs + others)
                return await self.async_step_init()

        current = [item[IN_SOURCE] for item in existing if self._is_tv_input(item)]
        schema = vol.Schema(
            {
                vol.Optional(CONF_SOURCES, default=current): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sources,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_TEST_INPUT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sources,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="tv_inputs", data_schema=schema, errors=errors
        )

    async def _test_tv_input(self, source: str) -> str:
        """Switch the TV to one of its own inputs. Returns an error key."""
        media = self._media
        if media is None:
            _LOGGER.error("Test: the integration is not loaded, nothing was sent")
            return "test_failed"
        try:
            await media.async_run_input(
                {IN_NAME: f"test:{source}", IN_SOURCE: source}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 — any failure is worth reporting
            _LOGGER.error("Test failed: %s", err)
            return "test_failed"
        _LOGGER.info("Test switched the TV to '%s'", source)
        return "test_sent"

    # ─── Shortcuts ─────────────────────────────────────────────────────────────

    async def async_step_shortcut(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an input that drives another integration — an app, a CEC command.

        Whether a media_player target needs select_source or play_media is
        worked out when the shortcut runs, by checking that entity's own
        source_list. That is why there is no Apple TV switch any more.
        """
        sources = self._tv_sources()
        errors: dict[str, str] = {}

        if user_input is not None:
            name = (user_input.get(IN_NAME) or "").strip()
            target = user_input.get(IN_TARGET) or ""
            action = (user_input.get(CONF_ACTION) or "").strip()
            tv_source = user_input.get(CONF_TV_SOURCE) or ""
            testing = bool(user_input.get(CONF_TEST))

            if not name:
                errors[IN_NAME] = "name_required"
            elif not testing and any(
                item.get(IN_NAME) == name for item in self._inputs
            ):
                errors[IN_NAME] = "name_taken"
            if not action:
                errors[CONF_ACTION] = "action_required"

            if not errors:
                item: dict[str, Any] = {
                    IN_ID: uuid4().hex[:8],
                    IN_NAME: name,
                    IN_TARGET: target,
                    IN_ACTION: action,
                }
                if tv_source:
                    item[IN_SOURCE] = tv_source

                if testing:
                    errors["base"] = await self._test_shortcut(item)
                else:
                    self._apply([*self._inputs, item])
                    return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required(IN_NAME): selector.TextSelector(),
                vol.Required(IN_TARGET): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["media_player", "remote"])
                ),
                vol.Required(CONF_ACTION): selector.TextSelector(),
                vol.Optional(CONF_TV_SOURCE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sources,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_TEST, default=False): selector.BooleanSelector(),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(
            step_id="shortcut", data_schema=schema, errors=errors
        )

    async def _test_shortcut(self, item: dict[str, Any]) -> str:
        """Fire a shortcut without saving it. Returns an options.error.* key.

        Detail goes to the log rather than into the message, so the string the
        user sees needs no placeholder — a description or error containing a
        {token} that is not supplied renders as empty text.
        """
        media = self._media
        if media is None:
            _LOGGER.error("Test: the integration is not loaded, nothing was sent")
            return "test_failed"
        try:
            await media.async_run_input(item, blocking=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Test failed: %s", err)
            return "test_failed"
        _LOGGER.info("Test sent: %s", item)
        return "test_sent"

    # ─── Manage ────────────────────────────────────────────────────────────────

    async def async_step_manage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Submenu: rename, reorder, remove."""
        if not self._inputs:
            return self.async_abort(reason="no_inputs")
        return self.async_show_menu(
            step_id="manage",
            menu_options=["rename", "reorder", "remove"],
        )

    async def async_step_rename(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Give an input a different display name.

        Only the label changes. What the input does — the TV source it switches
        to, or the entity and action it drives — is untouched, and so is its
        place in the cycle. The form comes back after each rename so several can
        be done in one visit.
        """
        inputs = self._inputs
        if not inputs:
            return self.async_abort(reason="no_inputs")

        errors: dict[str, str] = {}

        if user_input is not None:
            target_id = user_input[CONF_TARGET_INPUT]
            new_name = (user_input.get(CONF_NEW_NAME) or "").strip()

            if not new_name:
                errors[CONF_NEW_NAME] = "name_required"
            elif any(
                item.get(IN_NAME) == new_name and item[IN_ID] != target_id
                for item in inputs
            ):
                errors[CONF_NEW_NAME] = "name_taken"

            if not errors:
                for item in inputs:
                    if item[IN_ID] == target_id:
                        item[IN_NAME] = new_name
                        break
                self._apply(inputs)
                errors["base"] = "renamed"
                inputs = self._inputs

        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_INPUT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._input_options(),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_NEW_NAME): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="rename", data_schema=schema, errors=errors
        )

    async def async_step_reorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move one input through the cycle order.

        One input, one direction, applied straight away. The dropdown is
        renumbered every time the form comes back, so the list you are looking
        at is always the current order — move something, see it move, move the
        next thing. That beats a reorder widget you have to get right in one go.
        """
        inputs = self._inputs
        if len(inputs) < 2:
            return self.async_abort(reason="nothing_to_reorder")

        errors: dict[str, str] = {}

        if user_input is not None:
            target_id = user_input[CONF_TARGET_INPUT]
            direction = user_input[CONF_DIRECTION]
            index = next(
                (i for i, item in enumerate(inputs) if item[IN_ID] == target_id), None
            )
            if index is not None:
                item = inputs.pop(index)
                if direction == MOVE_TOP:
                    new_index = 0
                elif direction == MOVE_UP:
                    new_index = max(0, index - 1)
                elif direction == MOVE_DOWN:
                    new_index = min(len(inputs), index + 1)
                else:  # MOVE_BOTTOM
                    new_index = len(inputs)
                inputs.insert(new_index, item)
                self._apply(inputs)
                errors["base"] = "reordered"
                inputs = self._inputs

        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_INPUT): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._input_options(),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_DIRECTION, default=MOVE_UP): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[MOVE_TOP, MOVE_UP, MOVE_DOWN, MOVE_BOTTOM],
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="direction",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="reorder", data_schema=schema, errors=errors
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete inputs. Nothing is pre-ticked, so submitting empty is a no-op."""
        inputs = self._inputs
        if not inputs:
            return self.async_abort(reason="no_inputs")

        if user_input is not None:
            remove = set(user_input.get(CONF_REMOVE, []))
            self._apply([item for item in inputs if item[IN_ID] not in remove])
            return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Optional(CONF_REMOVE, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._input_options(),
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove", data_schema=schema)

    # ─── HAP command reference ─────────────────────────────────────────────────

    async def async_step_hap_commands(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the drawn remote listing every command remote.send_command takes.

        The artwork goes in as a description placeholder rather than being baked
        into strings.json, so it lives in one place and translators never see
        13 KB of path data. It is always supplied, so the description can never
        render as an empty string the way an unfilled placeholder would.
        """
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="hap_commands",
            data_schema=vol.Schema({}),
            description_placeholders={"remote": REMOTE_SVG},
        )

    # ─── Manual ────────────────────────────────────────────────────────────────

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the documentation link.

        A config flow cannot open a browser tab, so this is a step whose
        description is a markdown link — one click from inside the dialog. The
        same URL is behind the ? icon in the dialog header and the Documentation
        item in the integration's ⋮ menu, both wired up by manifest.json.
        """
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({}),
            description_placeholders={"url": DOCS_URL},
        )
