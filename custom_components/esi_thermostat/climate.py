"""ESI Thermostat Climate Platform"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    ATTR_INSIDE_TEMPERATURE,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_WORK_MODE,
    WORK_MODE_MANUAL,
    WORK_MODE_AUTO,
    WORK_MODE_AUTO_TEMP_OVERRIDE,
    WORK_MODE_OFF,
)
from .coordinator import ESIDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize climate platform"""
    coordinator: ESIDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    if not coordinator.data:
        await coordinator.async_config_entry_first_refresh()

    entities = []
    for device in coordinator.data.get("devices", []):
        try:
            entities.append(
                EsiThermostat(
                    coordinator=coordinator,
                    device_id=device["device_id"],
                    name=device.get("device_name", DEFAULT_NAME),
                )
            )
        except KeyError:
            continue

    if entities:
        async_add_entities(entities)


class EsiThermostat(CoordinatorEntity[ESIDataUpdateCoordinator], ClimateEntity):
    """ESI Thermostat Entity"""

    _attr_has_entity_name = False
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.5

    WORK_MODE_TO_HVAC = {
        WORK_MODE_MANUAL: HVACMode.HEAT,
        WORK_MODE_AUTO: HVACMode.AUTO,
        WORK_MODE_AUTO_TEMP_OVERRIDE: HVACMode.AUTO,
        WORK_MODE_OFF: HVACMode.OFF,
    }

    HVAC_TO_WORK_MODE = {
        HVACMode.HEAT: WORK_MODE_MANUAL,
        HVACMode.AUTO: WORK_MODE_AUTO,
        HVACMode.OFF: WORK_MODE_OFF,
    }

    def __init__(self, coordinator: ESIDataUpdateCoordinator, device_id: str, name: str):
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._optimistic_target_temp: float | None = None
        self._optimistic_hvac_mode: HVACMode | None = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="ESI Heating",
            model="Smart Thermostat",
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode with optimistic caching support."""
        device = self._get_device()
        real_mode = HVACMode.HEAT

        if device:
            try:
                work_mode = int(device.get(ATTR_WORK_MODE, WORK_MODE_MANUAL))
                real_mode = self.WORK_MODE_TO_HVAC.get(work_mode, HVACMode.HEAT)
            except (TypeError, ValueError):
                pass

        if self._optimistic_hvac_mode is not None:
            if real_mode == self._optimistic_hvac_mode:
                self._optimistic_hvac_mode = None
            else:
                return self._optimistic_hvac_mode

        return real_mode

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action based on th_work field."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        device = self._get_device()
        if not device:
            return HVACAction.IDLE

        try:
            th_work = int(device.get("th_work", 0))
            if th_work == 1:
                return HVACAction.HEATING
        except (TypeError, ValueError):
            pass

        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Return the measured room temperature."""
        if device := self._get_device():
            for key in ("inside_temperature", "inside_temparature", "measured_temperature"):
                if key in device and device[key] is not None:
                    try:
                        val = float(device[key])
                        temp = val / 10 if val > 50 else val
                        if 5.0 <= temp <= 35.0:
                            return temp
                    except (ValueError, TypeError):
                        continue
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target setpoint temperature with strict safety bounds and optimistic support."""
        if self.hvac_mode == HVACMode.OFF:
            return None

        device = self._get_device()
        real_target = None

        if device:
            for key in ("current_temperature", "current_temprature", "target_temperature"):
                if key in device and device[key] is not None:
                    try:
                        val = float(device[key])
                        parsed = val / 10 if val > 50 else val
                        # Ensure the target sits within valid hardware range (5°C to 35°C) to filter out placeholder spikes like 50°C
                        if 5.0 <= parsed <= 35.0:
                            real_target = parsed
                            break
                    except (ValueError, TypeError):
                        continue

        if self._optimistic_target_temp is not None:
            if real_target is not None and abs(real_target - self._optimistic_target_temp) < 0.1:
                self._optimistic_target_temp = None
            else:
                return self._optimistic_target_temp

        return real_target

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode with immediate optimistic frontend update."""
        device = self._get_device()
        current_target = 20.0
        if device:
            for key in ("current_temperature", "current_temprature", "target_temperature"):
                if key in device and device[key] is not None:
                    try:
                        val = float(device[key])
                        parsed = val / 10 if val > 50 else val
                        if 5.0 <= parsed <= 35.0:
                            current_target = parsed
                            break
                    except (ValueError, TypeError):
                        continue

        self._optimistic_hvac_mode = hvac_mode

        if hvac_mode == HVACMode.OFF:
            target_temp = current_target
            work_mode = WORK_MODE_OFF
            self._optimistic_target_temp = None
        elif hvac_mode == HVACMode.AUTO:
            self._optimistic_target_temp = None
            target_temp = current_target
            work_mode = WORK_MODE_AUTO
        else:
            target_temp = current_target
            work_mode = WORK_MODE_MANUAL
            self._optimistic_target_temp = target_temp

        self.async_write_ha_state()
        await self._async_update_device(work_mode, target_temp, is_auto_switch=(hvac_mode == HVACMode.AUTO))

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature with immediate optimistic override."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        current_mode = self.hvac_mode
        if current_mode == HVACMode.OFF:
            work_mode = WORK_MODE_MANUAL
            self._optimistic_hvac_mode = HVACMode.HEAT
        elif current_mode == HVACMode.AUTO:
            work_mode = WORK_MODE_AUTO_TEMP_OVERRIDE
        else:
            work_mode = WORK_MODE_MANUAL

        target_temp = float(temperature)
        
        self._optimistic_target_temp = target_temp
        self.async_write_ha_state()

        await self._async_update_device(work_mode, target_temp, is_auto_switch=False)

    async def _async_update_device(self, work_mode: int, temperature: float, is_auto_switch: bool = False) -> None:
        """Centralized method to push updates to the API via the coordinator."""
        try:
            await self.coordinator.async_set_device_state(
                self._device_id, work_mode, temperature
            )
            
            if is_auto_switch:
                await asyncio.sleep(1.5)
                self._optimistic_target_temp = None
            else:
                await self.coordinator.async_request_refresh()
                await asyncio.sleep(1.5)

            await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error("Failed to update thermostat state: %s", err, exc_info=True)
            self._optimistic_target_temp = None
            self._optimistic_hvac_mode = None
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    def _get_device(self) -> dict | None:
        return next(
            (
                d
                for d in self.coordinator.data.get("devices", [])
                if d.get("device_id") == self._device_id
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._get_device() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose extra diagnostic attributes."""
        attrs = {}
        if device := self._get_device():
            if "th_work" in device:
                attrs["th_work"] = device.get("th_work")
        return attrs