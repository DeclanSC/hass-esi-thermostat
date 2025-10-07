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
from homeassistant.core import HomeAssistant
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
    SET_TEMP_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize climate platform"""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

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


class EsiThermostat(CoordinatorEntity, ClimateEntity):
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

    def __init__(self, coordinator, device_id: str, name: str):
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{device_id}"

        # Last known server-confirmed state
        self._last_confirmed_temp = None
        self._last_confirmed_mode = None
        self._last_confirmed_work_mode = None

        # Pending state not yet confirmed by server
        self._pending_temperature = None
        self._pending_hvac_mode = None

        # Track if we're changing mode
        self._is_mode_change = False

        # Queue for serializing updates
        self._update_queue = asyncio.Queue()
        self._update_processor_task = asyncio.create_task(self._process_updates())

        # Initialize with current state
        if device := self._get_device():
            try:
                self._last_confirmed_temp = float(device[ATTR_CURRENT_TEMPERATURE]) / 10
                work_mode = int(device.get(ATTR_WORK_MODE))
                self._last_confirmed_work_mode = work_mode
                self._last_confirmed_mode = self.WORK_MODE_TO_HVAC.get(
                    work_mode, HVACMode.HEAT
                )
            except (TypeError, ValueError):
                pass

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="ESI Heating",
            model="Smart Thermostat",
        )

    async def _process_updates(self) -> None:
        """Process update requests sequentially from the queue."""
        while True:
            try:
                await self._update_queue.get()
                await self._async_perform_update()
            except asyncio.CancelledError:
                return
            except Exception as e:
                _LOGGER.error("Error processing update: %s", e, exc_info=True)
            finally:
                self._update_queue.task_done()

    @property
    def hvac_mode(self) -> HVACMode:
        if self._pending_hvac_mode is not None:
            return self._pending_hvac_mode
        if self._last_confirmed_mode is not None:
            return self._last_confirmed_mode
        if device := self._get_device():
            try:
                work_mode = int(device.get(ATTR_WORK_MODE))
                return self.WORK_MODE_TO_HVAC.get(work_mode, HVACMode.HEAT)
            except (TypeError, ValueError):
                return HVACMode.HEAT
        return HVACMode.HEAT

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
        except (TypeError, ValueError):
            th_work = 0

        if th_work == 1:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        if device := self._get_device():
            try:
                return float(device[ATTR_INSIDE_TEMPERATURE]) / 10
            except (ValueError, TypeError):
                return None
        return None

    @property
    def target_temperature(self) -> float | None:
        if self._pending_temperature is not None:
            return self._pending_temperature
        if self._last_confirmed_temp is not None:
            return self._last_confirmed_temp
        if device := self._get_device():
            try:
                return float(device[ATTR_CURRENT_TEMPERATURE]) / 10
            except (ValueError, TypeError):
                return None
        return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._pending_hvac_mode = hvac_mode
        self._is_mode_change = True

        if hvac_mode == HVACMode.OFF:
            self._pending_temperature = 5.0
        elif hvac_mode == HVACMode.HEAT:
            temp = (
                self._pending_temperature
                or self._last_confirmed_temp
                or self.target_temperature
                or self.current_temperature
                or 20.0
            )
            self._pending_temperature = temp
        else:
            self._pending_temperature = None

        self.async_write_ha_state()
        await self._enqueue_update()

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._pending_temperature = temperature
        self._is_mode_change = False
        current_mode = self.hvac_mode
        if current_mode == HVACMode.OFF:
            self._pending_hvac_mode = HVACMode.HEAT
            self._is_mode_change = True
        elif current_mode == HVACMode.AUTO:
            self._pending_hvac_mode = HVACMode.AUTO
        else:
            self._pending_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()
        await self._enqueue_update()

    async def _enqueue_update(self) -> None:
        try:
            while not self._update_queue.empty():
                self._update_queue.get_nowait()
                self._update_queue.task_done()
            self._update_queue.put_nowait("update")
        except Exception as e:
            _LOGGER.error("Failed to enqueue update: %s", e)

    async def _async_perform_update(self) -> None:
        try:
            target_temp = self._pending_temperature
            target_mode = self._pending_hvac_mode
            if target_mode is None:
                return
            if target_temp is None and target_mode != HVACMode.AUTO:
                target_temp = (
                    self._last_confirmed_temp
                    or self.target_temperature
                    or self.current_temperature
                    or 20.0
                )
            if target_mode == HVACMode.AUTO and target_temp is None:
                if device := self._get_device():
                    try:
                        target_temp = float(device[ATTR_CURRENT_TEMPERATURE]) / 10
                    except (TypeError, ValueError):
                        target_temp = self._last_confirmed_temp or 20.0
                else:
                    target_temp = self._last_confirmed_temp or 20.0
            if target_mode == HVACMode.AUTO:
                if not self._is_mode_change and self.hvac_mode == HVACMode.AUTO:
                    work_mode = WORK_MODE_AUTO_TEMP_OVERRIDE
                else:
                    work_mode = WORK_MODE_AUTO
            else:
                work_mode = self.HVAC_TO_WORK_MODE.get(
                    target_mode, WORK_MODE_MANUAL
                )
            api_temp = int(target_temp * 10)
            await self._send_api_request(work_mode, api_temp)

            # Immediately refresh to get updated state
            await self.coordinator.async_request_refresh()

            # Always perform a follow-up refresh after 3 seconds
            await asyncio.sleep(3.0)
            await self.coordinator.async_request_refresh()

            self._is_mode_change = False
        except Exception as err:
            _LOGGER.error("Update failed: %s", err, exc_info=True)
            self._pending_temperature = None
            self._pending_hvac_mode = None
            self._is_mode_change = False
            await self.coordinator.async_request_refresh()

    async def _send_api_request(self, work_mode: int, temperature: int) -> None:
        await self.hass.async_add_executor_job(
            self._set_work_mode, work_mode, temperature
        )

    def _set_work_mode(self, work_mode: int, temperature: int) -> None:
        import requests

        if not self.coordinator.token:
            raise ValueError("No auth token")

        params = {
            "device_id": self._device_id,
            "user_id": self.coordinator.user_id,
            "current_temprature": temperature,
            "work_mode": work_mode,
            "messageId": "261a",
            "token": self.coordinator.token,
        }
        try:
            response = requests.post(SET_TEMP_URL, params=params, timeout=5)
            response.raise_for_status()
            response_data = response.json()
        except Exception as err:
            raise ValueError(f"API request failed: {err}") from err

        if not response_data.get("statu"):
            error_msg = response_data.get("message", "Unknown error")
            error_code = response_data.get("error_code")
            if error_code == 7:
                raise ValueError(f"Work mode change rejected: {error_msg}")
            else:
                raise ValueError(f"API error: {response_data}")

    def _handle_coordinator_update(self) -> None:
        device = self._get_device()
        if not device:
            super()._handle_coordinator_update()
            return
        try:
            device_temp = float(device[ATTR_CURRENT_TEMPERATURE]) / 10
            device_work_mode = int(device.get(ATTR_WORK_MODE))
            device_mode = self.WORK_MODE_TO_HVAC.get(device_work_mode, HVACMode.HEAT)
            self._last_confirmed_temp = device_temp
            self._last_confirmed_mode = device_mode
            self._last_confirmed_work_mode = device_work_mode
            if (
                self._pending_temperature is not None
                and abs(device_temp - self._pending_temperature) < 0.5
            ):
                self._pending_temperature = None
            if (
                self._pending_hvac_mode is not None
                and device_mode == self._pending_hvac_mode
            ):
                self._pending_hvac_mode = None
        except (TypeError, ValueError):
            pass
        self.async_write_ha_state()
        super()._handle_coordinator_update()

    def _get_device(self) -> dict | None:
        return next(
            (
                d
                for d in self.coordinator.data.get("devices", [])
                if d["device_id"] == self._device_id
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._get_device() is not None
            and self.coordinator.token is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose extra diagnostic attributes."""
        attrs = {}
        if device := self._get_device():
            if "th_work" in device:
                attrs["th_work"] = device.get("th_work")
        return attrs

    async def async_will_remove_from_hass(self) -> None:
        if self._update_processor_task:
            self._update_processor_task.cancel()
            try:
                await self._update_processor_task
            except asyncio.CancelledError:
                pass
