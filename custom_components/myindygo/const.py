"""Constants for the MyIndygo (Solem) integration."""

from typing import Final

DOMAIN: Final = "myindygo"

API_BASE_URL: Final = "https://myindygo.com"
# API version expected by the server, as sent by the MyIndygo app 3.17.x.
API_VERSION: Final = "2.7"

# OAuth client identifier ("client_id:client_secret") of the MyIndygo mobile app.
# It is the same for every user (shipped in the public app package); the server rejects
# a login without it (HTTP 401). It can be overridden in the integration options in case
# Solem changes it.
DEFAULT_CLIENT_ID: Final = "5d1c5bb0b4acd1c748988085:LUowRAajRhZb6NZYqVCFkaLC"

CONF_CLIENT_ID: Final = "client_id"
CONF_LIVE_INTERVAL: Final = "live_interval"
CONF_PLATFORM_INTERVAL: Final = "platform_interval"

# Polling intervals, in minutes. Kept conservative: the vendor's rate limits are unknown.
DEFAULT_LIVE_INTERVAL: Final = 2
MIN_LIVE_INTERVAL: Final = 1
MAX_LIVE_INTERVAL: Final = 30
DEFAULT_PLATFORM_INTERVAL: Final = 15
MIN_PLATFORM_INTERVAL: Final = 10
MAX_PLATFORM_INTERVAL: Final = 60

MANUFACTURER: Final = "Solem"

# Solem manufacturer types (hexadecimal strings in the API).
MANUFACTURER_TYPE_GATEWAY_LR_MB_10: Final = "10"
MANUFACTURER_TYPE_POOL_CONTROLLER_LR_PC: Final = "15"
MANUFACTURER_TYPE_IPX: Final = "FD"

MODEL_NAMES: Final = {
    MANUFACTURER_TYPE_GATEWAY_LR_MB_10: "LR-MB-10",
    MANUFACTURER_TYPE_POOL_CONTROLLER_LR_PC: "LR-PC",
    MANUFACTURER_TYPE_IPX: "IPX",
}
