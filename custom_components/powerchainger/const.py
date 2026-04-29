"""Constants for the Powerchainger integration."""

DOMAIN = "powerchainger"
CONF_USER = "user"
CONF_WEBSOCKET_URL = "websocket_url"
CONF_DRY_RUN = "dry_run"
CONF_SEND_DATA = "send_data"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SELECTED_ENTITIES = "selected_entities"

DEFAULT_SCAN_INTERVAL = 1
DEFAULT_BUFFER_MAX_SIZE = 10_000
DEFAULT_WEBSOCKET_URL = "ws://146.190.226.254:5000"

# Poll selected HomeWizard entities directly at genuine 1 Hz.
DIRECT_HOMEWIZARD_POLL_INTERVAL_SECONDS = 1
# Per-device HomeWizard request timeout so one slow endpoint cannot stall 1 Hz cadence.
DIRECT_HOMEWIZARD_REQUEST_TIMEOUT_SECONDS = 0.9
