"""Config flow — one-time setup wizard for HomeKit TV Remote."""
# Version: 1.0.0

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import entity_registry as er
import logging

_LOGGER = logging.getLogger(__name__)
DOMAIN = "homekit_tv_remote"


class HomeKitTVRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Show a dropdown of HomeKit Device TV entities and a name field.
        Aborts if no homekit_controller media_player entities are found —
        the TV must be paired via HomeKit Device integration first."""
        entity_reg = er.async_get(self.hass)

        tvs = {
            entity.entity_id: entity.name or entity.entity_id
            for entity in entity_reg.entities.values()
            if entity.platform == "homekit_controller" and entity.domain == "media_player"
        }

        if not tvs:
            return self.async_abort(reason="no_homekit_tv")

        if user_input is not None:
            entity_id = user_input["media_player_entity_id"]
            tv_name = user_input.get("tv_name", "Homekit TV")
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"TV Remote ({tv_name})",
                data={
                    "media_player_entity_id": entity_id,
                    "tv_name": tv_name,
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("media_player_entity_id"): vol.In(tvs),
                vol.Optional("tv_name", default="Homekit TV"): str,
            })
        )
