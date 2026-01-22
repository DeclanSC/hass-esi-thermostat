"""Config flow for ESI Thermostat integration."""
from __future__ import annotations

from typing import Any
import voluptuous as vol
import requests

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    LOGIN_URL
)

class ESIThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESI Thermostat."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                valid = await self._test_credentials(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD]
                )
                
                if valid:
                    options = {
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]
                    }
                    
                    return self.async_create_entry(
                        title=DEFAULT_NAME,
                        data={
                            CONF_EMAIL: user_input[CONF_EMAIL],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                        options=options,
                    )
                errors["base"] = "incorrect_email_or_password"
            except requests.exceptions.RequestException:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=DEFAULT_SCAN_INTERVAL_MINUTES
                ): cv.positive_int,
            }),
            errors=errors,
        )

    async def _test_credentials(self, email: str, password: str) -> bool:
        """Test if the provided credentials are valid."""
        try:
            response = await self.hass.async_add_executor_job(
                lambda: requests.post(
                    LOGIN_URL,
                    data={"email": email, "password": password},
                    timeout=10
                )
            )
            data = response.json()
            return data.get("statu") and bool(data.get("user", {}).get("token"))
        except requests.exceptions.RequestException:
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ESIThermostatOptionsFlow:
        """Get the options flow for this handler."""
        return ESIThermostatOptionsFlow(config_entry)


class ESIThermostatOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for ESI Thermostat."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL,
                        DEFAULT_SCAN_INTERVAL_MINUTES
                    )
                ): cv.positive_int,
            }),
        )
