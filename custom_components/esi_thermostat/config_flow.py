"""Config flow for ESI Thermostat integration."""
from __future__ import annotations

from typing import Any
from collections.abc import Mapping
import voluptuous as vol

from esi_controls_async import ESICentroAPI, ESIProtocolError

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
)


class ESIThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESI Thermostat."""

    VERSION = 1
    
    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_email: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await self._test_credentials(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )

                if valid:
                    return self.async_create_entry(
                        title=DEFAULT_NAME,
                        data={
                            CONF_EMAIL: user_input[CONF_EMAIL],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                        options={
                            CONF_SCAN_INTERVAL: user_input.get(
                                CONF_SCAN_INTERVAL,
                                DEFAULT_SCAN_INTERVAL_MINUTES,
                            )
                        },
                    )
                errors["base"] = "incorrect_email_or_password"

            except ESIProtocolError:
                errors["base"] = "incorrect_email_or_password"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=DEFAULT_SCAN_INTERVAL_MINUTES,
                    ): cv.positive_int,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauthentication triggered by the integration."""
        self.context["title_placeholders"] = {"name": entry_data.get(CONF_EMAIL)}
        self._reauth_email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that prompts the user to enter their new password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await self._test_credentials(
                    self._reauth_email, user_input[CONF_PASSWORD]
                )

                if valid:
                    entry = self.hass.config_entries.async_get_entry(
                        self.context["entry_id"]
                    )
                    
                    new_data = dict(entry.data)
                    new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                    self.hass.config_entries.async_update_entry(
                        entry, data=new_data
                    )
                    
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                
                errors["base"] = "incorrect_password"

            except ESIProtocolError:
                errors["base"] = "incorrect_password"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _test_credentials(self, email: str, password: str) -> bool:
        """Test if the provided credentials are valid using the API library."""
        api = ESICentroAPI(session=async_get_clientsession(self.hass))
        await api.async_login(email=email, password=password)
        return api.available()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return ESIThermostatOptionsFlow()


class ESIThermostatOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for ESI Thermostat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL_MINUTES,
                        ),
                    ): cv.positive_int,
                }
            ),
        )