"""Diagnostics support for ESI Thermostat."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ESIConfigEntry

TO_REDACT = {"device_id", "serial_number", "mac", "email"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ESIConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "config_entry": {
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "options": dict(entry.options),
        },
        "coordinator_data": async_redact_data(coordinator.data, TO_REDACT),
    }