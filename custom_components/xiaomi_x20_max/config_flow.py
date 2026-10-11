"""Config flow for the standalone Xiaomi Robot Vacuum X20 Max integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult

from .cloud import X20MaxAuthError, X20MaxCloud, X20MaxCloudError
from .const import (
    CLOUD_DATA_KEY,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    DOMAIN,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)


class X20MaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select only X20 Max robots from the integration's own cloud client."""

    VERSION = 2

    def _cloud(self) -> X20MaxCloud:
        cloud: X20MaxCloud | None = self.hass.data.get(DOMAIN, {}).get(
            CLOUD_DATA_KEY
        )
        if cloud is None:
            cloud = X20MaxCloud(self.hass)
            self.hass.data.setdefault(DOMAIN, {})[CLOUD_DATA_KEY] = cloud
        return cloud

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cloud = self._cloud()
        try:
            if not cloud.ready:
                await cloud.async_initialize()
            robots = await cloud.async_list_robots()
        except X20MaxCloudError:
            return self.async_abort(reason="no_auth")

        by_did = {item["did"]: item for item in robots}
        choices = {
            did: f"{item['name']} ({did})" for did, item in by_did.items()
        }
        if not choices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            did = user_input[CONF_DID]
            robot = by_did.get(did)
            if robot is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_DID): vol.In(choices)}
                    ),
                    errors={"base": "invalid_device"},
                )
            await self.async_set_unique_id(did)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{robot['name']} X20 Max",
                data={
                    CONF_DID: did,
                    CONF_NAME: robot["name"],
                    "model": MODEL,
                    CONF_FIRMWARE: robot.get("firmware"),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_DID): vol.In(choices)}
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Xiaomi rejected the private OAuth grant."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import the grant again after the user signed in in Xiaomi Home.

        This integration has no own Xiaomi login: it uses the OAuth grant of
        the official Xiaomi Home integration. Re-authentication therefore
        means signing in again there and importing the new grant here.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            cloud = self._cloud()
            try:
                await cloud.async_reimport()
                robots = await cloud.async_list_robots()
            except X20MaxAuthError:
                errors["base"] = "reauth_failed"
            except X20MaxCloudError as err:
                _LOGGER.debug("Re-authentication check failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not any(
                    robot["did"] == entry.data.get(CONF_DID) for robot in robots
                ):
                    errors["base"] = "robot_not_found"
                else:
                    # The grant is shared by every X20 Max entry; reload the
                    # others that stopped on the same authentication error.
                    for other in self._async_current_entries():
                        if other.entry_id != entry.entry_id and other.state in (
                            ConfigEntryState.SETUP_ERROR,
                            ConfigEntryState.SETUP_RETRY,
                        ):
                            self.hass.config_entries.async_schedule_reload(
                                other.entry_id
                            )
                    return self.async_update_reload_and_abort(entry)

        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
        )
