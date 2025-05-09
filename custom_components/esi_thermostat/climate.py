from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any, Final, Dict
import asyncio

import requests
import voluptuous as vol

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    LOGIN_URL,
    DEVICE_LIST_URL,
    SET_TEMP_URL,
    DEFAULT_NAME,
)

_LOGGER: Final = logging.getLogger(__name__)

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)

class ESIDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage ESI API data with configurable update interval."""

    def __init__(self, hass: HomeAssistant, email: str, password: str, scan_interval_minutes: int):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.email = email
        self.password = password
        self.token: str | None = None
        self.user_id: str | None = None
        self._pending_updates: Dict[str, int] = {}  # device_id: temperature*10

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        try:
            if not self.token:
                await self._async_login()

            devices = await self._async_get_devices()
            
            # Apply pending updates to device data
            for device in devices:
                if device["device_id"] in self._pending_updates:
                    device["current_temprature"] = self._pending_updates[device["device_id"]]
            
            return {"devices": devices}

        except Exception as err:
            _LOGGER.error("Update failed: %s", err, exc_info=True)
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _async_login(self) -> None:
        """Authenticate with ESI API."""
        payload = {
            "password": self.password,
            "email": self.email
        }

        response = await self.hass.async_add_executor_job(
            lambda: requests.post(LOGIN_URL, data=payload, timeout=15)
        )
        data = response.json()

        if not data.get("statu") or not data.get("user", {}).get("token"):
            raise UpdateFailed("Login failed")

        self.token = data["user"]["token"]
        self.user_id = str(data["user"].get("id", ""))

    async def _async_get_devices(self) -> list[dict[str, Any]]:
        """Retrieve device list from API."""
        params = {
            "user_id": self.user_id,
            "token": self.token,
            "device_type": 1,
            "pageSize": 100,
        }

        response = await self.hass.async_add_executor_job(
            lambda: requests.post(DEVICE_LIST_URL, params=params, timeout=15)
        )

        data = response.json()

        if not data.get("statu") or "devices" not in data:
            raise UpdateFailed("Device list fetch failed")

        return data["devices"]

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up ESI Thermostat platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Wait for initial data if not yet loaded
    if not coordinator.data:
        await coordinator.async_config_entry_first_refresh()
    
    # Get devices with fallback to empty list
    devices = coordinator.data.get("devices", [])
    
    # Create entities with proper naming
    entities = []
    for device in devices:
        try:
            device_name = device.get("device_name", DEFAULT_NAME)
            entity = EsiThermostat(
                coordinator=coordinator,
                device_id=device["device_id"],
                name=device_name
            )
            entities.append(entity)
        except KeyError as err:
            _LOGGER.error("Skipping device due to missing data: %s", err)
            continue
    
    if not entities:
        _LOGGER.warning("No ESI Thermostat devices found")
        return
    
    async_add_entities(entities)
    
    # Add update listener for config option changes
    entry.async_on_unload(
        entry.add_update_listener(async_update_options)
    )
    
class EsiThermostat(CoordinatorEntity, ClimateEntity):
    """Representation of an ESI Thermostat."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        coordinator: ESIDataUpdateCoordinator,
        device_id: str,
        name: str,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_name = name
        self._attr_hvac_mode = HVACMode.HEAT
        self._pending_temperature: float | None = None
        self._is_setting = False

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="ESI Heating",
            model="Smart Thermostat",
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if device := self._get_device():
            try:
                return float(device["inside_temparature"]) / 10
            except (KeyError, ValueError, TypeError):
                return None
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self._pending_temperature is not None:
            return self._pending_temperature
        if device := self._get_device():
            try:
                return float(device["current_temprature"]) / 10
            except (KeyError, ValueError, TypeError):
                return None
        return None

    def _get_device(self) -> dict[str, Any] | None:
        """Get device data from coordinator."""
        devices = self.coordinator.data.get("devices", [])
        return next((d for d in devices if d["device_id"] == self._device_id), None)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        if self._is_setting:
            _LOGGER.debug("Already processing a temperature change")
            return

        self._is_setting = True
        self._pending_temperature = temperature
        self.async_write_ha_state()

        try:
            # Ensure pending updates exists
            if not hasattr(self.coordinator, '_pending_updates'):
                self.coordinator._pending_updates = {}
                
            # Store pending update
            self.coordinator._pending_updates[self._device_id] = int(temperature * 10)
            
            # Make API call
            await self.hass.async_add_executor_job(
                self._set_temperature, temperature
            )
            
            # Force refresh
            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error("Error setting temperature: %s", err)
            self._pending_temperature = None
            self.async_write_ha_state()
            raise

        finally:
            self._is_setting = False
            self._pending_temperature = None

    def _set_temperature(self, temperature: float) -> None:
        """Send temperature setting to API."""
        if not self.coordinator.token:
            raise ValueError("No auth token")

        params = {
            "device_id": self._device_id,
            "user_id": self.coordinator.user_id,
            "current_temprature": int(temperature * 10),
            "messageId": "261a",
            "work_mode": 1,
            "token": self.coordinator.token,
        }

        response = requests.post(
            SET_TEMP_URL,
            params=params,
            timeout=10
        )

        if not response.json().get("statu"):
            raise ValueError("Temperature set failed")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._get_device() is not None
            and self.coordinator.token is not None
        )