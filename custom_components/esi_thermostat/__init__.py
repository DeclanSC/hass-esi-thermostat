"""The ESI Thermostat integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES, PLATFORMS
from .coordinator import ESIDataUpdateCoordinator

# Config entries now carry their runtime object directly instead of a
# hass.data[DOMAIN][entry_id] dict. This also gives us proper typing on
# entry.runtime_data everywhere it's used (climate.py, diagnostics.py).
type ESIConfigEntry = ConfigEntry[ESIDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ESIConfigEntry) -> bool:
    """Set up ESI Thermostat from a config entry."""
    scan_interval_minutes = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
    )

    coordinator = ESIDataUpdateCoordinator(
        hass,
        entry,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        scan_interval_minutes,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to initialize: {err}") from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ESIConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ESIConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)