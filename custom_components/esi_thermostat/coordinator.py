"""Data update coordinator for ESI Thermostat."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from esi_controls_async import ESICentroAPI, ESILoginError, ESIProtocolError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from . import ESIConfigEntry

_LOGGER = logging.getLogger(__name__)


class ESIDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage ESI API data with configurable update interval."""

    config_entry: ESIConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ESIConfigEntry,
        email: str,
        password: str,
        scan_interval_minutes: int,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="esi_thermostat",
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.email = email
        self.password = password
        self.api = ESICentroAPI(session=async_get_clientsession(hass))

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API using the PyPI client."""
        try:
            if not self.api.available():
                await self.api.async_login(email=self.email, password=self.password)

            await self.api.async_update_devices()
            devices = self.api.get_devices() or []
            return {"devices": devices}

        except ESILoginError as err:
            # This is the only case that actually means "the email/password
            # are wrong" - only here should we ask the user to reauth.
            raise ConfigEntryAuthFailed(f"Invalid ESI credentials: {err}") from err
        except ESIProtocolError as err:
            # ESIServerError / ESIDeviceListError / ESINoAuthorization etc.
            # are raised by the library for timeouts, non-200 responses, and
            # unparsable JSON too - not just bad credentials. Treating these
            # as a plain (temporary) update failure instead of
            # ConfigEntryAuthFailed avoids nagging the user to re-enter a
            # password that was never actually wrong. The coordinator will
            # retry on schedule, and since the library clears its own token
            # internally on these errors, the next attempt logs back in
            # automatically with the credentials we already have.
            raise UpdateFailed(f"Error communicating with ESI API: {err}") from err
        except Exception as err:
            # DataUpdateCoordinator already logs UpdateFailed exceptions, so
            # there's no need to _LOGGER.error here too.
            raise UpdateFailed(f"Network error communicating with API: {err}") from err

    async def async_set_device_state(
        self, device_id: str, work_mode: int, temperature: float
    ) -> None:
        """Send state update to a specific device via the PyPI client."""
        try:
            if not self.api.available():
                await self.api.async_login(email=self.email, password=self.password)

            await self.api.async_set_work_mode(
                device_id=device_id,
                work_mode=work_mode,
                temperature=temperature,
            )
        except ESILoginError as err:
            raise ConfigEntryAuthFailed(f"Invalid ESI credentials: {err}") from err
        except ESIProtocolError as err:
            # Transient server/network error, not a credentials problem -
            # surface it as a normal failure so the entity's error handling
            # in climate.py rolls back the optimistic state and retries,
            # rather than kicking off a reauth flow.
            raise ValueError(f"API error: {err}") from err
        except Exception as err:
            raise ValueError(f"API error: {err}") from err
