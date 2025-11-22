"""
ConnectionManager - Centralized WiFi connection management with progressive backoff and interrupt support.

This module encapsulates all WiFi connection behavior for the device, including:
- Station mode connection with progressive exponential backoff
- Access Point mode for the setup portal
- Button interrupt support during connection attempts
- Connection state management
- WiFi radio lifecycle management via WiFiRadioController
- Graceful error handling

ConnectionManager is a singleton - use ConnectionManager.instance() to access it.
"""

import json
import os
import ssl  # type: ignore[import-not-found]  # CircuitPython-only module
import time

import socketpool  # type: ignore[import-not-found]  # CircuitPython-only module

from app_typing import Any, Callable, Generator
from logging_helper import logger
from manager_base import ManagerBase
from scheduler import Scheduler
from utils import suppress
from wifi_radio_controller import WiFiRadioController


class AuthenticationError(Exception):
    """Raised when WiFi authentication fails due to invalid credentials."""

    pass


class ConnectionManager(ManagerBase):
    """
    Singleton manager for all WiFi operations.

    Encapsulates station mode, AP mode, and all WiFi radio state management.
    Use instance() to access the singleton instance.
    """

    _instance = None

    # Connection timeout for a single attempt (seconds)
    CONNECTION_TIMEOUT = 10

    # Exponential backoff configuration
    BASE_BACKOFF_DELAY = 1.5  # Initial delay (seconds): 1.5s
    BACKOFF_MULTIPLIER = 2  # Doubles each retry: 1.5s, 3s, 6s, 12s, 24s, 48s...
    MAX_BACKOFF_TIME = 60 * 30  # Cap at 30 minutes between retries

    @classmethod
    def instance(cls, radio_controller: Any = None) -> "ConnectionManager":
        """
        Get the singleton instance of ConnectionManager.

        Supports smart reinitialization: if radio_controller changes (e.g., in tests),
        the existing instance will be shut down and reinitialized.

        Args:
            radio_controller: Optional WiFiRadioController instance for DI (only used on first call or when different)

        Returns:
            ConnectionManager: The singleton instance
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._init(radio_controller)
        else:
            # Check if reinitialization is needed (different radio_controller)
            if not cls._instance._is_compatible_with(radio_controller=radio_controller):
                cls._instance.shutdown()
                cls._instance._init(radio_controller)
        return cls._instance

    # Retry state file
    RETRY_STATE_FILE = "/wifi_retry_state.json"

    def _init(self, radio_controller: Any = None) -> None:
        """
        Internal initialization method.

        Args:
            radio_controller: Optional WiFiRadioController instance for dependency injection
        """
        self.logger = logger("wicid.wifi")

        # Store init parameters for compatibility checking
        self._init_radio_controller = radio_controller

        self.session = None
        self._connected = False
        self._ap_active = False
        self._credentials = None  # Cached credentials from secrets.json
        self._pre_ap_connected = False  # Track connection state before AP mode

        # Hardware abstraction for the WiFi radio (injectable for tests)
        self._radio_controller = radio_controller or WiFiRadioController()
        self._radio = self._radio_controller.radio

        self._initialized = True
        self.logger.debug("ConnectionManager initialized")

    def __init__(self, radio_controller: Any = None) -> None:
        """
        Direct instantiation is discouraged.
        Use instance() instead for singleton pattern.

        This is kept for backwards compatibility but will create independent instances.
        """
        # Guard against re-initialization
        if getattr(self, "_initialized", False):
            return
        # If _instance is already set, don't override it
        if ConnectionManager._instance is None:
            ConnectionManager._instance = self
        self._init(radio_controller)

    def _is_compatible_with(self, radio_controller: Any = None) -> bool:
        """
        Check if this instance is compatible with the given radio_controller.

        Args:
            radio_controller: Optional WiFiRadioController instance to check compatibility with

        Returns:
            bool: True if instance is compatible, False if reinit needed
        """
        # If not initialized yet, always compatible (will initialize)
        if not getattr(self, "_initialized", False):
            return True

        # Compare stored init parameters with requested ones
        # Same object references or both None means compatible
        radio_compat = (self._init_radio_controller is None and radio_controller is None) or (
            self._init_radio_controller is radio_controller
        )

        return radio_compat

    def reset_radio_to_station_mode(self) -> None:
        """
        Reset WiFi radio to station mode, clearing any AP mode state.
        This ensures the radio is ready for client connections.

        Call this after exiting setup/AP mode to restore normal operation.
        """
        try:
            self.logger.debug("Resetting WiFi radio to station mode")
            self._radio.enabled = False
            time.sleep(0.3)
            self._radio.enabled = True
            time.sleep(0.3)
            self.logger.debug("WiFi radio reset complete")
        except Exception as e:
            self.logger.warning(f"Error resetting radio: {e}")

    # --- Retry State Management ---

    def load_retry_count(self) -> int:
        """
        Load the retry count from persistent storage.

        Returns:
            int: Current retry count (0 if file doesn't exist or is corrupt)
        """
        try:
            with open(self.RETRY_STATE_FILE) as f:
                data = json.load(f)
                return int(data.get("retry_count", 0))
        except (OSError, ValueError, KeyError):
            return 0

    def increment_retry_count(self) -> int:
        """
        Increment the retry count and save to persistent storage.

        Returns:
            int: New retry count value
        """
        current = self.load_retry_count()
        new_count = current + 1
        self._save_retry_count(new_count)
        return new_count

    def clear_retry_count(self) -> None:
        """Clear the retry count (set to 0) and save to persistent storage."""
        self._save_retry_count(0)

    def _save_retry_count(self, count: int) -> None:
        """
        Save retry count to persistent storage.

        Args:
            count: Integer retry count to save
        """
        try:
            data = {"retry_count": count}
            with open(self.RETRY_STATE_FILE, "w") as f:
                json.dump(data, f)
            os.sync()
        except OSError as e:
            self.logger.warning(f"Failed to save retry state: {e}")

    # --- Secrets/Credentials Management ---

    def load_credentials(self) -> dict[str, str] | None:
        """
        Load WiFi credentials from secrets.json.

        Returns:
            dict: Credentials dict with 'ssid', 'password', 'weather_zip' keys
                  Returns None if file doesn't exist or is invalid
        """
        try:
            with open("/secrets.json") as f:
                secrets = json.load(f)

            # Validate required fields
            if not secrets.get("ssid") or not secrets.get("password"):
                return None

            self._credentials = secrets
            return secrets

        except (OSError, ValueError, KeyError):
            self._credentials = None
            return None

    def get_credentials(self) -> dict[str, str] | None:
        """
        Get cached credentials or load from file if not cached.

        Returns:
            dict: Credentials dict or None if not available
        """
        if self._credentials is None:
            return self.load_credentials()
        return self._credentials

    def clear_credentials_cache(self) -> None:
        """Clear the cached credentials (forces reload from file on next access)."""
        self._credentials = None

    async def ensure_connected(self, timeout: float | None = None) -> tuple[bool, str | None]:
        """
        Ensure WiFi is connected using credentials from secrets.json.

        High-level method that:
        1. Checks if already connected
        2. Loads credentials from secrets.json
        3. Attempts connection with backoff retry
        4. Returns success/failure status

        This method handles all connection logic internally and returns status
        rather than raising exceptions (except for unrecoverable errors).

        Args:
            timeout: Optional timeout in seconds for connection attempts
                     None means retry indefinitely

        Returns:
            tuple: (success: bool, error_message: str or None)

        Raises:
            KeyboardInterrupt: If button pressed during connection
            Exception: Only for unrecoverable errors (hardware failure, etc.)
        """
        # Check if already connected
        if self.is_connected():
            self.logger.info("Already connected to WiFi")
            return True, ""

        # Load credentials
        credentials = self.get_credentials()
        if not credentials:
            error_msg = "No credentials found"
            self.logger.error(error_msg)
            return False, error_msg

        ssid = credentials.get("ssid", "").strip()
        password = credentials.get("password", "")

        if not ssid or not password:
            error_msg = "Invalid credentials"
            self.logger.error(error_msg)
            return False, error_msg

        self.logger.info(f"Connecting to '{ssid}'...")

        # Attempt connection with backoff
        try:
            result = await self.connect_with_backoff(ssid, password, timeout=timeout)
            success: bool
            connect_error: str | None
            success, connect_error = result

            if success:
                self.logger.info(f"Connected to '{ssid}'")
                self.clear_retry_count()
                return True, None
            else:
                error_msg_final = connect_error if connect_error is not None else "Connection failed"
                self.logger.error(f"Connection failed: {error_msg_final}")
                return False, error_msg_final

        except AuthenticationError as e:
            error_msg = f"Authentication failed: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    async def connect_with_backoff(
        self,
        ssid: str,
        password: str,
        timeout: float | None = None,
        on_retry: Callable[[int, float], None] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Connect to WiFi with progressive exponential backoff retry logic.
        Automatically interrupts when the InputManager reports a button press.

        Retries with exponential backoff capped at MAX_BACKOFF_TIME (30 minutes).
        If timeout is specified, gives up after that duration. Otherwise retries indefinitely.

        Authentication failures require 3 consecutive occurrences before raising
        AuthenticationError. This tolerates transient auth failures (router/radio states)
        while still failing fast (~6-7 seconds) on truly invalid credentials.

        Network unreachable errors, timeouts, and generic errors are treated as transient
        and will be retried with backoff until timeout is reached.
        User can manually trigger setup mode via button press.

        Args:
            ssid: WiFi network SSID
            password: WiFi network password
            timeout: Optional timeout in seconds (None for indefinite retry)
            on_retry: Optional callback function called on each retry attempt(attempt_num, wait_time)

        Returns:
            tuple: (success: bool, error_message: str or None)

        Raises:
            KeyboardInterrupt: If button is pressed during connection attempt
            AuthenticationError: If 3 consecutive authentication failures occur
        """
        attempts = 0
        start_time = time.monotonic()  # Track when we started trying
        auth_failure_count = 0  # Track consecutive authentication failures

        while True:
            attempts += 1

            try:
                self.logger.debug(f"Connection attempt #{attempts} to '{ssid}'")

                # Check for button interrupt before attempting connection
                from input_manager import InputManager

                input_mgr = InputManager.instance()
                if input_mgr.is_pressed():
                    raise KeyboardInterrupt("Connection interrupted by button press")

                # Convert to bytes to satisfy buffer protocol requirement
                ssid_b = bytes(ssid, "utf-8")
                password_b = bytes(password, "utf-8")

                # Attempt connection via radio controller
                self._radio.connect(ssid_b, password_b, timeout=self.CONNECTION_TIMEOUT)

                # Verify connection
                if self._radio.connected and self._radio.ipv4_address:
                    self.logger.info(f"WiFi connected - IP: {self._radio.ipv4_address}")
                    self._connected = True

                    # Create socket pool and session
                    # pool = socketpool.SocketPool(self._radio)  # Unused
                    self.session = None  # Will be created by caller if needed

                    return True, None
                else:
                    self.logger.error("Connection failed - no IP address")
                    raise ConnectionError("Failed to obtain IP address")

            except KeyboardInterrupt:
                # Re-raise keyboard interrupt to allow caller to handle mode changes
                raise

            except TimeoutError as e:
                # Timeout indicates network unreachable, not authentication failure
                # Reset auth failure counter and retry with backoff
                auth_failure_count = 0
                self.logger.warning(f"Attempt #{attempts} timed out")
                result = await self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry

            except RuntimeError as e:
                error_msg = str(e)
                self.logger.debug(f"Attempt #{attempts} failed: {e}")

                # Check for explicit authentication failure message
                # Note: Can be transient even with valid credentials (router/radio states)
                if "authentication failure" in error_msg.lower():
                    auth_failure_count += 1
                    self.logger.debug(f"Auth failure #{auth_failure_count}/3")

                    # Only raise after 3 consecutive auth failures to avoid false positives
                    # Total time: ~6-7 seconds with short backoff between attempts
                    if auth_failure_count >= 3:
                        self.logger.error("Authentication failed - invalid credentials")
                        raise AuthenticationError("Invalid password") from e
                else:
                    # Reset counter on non-auth errors
                    auth_failure_count = 0

                # Network unreachable or other transient errors - retry with backoff
                result = await self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry

            except ConnectionError as e:
                # errno_code = getattr(e, "errno", None)  # Unused
                error_msg = str(e)
                self.logger.debug(f"Attempt #{attempts} failed: {e}")

                # Check for explicit authentication failure message
                # Note: Can be transient even with valid credentials (router/radio states)
                if "authentication failure" in error_msg.lower():
                    auth_failure_count += 1
                    self.logger.debug(f"Auth failure #{auth_failure_count}/3")

                    # Only raise after 3 consecutive auth failures to avoid false positives
                    # Intermittent auth failures can occur with valid credentials due to:
                    # - Router processing previous disconnect
                    # - WiFi radio initialization timing
                    # - Router rate limiting
                    # Total time to fail: ~6-7 seconds with short backoff between attempts
                    if auth_failure_count >= 3:
                        self.logger.error("Authentication failed - invalid credentials")
                        raise AuthenticationError("Invalid password") from e
                else:
                    # Reset counter on non-auth errors
                    auth_failure_count = 0

                # Network unreachable or other transient errors - retry with backoff
                # "No network with that ssid" could be typo OR temporary outage - retry cycle handles both
                result = await self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry

            except AuthenticationError:
                # Re-raise authentication errors immediately (fail fast)
                raise

            except Exception as e:
                error_msg = str(e)
                self.logger.debug(f"Connection attempt #{attempts} failed: {error_msg}")

                # Reset auth failure counter for generic errors
                auth_failure_count = 0

                # Network unreachable or other transient errors - retry with backoff
                result = await self._handle_retry_or_fail(attempts, error_msg, start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry

    async def _handle_retry_or_fail(
        self,
        attempts: int,
        error_msg: str,
        start_time: float,
        timeout: float | None = None,
        on_retry: Callable[[int, float], None] | None = None,
    ) -> tuple[bool, str] | None:
        """
        Handle retry logic for soft failures.

        Args:
            attempts: Current attempt number
            error_msg: Error message from the failed attempt
            start_time: Monotonic timestamp when connection attempts started
            timeout: Optional timeout in seconds (None for indefinite retry)
            on_retry: Optional callback for retry events

        Returns:
            tuple: (False, error_message) if timeout exceeded
            None: if should continue retrying
        """
        # Check if we've exceeded the timeout (if specified)
        elapsed_time = time.monotonic() - start_time
        if timeout is not None and elapsed_time >= timeout:
            self.logger.warning(f"Retry timeout exceeded ({elapsed_time:.1f}s). Giving up.")
            return False, f"Unable to connect to WiFi after {attempts} attempts over {elapsed_time:.1f} seconds."

        # Calculate exponential backoff time: base * (2^(attempts-1))
        # Attempt 1: 1.5s, 2: 3s, 3: 6s, 4: 12s, 5: 24s, 6: 48s, 7: 96s...
        wait_time = self.BASE_BACKOFF_DELAY * (self.BACKOFF_MULTIPLIER ** (attempts - 1))

        # Cap wait time at maximum backoff (30 minutes)
        if wait_time > self.MAX_BACKOFF_TIME:
            wait_time = self.MAX_BACKOFF_TIME
            self.logger.debug(f"Backoff capped at {self.MAX_BACKOFF_TIME}s ({self.MAX_BACKOFF_TIME / 60:.0f} minutes)")

        # Call retry callback if provided
        if on_retry:
            on_retry(attempts, wait_time)

        self.logger.debug(f"Waiting {wait_time:.1f}s before retry...")

        # Wait with button interrupt checking using InputManager
        from input_manager import InputManager

        input_mgr = InputManager.instance()
        start = time.monotonic()
        while time.monotonic() - start < wait_time:
            if input_mgr.is_pressed():
                raise KeyboardInterrupt("Connection interrupted by button press during backoff")
            remaining = wait_time - (time.monotonic() - start)
            await Scheduler.sleep(min(0.1, remaining))

        # Return None to signal caller to continue retry loop
        return None

    def connect_once(self, ssid: str, password: str) -> tuple[bool, dict[str, str] | None]:
        """
        Attempt to connect to WiFi once without retry logic.

        Args:
            ssid: WiFi network SSID
            password: WiFi network password

        Returns:
            tuple: (success: bool, error_dict or None)
        """
        self.logger.debug(f"Testing connection to '{ssid}'")

        # Convert to bytes to satisfy buffer protocol requirement
        ssid_b = bytes(ssid, "utf-8")
        password_b = bytes(password, "utf-8")

        # Attempt connection with explicit exception handling
        start_time = time.monotonic()
        error_result = None

        try:
            self._radio.connect(ssid_b, password_b, timeout=self.CONNECTION_TIMEOUT)
            elapsed = time.monotonic() - start_time
            self.logger.debug(f"Connection completed in {elapsed:.1f}s")

            # Verify connection success
            if self._radio.connected and self._radio.ipv4_address:
                self.logger.info(f"Connected - IP: {self._radio.ipv4_address}")
                self._connected = True
                return True, None
            else:
                # Connection method returned but no connection established
                self.logger.error("Connection failed - no IP address")
                error_result = (False, {"message": "Failed to obtain IP address", "field": "ssid"})

        except TimeoutError:
            # Explicit timeout during connection
            elapsed = time.monotonic() - start_time
            self.logger.error(f"Connection timed out ({elapsed:.1f}s)")
            error_result = (
                False,
                {"message": "Connection timed out. Please check your password and network.", "field": "password"},
            )

        except RuntimeError as e:
            # RuntimeError often indicates authentication or connection failures
            elapsed = time.monotonic() - start_time
            error_msg = str(e).lower()
            self.logger.error(f"Connection failed: {e}")

            # Check for authentication failure
            if "auth" in error_msg or "password" in error_msg:
                error_result = (
                    False,
                    {"message": "WiFi authentication failure. Please check your password.", "field": "password"},
                )
            elif "no matching" in error_msg or "not found" in error_msg:
                error_result = (
                    False,
                    {"message": "WiFi network not found. Please check the network name.", "field": "ssid"},
                )
            else:
                error_result = (
                    False,
                    {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"},
                )

        except ConnectionError as e:
            # ConnectionError typically indicates network-level failures
            elapsed = time.monotonic() - start_time
            errno_code = getattr(e, "errno", None)
            error_msg = str(e).lower()
            self.logger.error(f"Connection failed: {e}")

            # Check for authentication failure by errno or message
            if errno_code in (-3, 7, 15, 202) or "auth" in error_msg or "password" in error_msg:
                error_result = (
                    False,
                    {"message": "WiFi authentication failure. Please check your password.", "field": "password"},
                )
            elif "not found" in error_msg or "no matching" in error_msg:
                error_result = (
                    False,
                    {"message": "WiFi network not found. Please check the network name.", "field": "ssid"},
                )
            else:
                error_result = (
                    False,
                    {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"},
                )

        except OSError as e:
            # OSError can indicate various system-level connection problems
            elapsed = time.monotonic() - start_time
            errno_code = getattr(e, "errno", None)
            self.logger.error(f"Connection failed: {e}")
            error_result = (False, {"message": "WiFi connection error. Please try again.", "field": "ssid"})

        except Exception as e:
            # Catch-all for unexpected exceptions
            elapsed = time.monotonic() - start_time
            self.logger.error(f"Connection failed: {type(e).__name__} - {e}")
            error_result = (
                False,
                {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"},
            )

        # Note: No radio reset on failure - caller handles cleanup as needed
        # Radio reset would disconnect any active AP in concurrent AP+STA mode

        return error_result if error_result else (False, {"message": "Unknown connection failure", "field": "ssid"})

    def disconnect(self) -> None:
        """Disconnect from WiFi."""
        try:
            if self._radio.connected:
                self._radio.enabled = False
                self._radio.enabled = True
                self._connected = False
                self.logger.info("WiFi disconnected")
        except Exception as e:
            self.logger.warning(f"Error disconnecting WiFi: {e}")

    def is_connected(self) -> bool:
        """Check if currently connected to WiFi."""
        return self._connected and self._radio.connected

    async def reconnect(self, ssid: str, password: str, timeout: float | None = None) -> tuple[bool, str | None]:
        """
        Reconnect to WiFi after setup mode or network disruption.
        Handles all necessary cleanup and state management:
        - Resets WiFi radio from AP mode to station mode
        - Clears connection state
        - Reconnects using standard backoff logic

        Args:
            ssid: WiFi network SSID
            password: WiFi network password
            timeout: Optional timeout in seconds

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        self.logger.info("Reconnecting to WiFi after setup mode exit")

        # Reset radio to station mode (clears any AP mode state)
        self.reset_radio_to_station_mode()

        # Reset connection state
        self._connected = False
        self.session = None

        # Reconnect using standard backoff logic
        return await self.connect_with_backoff(ssid, password, timeout)

    def create_session(self) -> Any:
        """
        Create and return an HTTP session for making requests.

        Returns:
            adafruit_requests.Session instance

        Raises:
            RuntimeError: If not connected to WiFi
        """
        if not self.is_connected():
            raise RuntimeError("Cannot create session: not connected to WiFi")

        import adafruit_requests

        pool = socketpool.SocketPool(self._radio)
        self.session = adafruit_requests.Session(pool, ssl.create_default_context())
        return self.session

    def get_mac_address(self) -> str:
        """
        Get the WiFi MAC address as a hex string.

        Returns:
            str: MAC address in format "aa:bb:cc:dd:ee:ff"
        """
        mac_binary = self._radio.mac_address
        return mac_binary.hex(":")

    def start_access_point(self, ssid: str, password: str | None = None) -> str:
        """
        Start WiFi access point for setup mode.
        Handles all necessary radio state transitions and configuration.
        Saves current connection state for later restoration.

        Args:
            ssid: Access point SSID
            password: Optional password (None for open network)

        Returns:
            str: AP IP address

        Raises:
            RuntimeError: If AP fails to start
        """
        self.logger.info("Starting access point")

        # Save current connection state for later restoration
        self._pre_ap_connected = self.is_connected()
        if self._pre_ap_connected:
            self.logger.debug("Saving connection state before AP mode")

        # Disconnect from any existing WiFi connection before starting AP
        try:
            if self._radio.connected:
                self.logger.debug("Disconnecting from current network")
                self._radio.stop_station()
                time.sleep(0.3)
        except Exception as e:
            self.logger.warning(f"Warning during disconnect: {e}")

        # Initialize/reset WiFi radio to ensure it's in a known good state
        try:
            self._radio.enabled = False
            time.sleep(0.2)
            self._radio.enabled = True
            time.sleep(0.2)
            self.logger.debug("WiFi radio initialized")
        except Exception as e:
            self.logger.warning(f"WiFi radio initialization warning: {e}")

        # Use bytes for SSID/password to satisfy older firmware buffer requirements
        ssid_b = bytes(ssid, "utf-8")
        pwd_b = bytes(password, "utf-8") if password else None

        try:
            # Configure AP IP address before starting
            try:
                import ipaddress

                self._radio.set_ipv4_address_ap(
                    ipv4=ipaddress.IPv4Address("192.168.4.1"),
                    netmask=ipaddress.IPv4Address("255.255.255.0"),
                    gateway=ipaddress.IPv4Address("192.168.4.1"),
                )
                self.logger.debug("AP IP configured: 192.168.4.1")
            except Exception as ip_err:
                self.logger.warning(f"Could not set AP IP (will use default): {ip_err}")

            # Start the access point
            if pwd_b:
                self._radio.start_ap(ssid_b, pwd_b)
            else:
                # Open network; signature varies by version
                try:
                    self._radio.start_ap(ssid_b)
                except TypeError:
                    self._radio.start_ap(ssid_b, None)
        except Exception as e:
            self.logger.error(f"start_ap failed: {e}")
            raise RuntimeError(f"Failed to start access point: {e}") from e

        self.logger.info(f"AP Mode Active. Connect to: {ssid}")
        self._ap_active = True
        self._connected = False  # Not in station mode

        # Wait for AP IP address to be assigned
        ap_ip = None
        for _attempt in range(10):
            ap_ip = self._radio.ipv4_address_ap
            if ap_ip:
                break
            time.sleep(0.1)

        if not ap_ip:
            ap_ip = "192.168.4.1"

        self.logger.debug(f"AP IP address: {ap_ip}")
        return str(ap_ip)

    def stop_access_point(self, restore_connection: bool = True) -> None:
        """
        Stop access point and optionally restore previous WiFi connection.

        Args:
            restore_connection: If True and WiFi was connected before AP mode,
                               automatically attempt to reconnect

        Behavior:
        - If currently connected in station mode (concurrent AP+STA): stops AP, preserves connection
        - If not connected but was connected before AP: attempts to reconnect (if restore_connection=True)
        - Otherwise: resets radio to station mode
        """
        if not self._ap_active:
            return

        self.logger.debug("Stopping access point")

        # If we're connected in station mode, just stop the AP
        # Don't reset the radio - that would disconnect us!
        if self.is_connected():
            self.logger.debug(
                f"Stopping AP while preserving connection (connected={self._radio.connected}, _connected={self._connected})"
            )
            try:
                self._radio.stop_ap()
                # Verify connection preserved
                time.sleep(0.2)  # Brief pause for radio state to stabilize
                still_connected = self._radio.connected
                self.logger.info(
                    f"AP stopped - connection {'preserved' if still_connected else 'LOST'} (radio.connected={still_connected})"
                )
                if not still_connected:
                    self.logger.error("Connection lost after stopping AP - ESP32 firmware issue?")
                    self._connected = False
            except Exception as e:
                self.logger.warning(f"Error stopping AP: {e}")
        else:
            # Not currently connected - check if we should restore previous connection
            if restore_connection and self._pre_ap_connected:
                self.logger.info("Restoring WiFi connection after AP mode")
                credentials = self.get_credentials()
                if credentials and credentials.get("ssid"):
                    scheduler = Scheduler.instance()
                    self._track_task_handle(
                        scheduler.schedule_now(
                            coroutine=lambda: self.ensure_connected(timeout=30),
                            priority=20,
                            name="Restore WiFi After AP",
                        )
                    )
                    self.logger.debug("Queued background reconnection task")
                else:
                    self.logger.warning("Cannot restore connection - no valid credentials")
            else:
                # Not restoring - reset radio to station mode
                self.logger.debug("Not connected - resetting radio to station mode")
                self.reset_radio_to_station_mode()

        self._ap_active = False
        self._pre_ap_connected = False  # Reset saved state

    async def _wait_for_radio_ready_for_concurrent_mode(self, timeout: float = 1.0) -> bool:
        """
        Wait for radio to be ready for concurrent AP+STA mode.

        Checks that:
        - Radio is enabled
        - AP IP address is assigned (indicates AP is fully initialized)

        Args:
            timeout: Maximum time to wait in seconds (default: 1.0)

        Returns:
            bool: True if radio is ready, False if timeout exceeded
        """
        start_time = time.monotonic()
        check_interval = 0.1  # Check every 100ms

        while time.monotonic() - start_time < timeout:
            try:
                # Check radio is enabled
                if not self._radio.enabled:
                    await Scheduler.sleep(check_interval)
                    await Scheduler.yield_control()
                    continue

                # Check AP IP is assigned (indicates AP is ready)
                ap_ip = self._radio.ipv4_address_ap
                if ap_ip:
                    self.logger.debug(f"Radio ready for concurrent mode (AP IP: {ap_ip})")
                    return True

            except Exception as e:
                self.logger.debug(f"Radio readiness check error: {e}")

            await Scheduler.sleep(check_interval)
            await Scheduler.yield_control()

        self.logger.warning(f"Radio not ready for concurrent mode after {timeout}s timeout")
        return False

    async def test_credentials_from_ap(
        self, ssid: str, password: str, max_attempts: int = 3
    ) -> tuple[bool, str | None]:
        """
        Test WiFi credentials while in AP mode with retry logic.
        Uses concurrent AP+STA mode - AP stays running so clients remain connected.

        Retries connection attempts to handle transient errors (e.g., "Unknown failure 2").

        Args:
            ssid: WiFi network SSID to test
            password: WiFi network password to test
            max_attempts: Maximum connection attempts for transient error handling (default: 3)

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        self.logger.info(f"Testing credentials for '{ssid}' in concurrent AP+STA mode")

        if not self._ap_active:
            return False, "Not in AP mode"

        try:
            # Try connecting in station mode while AP is still running
            # ESP32 supports concurrent AP+STA mode
            self.logger.debug("AP remains active during test - clients stay connected")

            # Wait for radio to be ready for concurrent AP+STA mode
            # Error 205 indicates radio not ready - this check prevents first-attempt failures
            ready = await self._wait_for_radio_ready_for_concurrent_mode(timeout=1.0)
            if not ready:
                self.logger.warning("Radio readiness check failed, proceeding anyway")

            # Try connection with retries for transient errors
            success = False
            last_error_msg = None

            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    self.logger.debug(f"Retry attempt {attempt}/{max_attempts} after transient error")
                    await Scheduler.sleep(1.5)  # Short delay between retries

                self.logger.debug(f"Testing connection to '{ssid}' (attempt {attempt}/{max_attempts})")
                await Scheduler.yield_control()
                success, error_msg = self.connect_once(ssid, password)
                await Scheduler.yield_control()
                last_error_msg = error_msg

                if success:
                    self.logger.info(f"Credentials validated on attempt {attempt}/{max_attempts}")
                    # Connected in station mode while AP still running
                    # Caller will stop AP and continue with station mode
                    return True, None

                # Check if this is a permanent failure (auth error) or transient
                if isinstance(error_msg, dict):
                    msg_text = error_msg.get("message", "").lower()
                    # Authentication failures are permanent - don't retry
                    if "authentication" in msg_text or "password" in msg_text:
                        self.logger.warning("Authentication failure detected - stopping retries")
                        break

                self.logger.debug(f"Attempt {attempt} failed: {error_msg}")

            # All attempts failed - AP is still running, just disconnect station attempt
            self.logger.info("Credential test failed - AP remains active for client")

            # Disconnect from failed station connection attempt
            try:
                # Don't use disconnect() as it would affect AP state
                # Just let the failed connection state clear naturally
                pass
            except Exception as e:
                self.logger.debug(f"Note: {e}")

            # Extract error message from error dict if present
            if isinstance(last_error_msg, dict):
                error_message = last_error_msg.get("message", "Connection test failed")
            else:
                error_message = str(last_error_msg) if last_error_msg else "Connection test failed"

            return False, error_message

        except Exception as e:
            self.logger.error(f"Error during credential test: {e}")
            # AP is still running, just return error
            return False, str(e)

    def shutdown_access_point(self) -> None:
        """
        Shutdown access point and disable WiFi radio completely.
        Used before rebooting to ensure clients detect network disconnection.
        Does NOT reset radio back to station mode - just disables it.
        """
        if not self._ap_active:
            return

        self.logger.info("Shutting down access point")

        # Stop AP if running
        try:
            self._radio.stop_ap()
            self.logger.debug("AP stopped")
        except Exception as e:
            self.logger.warning(f"Warning stopping AP: {e}")

        # Disable radio completely (no re-enable)
        try:
            self._radio.enabled = False
            self.logger.debug("WiFi radio disabled")
        except Exception as e:
            self.logger.warning(f"Warning disabling radio: {e}")

        self._ap_active = False
        self.logger.debug("Access point shutdown complete")

    def is_ap_active(self) -> bool:
        """Check if access point mode is currently active."""
        return self._ap_active

    def get_socket_pool(self) -> Any:
        """
        Get a socket pool for the current WiFi radio.
        Used by DNS interceptor and other network services.

        Returns:
            socketpool.SocketPool instance
        """
        return socketpool.SocketPool(self._radio)

    def get_ap_ip_address(self) -> str:
        """
        Get the current access point IP address.

        Returns:
            str: AP IP address, or "192.168.4.1" if not available
        """
        ap_ip = self._radio.ipv4_address_ap
        return str(ap_ip) if ap_ip else "192.168.4.1"

    def scan_networks(self) -> Generator[Any, None, None]:
        """
        Scan for available WiFi networks.

        Yields:
            Network objects with ssid, rssi, channel, etc.
        """
        try:
            yield from self._radio.start_scanning_networks()
        finally:
            try:
                self._radio.stop_scanning_networks()
            except Exception as e:
                self.logger.warning(f"Error stopping network scan: {e}")

    def validate_ssid_exists(self, ssid: str) -> bool:
        """
        Check if a given SSID exists in the available networks.

        Args:
            ssid: SSID to validate

        Returns:
            bool: True if SSID found in scan results
        """
        try:
            scan_results = self._radio.start_scanning_networks()

            # Handle different return types (iterator or int)
            if isinstance(scan_results, int):
                return False

            found = False
            for network in scan_results:
                if network.ssid == ssid:
                    found = True
                    break

            return found
        except Exception as e:
            self.logger.error(f"Error during SSID validation scan: {e}")
            return False
        finally:
            try:
                self._radio.stop_scanning_networks()
            except Exception as e:
                self.logger.warning(f"Error stopping scan: {e}")

    def shutdown(self) -> None:
        """
        Release all resources owned by ConnectionManager.

        Disconnects WiFi, stops AP if active, disables radio, and clears references.
        This is called automatically when reinitializing with different dependencies,
        or can be called explicitly for cleanup.

        This method is idempotent (safe to call multiple times).
        """
        if not getattr(self, "_initialized", False):
            return

        try:
            # Stop access point if active
            if getattr(self, "_ap_active", False):
                self.shutdown_access_point()

            # Disconnect from WiFi
            self.disconnect()

            # Disable radio completely
            if hasattr(self, "_radio") and self._radio is not None:
                with suppress(Exception):
                    self._radio.enabled = False

            # Clear references
            self.session = None
            self._connected = False
            self._ap_active = False
            self._pre_ap_connected = False
            self._credentials = None
            self._init_radio_controller = None

            # Radio controller should be managed by its own lifecycle
            # Don't delete _radio_controller here as it might be shared
            # Just clear the radio reference
            self._radio = None

            self.logger.debug("ConnectionManager shut down")

        except Exception as e:
            self.logger.warning(f"Error during ConnectionManager shutdown: {e}")
        finally:
            super().shutdown()
