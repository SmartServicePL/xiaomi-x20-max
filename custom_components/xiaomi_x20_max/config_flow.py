"""Config flow for the standalone Xiaomi Robot Vacuum X20 Max integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .cloud import X20MaxCloud, X20MaxCloudError
from .const import (
    CLOUD_DATA_KEY,
    CONF_DID,
    CONF_FIRMWARE,
    CONF_NAME,
    DOMAIN,
    MODEL,
)


class X20MaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select only X20 Max robots from the integration's own cloud client."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        cloud: X20MaxCloud | None = self.hass.data.get(DOMAIN, {}).get(
            CLOUD_DATA_KEY
        )
        if cloud is None:
            cloud = X20MaxCloud(self.hass)
            self.hass.data.setdefault(DOMAIN, {})[CLOUD_DATA_KEY] = cloud
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
