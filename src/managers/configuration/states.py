"""State management classes for ConfigurationManager."""

from core.app_typing import Any, Optional


class ValidationState:
    """Tracks async WiFi credential validation and update checking."""

    def __init__(self) -> None:
        self.state: str = "idle"  # idle | validating_wifi | checking_updates | success | error
        self.result: Optional[dict[str, Any]] = None
        self.started_at: Optional[float] = None
        self.trigger: bool = False
        self.activation_mode: Optional[str] = None  # "continue" (no update) | "update" (download update)


class UpdateState:
    """Tracks firmware update download and installation progress."""

    def __init__(self) -> None:
        self.state: str = "idle"  # idle | downloading | verifying | unpacking | restarting | error
        self.trigger: bool = False
        self.progress_message: Optional[str] = None
        self.progress_pct: Optional[float] = None

        # Progress tracking for notification throttling
        self._last_notify_state: Optional[str] = None
        self._last_notify_message: Optional[str] = None
        self._last_notify_pct: Optional[float] = None
        self._last_pct_value: Optional[float] = None


class PortalState:
    """Tracks setup portal session state."""

    def __init__(self) -> None:
        self.setup_complete: bool = False
        self.user_connected: bool = False
        self.last_request_time: Optional[float] = None
        self.pending_ready_at: Optional[float] = None  # monotonic timestamp for scheduled activation
        self.last_connection_error: Optional[str | dict[str, Any]] = None


class PendingCredentials:
    """Stores credentials awaiting validation."""

    def __init__(self) -> None:
        self.ssid: Optional[str] = None
        self.password: Optional[str] = None

    def clear(self) -> None:
        """Clear stored credentials."""
        self.ssid = None
        self.password = None

    def set(self, ssid: str, password: str) -> None:
        """Store credentials for validation."""
        self.ssid = ssid
        self.password = password

    def has_credentials(self) -> bool:
        """Check if credentials are set."""
        return bool(self.ssid and self.password)
