"""Constants for ESI Thermostat integration."""
from typing import Final

from homeassistant.const import Platform

# Domain
DOMAIN: Final = "esi_thermostat"

# Platforms
PLATFORMS: Final[list[Platform]] = [Platform.CLIMATE]

# Configuration
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 3
CONF_SCAN_INTERVAL: Final = "scan_interval_minutes"
DEFAULT_NAME: Final = "ESI Thermostat"

# Device Attributes
ATTR_WORK_MODE: Final = "work_mode"

# The vendor API is inconsistent about field naming (and has shipped typos
# such as "temparature"/"temprature" historically), so we fall back through
# every known key. Defined once here so climate.py doesn't repeat the same
# tuple three times.
INSIDE_TEMPERATURE_KEYS: Final[tuple[str, ...]] = (
    "inside_temperature",
    "inside_temparature",
    "measured_temperature",
)
TARGET_TEMPERATURE_KEYS: Final[tuple[str, ...]] = (
    "current_temperature",
    "current_temprature",
    "target_temperature",
)

# Some API responses report temperature as a raw integer (e.g. 215 for
# 21.5C) instead of a float. Anything above this threshold is assumed to
# need dividing by TEMP_SCALE_DIVISOR.
RAW_VALUE_SCALE_THRESHOLD: Final = 50
TEMP_SCALE_DIVISOR: Final = 10

# Hardware safety bounds, also used to filter out placeholder/garbage values
# (e.g. a stray 50C+ reading) coming back from the API.
MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 35.0

# Work modes
WORK_MODE_MANUAL: Final = 5
WORK_MODE_AUTO: Final = 0
WORK_MODE_AUTO_TEMP_OVERRIDE: Final = 1
WORK_MODE_OFF: Final = 4