"""Constants for the HLK-2412 integration."""

from enum import StrEnum

DOMAIN = "hlk2412"
MANUFACTURER = "HiLink"

DEFAULT_NAME = "HLK-2412"

class SupportedModels(StrEnum):
    """Supported models."""

    HLK2412 = "hlk2412"

DEFAULT_RETRY_COUNT = 3

CONF_RETRY_COUNT = "retry_count"
