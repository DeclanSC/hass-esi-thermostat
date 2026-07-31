"""Config flow for ESI Thermostat integration."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from esi_controls_async import ESICentroAPI, ESIProtocolError

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)


class ESIThermostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESI Thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_email: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Previously nothing stopped the same ESI account being added
            # twice, which would create two coordinators hammering the same
            # cloud account. Abort early if it's already configured.
            self._async_abort_entries_match({CONF_EMAIL: user_input[CONF_EMAIL]})

            try:
                valid = await self._test_credentials(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except ESIProtocolError:
                errors["base"] = "incorrect_email_or_password"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if valid:
                    await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=DEFAULT_NAME,
                        data={
                            CONF_EMAIL: user_input[CONF_EMAIL],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                        options={
                            CONF_SCAN_INTERVAL: user_input.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                            )
                        },
                    )
                errors["base"] = "incorrect_email_or_password"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL_MINUTES
                    ): cv.positive_int,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication triggered by the integration."""
        self._reauth_email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that prompts the user to enter their new password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await self._test_credentials(
                    self._reauth_email, user_input[CONF_PASSWORD]
                )
            except ESIProtocolError:
                errors["base"] = "incorrect_password"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if valid:
                    reauth_entry = self._get_reauth_entry()
                    new_data = dict(reauth_entry.data)
                    new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                    return self.async_update_reload_and_abort(
                        reauth_entry, data=new_data
                    )
                errors["base"] = "incorrect_password"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self._reauth_email or ""},
        )

    async def _test_credentials(self, email: str, password: str) -> bool:
        """Test if the provided credentials are valid using the API library."""
        api = ESICentroAPI(session=async_get_clientsession(self.hass))
        await api.async_login(email=email, password=password)
        return api.available()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow handler."""
        return ESIThermostatOptionsFlow()


class ESIThermostatOptionsFlow(OptionsFlow):
    """Handle options flow for ESI Thermostat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                        ),
                    ): cv.positive_int,
                }
            ),
        )