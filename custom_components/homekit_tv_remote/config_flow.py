"""Config flow for HomeKit TV Remote."""
# Version: 1.0.0
#
# ROLE IN INTEGRATION:
# Handles the one-time setup wizard shown when the user adds the integration
# via Settings → Devices & Services → Add Integration.
#
# Step 1 (async_step_user):
#   - Scans the entity registry for media_player entities from homekit_controller
#     (these are the TV entities created when the user paired the TV via HomeKit Controller)
#   - Presents a form with a dropdown of those entities and a TV name field
#   - Creates the config entry with media_player_entity_id and tv_name in entry.data
#
# The config entry's entry.data (set here) is static — it does not change after setup.
# The config entry's entry.options (not set here, starts empty) is modified at runtime
# by button.py (custom_inputs), switch.py (debug_listen, debug_send), etc.

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import entity_registry as er
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "homekit_tv_remote"


class HomeKitTVRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Config flow that guides the user through one-time integration setup.
    VERSION = 1 is the config entry schema version.
    Incrementing this would require a migration function (not implemented).
    """

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """
        Handle the single setup step shown to the user.
        
        On first call (user_input=None): build and show the form.
        On submission (user_input set): validate and create the config entry.
        
        Scans the entity registry for homekit_controller media_player entities.
        These are the entities HA creates when a TV is paired via the
        HomeKit Controller integration. The user selects which one is their TV.
        
        Aborts with "no_homekit_tv" if no HomeKit Controller TV is found —
        the user must pair their TV via HomeKit Controller first.
        
        Sets unique_id to the selected entity_id to prevent duplicate entries
        for the same TV (_abort_if_unique_id_configured handles this).
        """
        entity_reg = er.async_get(self.hass)

        # Find all media_player entities created by homekit_controller
        tvs = {}
        for entity in entity_reg.entities.values():
            if entity.platform == "homekit_controller" and entity.domain == "media_player":
                tvs[entity.entity_id] = entity.name or entity.entity_id

        if not tvs:
            # No HomeKit Controller TV found — user must pair TV first
            return self.async_abort(reason="no_homekit_tv")

        if user_input is not None:
            entity_id = user_input["media_player_entity_id"]
            tv_name = user_input.get("tv_name", "Homekit TV")

            # Prevent creating two config entries for the same TV
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"TV Remote ({tv_name})",
                data={
                    "media_player_entity_id": entity_id,  # Used by remote.py to find HAP connection
                    "tv_name": tv_name                    # Used as display name by remote.py and media_player.py
                }
            )

        # Show the setup form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("media_player_entity_id"): vol.In(tvs),
                vol.Optional("tv_name", default="Homekit TV"): str,
            })
        )
