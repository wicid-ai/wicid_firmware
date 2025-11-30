import json
import os
import time

import supervisor  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
from adafruit_httpserver import (  # type: ignore[import-not-found, attr-defined]  # CircuitPython-only module
    JSONResponse,
    Request,
    Response,
)

from controllers.pixel_controller import PixelController
from core.app_typing import Any, Callable, Optional
from core.logging_helper import logger
from core.scheduler import Scheduler
from managers.configuration.states import PendingCredentials, PortalState, UpdateState, ValidationState
from managers.connection_manager import ConnectionManager
from managers.manager_base import ManagerBase
from services.dns_interceptor_service import DNSInterceptorService as DNSInterceptor
from utils.utils import suppress


class ConfigurationManager(ManagerBase):
    """
    Singleton manager for device configuration lifecycle.

    Handles:
    - Configuration state management (missing/invalid/valid)
    - Portal lifecycle (AP, DNS, HTTP server)
    - Credential validation and testing
    - Update checking after successful connection
    - Restart decisions for configuration scenarios

    Use instance() to access the singleton instance.
    """

    _instance = None
    PROGRESS_STEP_PERCENT = 2  # Minimum % delta required to emit progress updates
    UPDATE_SERVICE_INTERVAL_MS = 200  # Interval between servicing HTTP during updates

    # Type annotations for instance attributes
    connection_manager: Optional[ConnectionManager] = None
    pixel: Any = None  # PixelController | None, but Any to avoid circular import
    _update_manager: Any = None  # UpdateManager | None, but Any to avoid circular import
    _http_server: Any = None  # HTTPServer | None, but Any to avoid circular import
    dns_interceptor: Optional["DNSInterceptor"] = None
    _active_button_session: Any = None  # ButtonController | None, but Any to avoid circular import

    # --- Centralized error strings ---
    ERR_INVALID_REQUEST = "Invalid request data."
    ERR_EMPTY_SSID = "SSID cannot be empty."
    ERR_PWD_LEN = "Password must be 8-63 characters."
    ERR_SCAN_FAIL = "Could not scan for networks. Please try again."
    ERR_INVALID_ZIP = "ZIP code must be 5 digits."

    @classmethod
    def instance(cls) -> "ConfigurationManager":
        """
        Get the singleton instance of ConfigurationManager.

        Args:
            portal_runner: Coroutine callable used to launch the setup portal
                when configuration must be collected or repaired.

        Returns:
            ConfigurationManager: The singleton instance
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._init()
        return cls._instance

    def _init(self) -> None:
        """Internal initialization method."""
        # Access point configuration
        self.ap_ssid = "WICID-Setup"
        self.ap_password: Optional[str] = None  # Open network

        # Core managers and controllers
        self.pixel = PixelController()  # Get singleton instance
        self.connection_manager = ConnectionManager.instance()  # Get ConnectionManager singleton
        self.dns_interceptor = None  # DNS interceptor for captive portal
        self._update_manager = None  # Lazy-initialized UpdateManager
        self._http_server = None  # Store server reference for update polling
        self._active_button_session = None  # Tracks session controller while portal active

        # State management using dataclasses
        self.portal = PortalState()
        self.validation = ValidationState()
        self.update = UpdateState()
        self.credentials = PendingCredentials()

        # Update service interval tracking
        self._last_update_service_time = 0.0

        self.logger = logger("wicid.config")
        self._initialized = False  # Track if initialize() has been called (different from ManagerBase._initialized)

        # ManagerBase initialization flag
        self._manager_initialized = True

    def _load_saved_configuration(self) -> tuple[str, str, str] | None:
        """Read stored credentials from disk."""
        try:
            with open("/secrets.json") as f:
                secrets = json.load(f)
        except (OSError, ValueError) as e:
            self.logger.info(f"No configuration found: {e}")
            return None

        ssid = secrets.get("ssid", "").strip()
        password = secrets.get("password", "")
        zip_code = secrets.get("weather_zip", "")
        return ssid, password, zip_code

    @staticmethod
    def _has_complete_configuration(ssid: str, password: str, zip_code: str) -> bool:
        """Return True when all configuration fields are populated."""
        return bool(ssid and password and zip_code)

    def __init__(self) -> None:
        """Private constructor. Use instance() instead."""
        # Guard against re-initialization
        if getattr(self, "_manager_initialized", False):
            return
        # If _instance is already set, don't override it
        if ConfigurationManager._instance is None:
            ConfigurationManager._instance = self
        self._init()

    def shutdown(self) -> None:
        """
        Release all resources owned by ConfigurationManager.

        Stops HTTP server, DNS interceptor, and clears references.
        This method is idempotent (safe to call multiple times).
        """
        if not getattr(self, "_manager_initialized", False):
            return

        try:
            # Use existing cleanup method if portal is active
            if hasattr(self, "_cleanup_setup_portal"):
                with suppress(Exception):
                    # Schedule cleanup as async task since shutdown() is synchronous
                    scheduler = Scheduler.instance()
                    scheduler.schedule_now(
                        coroutine=self._cleanup_setup_portal,
                        priority=10,
                        name="Cleanup Setup Portal",
                    )

            # Clear references
            self.connection_manager = None
            self.pixel = None
            self._update_manager = None
            self._http_server = None
            self.dns_interceptor = None
            self.logger.debug("ConfigurationManager shut down")

        except Exception as e:
            self.logger.warning(f"Error during ConfigurationManager shutdown: {e}")
        finally:
            super().shutdown()
            self._manager_initialized = False

    async def initialize(self, portal_runner: Callable[..., Any] | None = None) -> bool:
        """
        Initialize system configuration on boot.

        Checks if valid configuration exists and WiFi is connected.
        Enters setup mode if configuration is missing or WiFi connection fails.
        Blocks until configuration is complete and WiFi is connected.

        Args:
            portal_runner: Coroutine callable used to launch the setup portal
                when configuration must be collected or repaired.

        Returns:
            bool: True if initialization successful (WiFi connected)

        Raises:
            Exception: Only on unrecoverable errors (hardware failure, etc.)
        """
        if self._initialized:
            self.logger.debug("ConfigurationManager already initialized")
            return True

        self.logger.info("Initializing configuration")

        config = self._load_saved_configuration()
        if config is None:
            if portal_runner is None:
                raise ValueError("portal_runner is required to enter setup mode")
            return await portal_runner(error=None)

        ssid, password, zip_code = config

        # Validate configuration is complete
        if not self._has_complete_configuration(ssid, password, zip_code):
            self.logger.info("Configuration incomplete - entering setup")
            if portal_runner is None:
                raise ValueError("portal_runner is required to enter setup mode")
            return await portal_runner(error=None)

        self.logger.debug(f"Configuration found for '{ssid}'")

        # Try to connect with existing credentials
        if self.connection_manager and self.connection_manager.is_connected():
            self.logger.debug("Already connected")
            self._initialized = True
            return True

        # Attempt connection with saved credentials
        self.logger.debug("Connecting with saved credentials")
        if not self.connection_manager:
            raise RuntimeError("ConnectionManager not initialized")
        success, error_msg = await self.connection_manager.ensure_connected(timeout=60)

        if success:
            self._initialized = True
            return True

        # Connection failed - enter setup mode
        self.logger.warning(f"Connection failed: {error_msg}")
        self.logger.info("Entering setup mode")
        friendly_message, field = self._build_connection_error(ssid, error_msg)
        if portal_runner is None:
            raise ValueError("portal_runner is required to enter setup mode")
        return await portal_runner(error={"message": friendly_message, "field": field})

    async def run_portal(self, error: dict[str, str] | None = None, button_session: Any = None) -> bool:
        """
        Force entry into setup/configuration mode.

        Starts the captive portal regardless of existing configuration state.
        Used for:
        - Initial setup (no configuration)
        - Re-configuration (button hold from main loop)
        - Configuration errors

        Args:
            error: Optional error dict to display in portal ({'message': str, 'field': str})
            button_session: Controller that exposes button events for exit/safe mode actions

        Returns:
            bool: True if setup successful and WiFi connected, False if cancelled

        Lifecycle decisions:
        - User saves valid config → return True (WiFi connected)
        - User clicks cancel → restart
        - User exits via button → restart
        - Idle timeout (5+ min) → restart

        Raises:
            Exception: Only on unrecoverable errors
        """
        if button_session is None:
            raise ValueError("run_portal() requires a button_session controller")
        self._active_button_session = button_session

        self.logger.info("Entering configuration mode")

        # Reset setup completion flag for new session
        self.portal.setup_complete = False

        # Set error message if provided
        if error:
            self.portal.last_connection_error = error

        # Reset button state tracking for this portal session
        if self._active_button_session and hasattr(self._active_button_session, "reset"):
            self._active_button_session.reset()

        # Start setup mode indicator (pulsing white LED)
        self.start_setup_indicator()

        # Start access point and web server
        await self.start_access_point()

        # Run the web server (blocks until setup complete or cancelled)
        result = await self.run_web_server()

        if result:
            self.logger.info("Configuration complete")
            self._initialized = True
            self._active_button_session = None
            return True
        else:
            self.logger.info("Configuration cancelled - returning to caller")
            # Clean up and return False - caller decides next action
            # ConnectionManager will automatically restore connection if needed
            await self._cleanup_setup_portal()
            self._active_button_session = None
            return False

    def _build_connection_error(self, ssid: str, raw_error: str | None) -> tuple[str, str]:
        """
        Create a concise, user-friendly connection error message and map it to the correct field.

        Args:
            ssid: The SSID we attempted to connect to
            raw_error: The raw error message returned by the WiFi manager

        Returns:
            tuple[str, str]: (friendly_message, field_name)
        """
        base = f"Couldn't connect to '{ssid}'."
        field = "ssid"

        if not raw_error:
            return f"{base} Please try again.", field

        normalized = str(raw_error).lower()

        if "auth" in normalized or "password" in normalized:
            field = "password"
            return f"{base} Please double-check the Wi-Fi password.", field

        if "not found" in normalized or "no matching" in normalized:
            field = "ssid"
            return f"Couldn't find '{ssid}'. Try selecting it again or entering it manually.", field

        if "timeout" in normalized:
            field = "password"
            return f"{base} Connection timed out. Please check the Wi-Fi password and signal, then try again.", field

        return f"{base} Please check your Wi-Fi settings and try again.", field

    def start_setup_indicator(self) -> None:
        """Begin pulsing white to indicate setup mode is active."""
        self.pixel.indicate_setup_mode()

    def _start_dns_interceptor(self, ap_ip: str) -> bool:
        """
        Start the DNS interceptor for captive portal functionality.

        Args:
            ap_ip: Access point IP address

        Returns:
            bool: True if DNS interceptor started successfully
        """
        try:
            if not self.connection_manager:
                return False
            socket_pool = self.connection_manager.get_socket_pool()
            self.dns_interceptor = DNSInterceptor(local_ip=ap_ip, socket_pool=socket_pool)

            if self.dns_interceptor.start():
                self.logger.info("DNS interceptor started on port 53")
                return True
            else:
                self.logger.warning("DNS interceptor failed - HTTP-only mode")
                self.dns_interceptor = None
                return False

        except Exception as e:
            self.logger.warning(f"DNS interceptor error: {e}")

            if hasattr(self, "dns_interceptor") and self.dns_interceptor:
                with suppress(Exception):
                    self.dns_interceptor.stop()

            self.dns_interceptor = None
            return False

    def _stop_dns_interceptor(self) -> None:
        """Stop the DNS interceptor and clean up resources"""
        if self.dns_interceptor:
            try:
                self.dns_interceptor.stop()
            except Exception as e:
                self.logger.warning(f"Error stopping DNS interceptor: {e}")
            finally:
                self.dns_interceptor = None

    def _stop_http_server(self) -> None:
        """Stop the HTTP server and clean up resources"""
        if self._http_server:
            try:
                self._http_server.stop()
            except Exception as e:
                self.logger.warning(f"Error stopping HTTP server: {e}")
            finally:
                self._http_server = None

    def _check_dns_interceptor_health(self) -> bool:
        """Check DNS interceptor health"""
        if not self.dns_interceptor:
            return False

        try:
            status = self.dns_interceptor.get_status()
            return status["healthy"]
        except Exception:
            return False

    def get_socket_pool(self) -> Any:
        """Get the socket pool from the connection manager."""
        if not self.connection_manager:
            raise RuntimeError("ConnectionManager not initialized")
        return self.connection_manager.get_socket_pool()

    async def start_access_point(self) -> str:
        """Start the access point for setup mode using the connection manager."""
        # Start AP through ConnectionManager (handles all radio state transitions)
        if not self.connection_manager:
            raise RuntimeError("ConnectionManager not initialized")
        ap_ip = await self.connection_manager.start_access_point(self.ap_ssid, self.ap_password)

        # Start DNS interceptor for captive portal functionality
        dns_success = self._start_dns_interceptor(ap_ip)

        if dns_success:
            self.logger.info("Captive portal: DNS + HTTP")
        else:
            self.logger.info("Captive portal: HTTP only")

        # Ensure setup mode indicator is active whenever portal is running
        self.pixel.indicate_setup_mode()
        # Scheduler automatically handles LED animation updates at 25Hz
        return ap_ip

    def _get_os_from_user_agent(self, request: Request) -> str:
        """
        Parse user agent to determine operating system for captive portal handling.
        Returns: 'android', 'ios', 'windows', 'linux', 'macos', or 'unknown'
        """
        try:
            user_agent = ""
            if hasattr(request, "headers") and request.headers:
                user_agent = request.headers.get("User-Agent", "").lower()

            if "android" in user_agent or "dalvik" in user_agent:
                return "android"

            if any(ios_indicator in user_agent for ios_indicator in ["iphone", "ipad", "ipod", "cfnetwork"]):
                return "ios"

            if "windows" in user_agent or "microsoft ncsi" in user_agent:
                return "windows"

            if "mac os x" in user_agent or "darwin" in user_agent:
                return "macos"

            if "linux" in user_agent and "android" not in user_agent:
                return "linux"

            return "unknown"

        except Exception:
            return "unknown"

    def _create_captive_redirect_response(self, request: Request, target_url: str = "/") -> Response:
        """
        Create appropriate redirect response for captive portal detection.
        Preserves setup portal functionality while triggering captive portal.
        """
        try:
            os_type = self._get_os_from_user_agent(request)

            # iOS devices expect HTML with meta redirect
            if os_type == "ios":
                html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0; url={target_url}">
    <title>WICID Setup</title>
</head>
<body>
    <p>Redirecting to WICID setup...</p>
    <script>window.location.href = "{target_url}";</script>
</body>
</html>"""
                return Response(request, html_content, content_type="text/html")

            # All other operating systems use HTTP 302 redirect
            else:
                return Response(request, "", status=(302, "Found"), headers={"Location": target_url})

        except Exception:
            # Fallback to simple redirect
            try:
                return Response(request, "", status=(302, "Found"), headers={"Location": target_url})
            except Exception:
                # Last resort: HTML redirect
                fallback_html = f'<html><head><meta http-equiv="refresh" content="0; url={target_url}"></head><body>Redirecting...</body></html>'
                return Response(request, fallback_html, content_type="text/html")

    # --- Message helpers ---
    def _net_not_found_message(self, ssid: str) -> str:
        return f"Network '{ssid}' not found. Check for typos."

    # --- Validation helpers ---
    def _validate_config_input(self, request: Request, ssid: str, password: str, zip_code: str) -> Optional[Response]:
        """Validate SSID, password, and ZIP code format. Return a Response on error, else None."""
        if not ssid:
            return self._json_error(request, self.ERR_EMPTY_SSID, field="ssid")
        try:
            pwd_len = len(password)
            if not (8 <= pwd_len <= 63):
                return self._json_error(request, self.ERR_PWD_LEN, field="password")
        except Exception as e:
            self.logger.error(f"Password length check crashed: {e}")
            raise

        # Validate ZIP code format (5 digits)
        if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
            return self._json_error(request, self.ERR_INVALID_ZIP, field="zip_code")

        return None

    def scan_networks(self) -> list[Any]:
        """Scan for available networks."""
        if not self.connection_manager:
            return []
        return list(self.connection_manager.scan_networks())

    def _scan_ssids(self) -> list[str]:
        """Scan for WiFi networks and return a list of available SSIDs.
        Uses the connection manager for scanning (ensures scanning is stopped).
        """
        self.logger.debug("Starting network scan for SSID validation")
        try:
            networks = self.scan_networks()
            ssids = [net.ssid for net in networks if getattr(net, "ssid", None)]
            self.logger.debug(f"Found SSIDs: {ssids}")
            return ssids
        except Exception as e:
            self.logger.error(f"Network scan error: {e}")
            raise

    # --- Response helpers to keep code DRY and API-compatible ---
    def _json_ok(self, request: Request, data: dict[str, Any]) -> Response:
        """Return a JSONResponse with 200 OK."""
        return JSONResponse(request, data)

    def _json_error(
        self, request: Request, message: str, field: str | None = None, code: int = 400, text: str = "Bad Request"
    ) -> Response:
        """Return an error JSON response with explicit status tuple.

        Using the base Response with a (code, text) tuple is compatible across library versions.
        """
        body = {"status": "error", "error": {"message": message, "field": field}}
        return Response(request, json.dumps(body), content_type="application/json", status=(code, text))

    def save_credentials(self, ssid: str, password: str, zip_code: str) -> tuple[bool, Optional[str]]:
        """Save WiFi credentials and weather ZIP to secrets.json."""
        try:
            # Save all user settings to secrets.json (no config.json anymore)
            secrets = {"ssid": ssid, "password": password, "weather_zip": zip_code}

            with open("/secrets.json", "w") as f:
                json.dump(secrets, f)
            os.sync()

            # Store credentials for later testing before activation
            self.credentials.set(ssid, password)

            self.logger.info("Credentials saved")
            return True, None

        except Exception as e:
            self.logger.error(f"Error saving credentials: {e}")
            return False, str(e)

    async def blink_success(self) -> None:
        """Blink green to indicate success"""
        try:
            await self.pixel.blink_success()
        except Exception as e:
            self.logger.warning(f"Error in blink_success: {e}")

    async def run_web_server(self) -> bool:
        """Run a simple web server to handle the setup interface"""
        from adafruit_httpserver import Server  # type: ignore[import-not-found, attr-defined]

        from managers.configuration.portal_routes import PortalRoutes

        if not self.connection_manager:
            raise RuntimeError("ConnectionManager not initialized")
        pool = self.connection_manager.get_socket_pool()
        server = Server(pool, "/www", debug=False)

        # Store server reference for update polling
        self._http_server = server

        # Initialize idle timeout tracking
        self.portal.last_request_time = time.monotonic()
        setup_idle_timeout = int(os.getenv("SETUP_IDLE_TIMEOUT", "300"))

        # Register all HTTP route handlers
        routes = PortalRoutes(self)
        routes.register_routes(server)

        # Start the server
        if not self.connection_manager:
            raise RuntimeError("ConnectionManager not initialized")
        server_ip = self.connection_manager.get_ap_ip_address()
        server.start(host=server_ip, port=80)
        self.logger.info(f"Server started at http://{server_ip}")

        # Small debounce delay
        debounce_end = time.monotonic() + 0.5
        while time.monotonic() < debounce_end:
            await Scheduler.sleep(0.05)

        # Main server loop - listen for button press to exit
        while not self.portal.setup_complete:
            try:
                # Service HTTP server and DNS interceptor
                # Note: Pixel controller animation now handled by scheduler
                self.tick()

                # Check for idle timeout (no user interaction)
                if self.portal.last_request_time is not None:
                    idle_time = time.monotonic() - self.portal.last_request_time
                    if idle_time >= setup_idle_timeout:
                        self.logger.info(f"Setup idle timeout exceeded ({idle_time:.0f}s). Restarting to retry...")

                        # Comprehensive cleanup before restarting
                        await self._cleanup_setup_portal()
                        supervisor.reload()

                # Execute async validation if triggered
                if self.validation.trigger and self.validation.state in ["validating_wifi", "checking_updates"]:
                    await self._execute_async_validation()

                # Execute async update if triggered
                if self.update.trigger and self.update.state in ["downloading", "verifying", "unpacking"]:
                    await self._execute_async_update(server, server_ip)

                # If activation scheduled (after validation or user action), execute activation
                # Note: Update mode is handled by _execute_async_update, not here
                if self.portal.pending_ready_at is not None and time.monotonic() >= self.portal.pending_ready_at:
                    if self.validation.activation_mode == "continue":
                        # Continue mode: credentials validated, no update available
                        self.logger.info("Executing activation (continue mode)")

                        # Flash green to indicate success
                        try:
                            await self.pixel.blink_success()
                        except Exception as led_e:
                            self.logger.warning(f"Error flashing LED: {led_e}")

                        # Verify WiFi connection preserved, reconnect if needed
                        if self.connection_manager and not self.connection_manager.is_connected():
                            self.logger.warning("WiFi connection lost after stopping AP - reconnecting")
                            credentials = self.connection_manager.get_credentials()
                            if credentials:
                                success, error_msg = await self.connection_manager.ensure_connected(timeout=30)
                                if not success:
                                    self.logger.error(f"Failed to reconnect after AP stop: {error_msg}")
                                else:
                                    self.logger.info("WiFi reconnected successfully")
                        else:
                            self.logger.debug("WiFi connection preserved after AP stop")

                        # Comprehensive cleanup
                        await self._cleanup_setup_portal()

                        self.logger.info("Setup complete - continuing in normal mode")
                        self.portal.setup_complete = True
                        return True
                    else:
                        # Unknown or update mode (update is handled by _execute_async_update)
                        self.logger.debug(f"Ignoring pending_ready_at for mode: {self.validation.activation_mode}")
                        self.portal.pending_ready_at = None

                # Check for button interrupt via session
                if self._active_button_session and self._active_button_session.safe_mode_ready():
                    self.logger.info("Safe Mode requested (setup portal)")

                    await self._cleanup_setup_portal()
                    # Session handoff requeues SAFE action for ModeManager
                    return False

                exit_reason = (
                    None if self._active_button_session is None else self._active_button_session.consume_exit_request()
                )
                if exit_reason:
                    self.logger.debug(f"Setup exit requested via {exit_reason}")

                    cleanup_successful = await self._cleanup_setup_portal()

                    if not cleanup_successful:
                        self.logger.warning("Cleanup completed with issues")

                    await Scheduler.sleep(0.2)
                    return False

                # Small sleep to prevent busy-waiting while maintaining smooth LED animation
                # 5ms is fast enough for smooth pulsing (tick interval is 40ms) while being CPU-friendly
                await Scheduler.sleep(0.005)

            except Exception as e:
                self.logger.error(f"Server error: {e}")
                await Scheduler.sleep(1)

        # Comprehensive cleanup
        await self._cleanup_setup_portal()
        self._active_button_session = None
        return self.portal.setup_complete

    def tick(self) -> None:
        """
        Service HTTP server, DNS interceptor, and pixel controller once.

        Called regularly while the setup portal is active to keep networking
        responsive and LED animations smooth.
        """
        if self._http_server:
            self._http_server.poll()

        if self.dns_interceptor:
            try:
                self.dns_interceptor.poll()
                self._check_dns_interceptor_health()
            except Exception as dns_e:
                self.logger.error(f"DNS interceptor error: {dns_e}")
                self._stop_dns_interceptor()

        # Pixel controller animation now handled by scheduler at 25Hz

    def _update_progress_callback(self, state: str, message: str, progress_pct: float) -> None:
        """
        Progress callback for UpdateManager (Observer pattern).

        Updates internal state that UI can poll via /update-status endpoint.
        Yields control to HTTP server to service pending requests at each milestone.

        Args:
            state: 'downloading', 'verifying', 'unpacking', 'complete', 'error'
            message: Human-readable progress message
            progress_pct: Completion percentage (0-100), may be None
        """
        # Map 'complete' to 'restarting' since ConfigurationManager will set it to restarting anyway
        # This ensures UI sees the correct state immediately
        if state == "complete":
            state = "restarting"

        state_changed = state != self.update._last_notify_state
        message_changed = message != self.update._last_notify_message
        progress_changed = self._progress_delta_trigger(progress_pct)

        self.update.state = state
        self.update.progress_message = message
        self.update.progress_pct = progress_pct

        if not (state_changed or message_changed or progress_changed):
            return

        self.update._last_notify_state = state
        self.update._last_notify_message = message
        self.update._last_notify_pct = progress_pct
        self.update._last_pct_value = self._normalize_progress(progress_pct)

        self.logger.debug(f"Update progress: {state} - {message} ({progress_pct}%)")

    def _normalize_progress(self, progress_pct: float) -> Optional[float]:
        """Convert progress value to int 0-100 when possible; return None otherwise."""
        if progress_pct is None:
            return None
        try:
            progress_val = int(progress_pct)
            return max(0, min(progress_val, 100))
        except (ValueError, TypeError):
            return None

    def _progress_delta_trigger(self, progress_pct: float) -> bool:
        """
        Determine if progress change alone warrants emitting an update.

        Returns True when:
        - Progress switches between determinate/indeterminate
        - Numeric progress changes by PROGRESS_STEP_PERCENT or more
        - Non-numeric progress value changes
        """
        normalized = self._normalize_progress(progress_pct)
        last_normalized = self.update._last_pct_value

        # Determinate progress comparison
        if normalized is not None:
            if last_normalized is None:
                return True
            return abs(normalized - last_normalized) >= self.PROGRESS_STEP_PERCENT

        # Indeterminate progress - defer to raw value comparison
        return progress_pct != self.update._last_notify_pct

    def _service_update_timeslice(self) -> None:
        """Allow update loop to service HTTP/DNS without re-entering frequently."""
        now = time.monotonic()
        if (now - self._last_update_service_time) * 1000.0 < self.UPDATE_SERVICE_INTERVAL_MS:
            return
        self._last_update_service_time = now
        try:
            self.tick()
        except Exception as e:
            self.logger.debug(f"Error servicing update requests: {e}")

    async def _sleep_with_portal_service(self, seconds: float) -> None:
        """Sleep while continuing to service portal networking."""
        target = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                break
            self._service_update_timeslice()
            await Scheduler.sleep(min(0.1, remaining))

    def _get_update_manager(self) -> Any:
        """
        Get or create UpdateManager instance.

        Lazy initialization ensures UpdateManager has WiFi access.

        Returns:
            UpdateManager: Instance
        """
        if self._update_manager is None:
            from managers.update_manager import UpdateManager

            self._update_manager = UpdateManager.instance()
        return self._update_manager

    async def _execute_async_update(self, server: Any, server_ip: str) -> None:
        """
        Execute async update workflow using UpdateManager.

        UpdateManager handles download, verification, and extraction with proper
        LED feedback and error handling. We observe progress via callback.

        Called from main server loop when update_trigger is set.
        """
        try:
            if self.update.state == "downloading":
                self.logger.info("Initiating update download")
                update_manager = self._get_update_manager()

                # UpdateManager cached update_info from check_for_updates()
                try:
                    download_success = await update_manager.download_update(
                        progress_callback=self._update_progress_callback,
                        service_callback=self._service_update_timeslice,
                    )
                except ValueError as e:
                    self.logger.error(f"Update download failed: {e}")
                    await self._handle_setup_update_failure(server, f"Invalid update request: {e}")
                    return
                except RuntimeError as e:
                    # Critical programming errors - re-raise to propagate to main() and trigger reboot
                    self.logger.critical(f"Critical update download error: {e}")
                    self.update.state = "error"
                    self.update.trigger = False
                    raise

                if not download_success:
                    self.logger.error("Update download failed")
                    await self._handle_setup_update_failure(server, "Download failed")
                    return

                self.logger.info("Update ready for installation")

                # Move to restarting state
                self.update.state = "restarting"
                self.update.trigger = False

                # Give client time to see "Restarting..." (2 seconds)
                await self._sleep_with_portal_service(2)

                # Stop server and AP before reboot
                self._stop_dns_interceptor()

                try:
                    if self.connection_manager:
                        await self.connection_manager.stop_access_point()
                except Exception as e:
                    self.logger.warning(f"Error stopping AP: {e}")

                # Hard reset to trigger update installation in boot.py
                self.logger.info("Rebooting to install update")
                import microcontroller  # type: ignore[import-not-found]  # CircuitPython-only module

                microcontroller.reset()

        except Exception as e:
            self.logger.error(f"Error during async update: {e}")
            await self._handle_setup_update_failure(server, f"Async update error: {e}")

    async def _handle_setup_update_failure(self, server: Any, reason: str) -> None:
        """
        Gracefully exit setup mode after an update failure and resume normal mode.
        """
        self.logger.warning(f"Update failed in setup mode: {reason}. Continuing with current firmware.")
        self.update.trigger = False
        self.update.state = "restarting"
        self.update.progress_message = "Restarting device..."
        self.update.progress_pct = 100
        self.validation.activation_mode = None
        self.portal.setup_complete = True
        self.portal.pending_ready_at = None

        try:
            await self._cleanup_setup_portal()
        except Exception as cleanup_error:
            self.logger.warning(f"Cleanup after update failure reported: {cleanup_error}")

        # Allow the client to poll one last status update before restarting
        await self._sleep_with_portal_service(1)
        supervisor.reload()

    async def _execute_async_validation(self) -> None:
        """
        Execute async validation workflow: test WiFi credentials and check for updates.
        Updates validation_state and validation_result as it progresses.
        Called from main server loop when validation_trigger is set.
        """
        try:
            # Test WiFi credentials
            if self.validation.state == "validating_wifi":
                if not self.credentials.has_credentials():
                    self.logger.error("No credentials to validate")
                    self.validation.state = "error"
                    self.validation.result = {
                        "error": {"message": "No credentials available for validation", "field": None}
                    }
                    self.validation.trigger = False
                    return

                # Extract credentials (guaranteed non-None by has_credentials() check above)
                ssid = self.credentials.ssid
                password = self.credentials.password
                assert ssid is not None and password is not None  # Type narrowing for mypy

                self.logger.info(f"Validating WiFi credentials for '{ssid}'")
                if not self.connection_manager:
                    success = False
                    error_msg: str | dict[str, Any] | None = "ConnectionManager not initialized"
                else:
                    success, error_msg = await self.connection_manager.test_credentials_from_ap(ssid, password)

                if not success:
                    # Credentials failed
                    self.logger.warning(f"WiFi validation failed: {error_msg}")
                    self.validation.state = "error"

                    # Extract error message from dict if present
                    if isinstance(error_msg, dict):
                        error_message = error_msg.get("message", "WiFi connection test failed")
                        val = error_msg.get("field", "password")
                        error_field = str(val) if val is not None else "password"
                    else:
                        error_message = str(error_msg) if error_msg else "WiFi connection test failed"
                        error_field = "password"

                    self.validation.result = {"error": {"message": error_message, "field": error_field}}
                    self.validation.trigger = False

                    # Clear credentials for retry
                    self.credentials.clear()
                    return

                # WiFi validation successful - move to update check
                self.logger.info("WiFi credentials validated successfully")
                self.validation.state = "checking_updates"
                # Don't return - continue to update check

            # Check for updates
            if self.validation.state == "checking_updates":
                try:
                    update_manager = self._get_update_manager()

                    # Check for updates
                    update_info = update_manager.check_for_updates()

                    if update_info:
                        # Update available
                        self.logger.info(f"Update available: {update_info.get('version')}")
                        self.validation.state = "success"
                        self.validation.result = {"update_available": True, "update_info": update_info}
                    else:
                        # No update available
                        self.logger.info("No updates available")
                        self.validation.state = "success"
                        self.validation.result = {"update_available": False}

                    self.validation.trigger = False

                except Exception as update_e:
                    # Update check failed - but WiFi works, so continue anyway
                    self.logger.warning(f"Update check failed: {update_e}")
                    self.validation.state = "success"
                    self.validation.result = {"update_available": False}
                    self.validation.trigger = False

        except Exception as e:
            self.logger.error(f"Error during async validation: {e}")
            self.validation.state = "error"
            self.validation.result = {"error": {"message": f"Validation error: {e}", "field": None}}
            self.validation.trigger = False

    def _restart_portal_services(self, server: Any, server_ip: str) -> None:
        """
        Restart HTTP server and DNS interceptor after failed credential test.
        Called when credentials fail so client can see error and retry.

        Args:
            server: The HTTP server instance to restart
            server_ip: IP address to bind server to
        """
        # Restart DNS interceptor
        dns_success = self._start_dns_interceptor(server_ip)
        if dns_success:
            self.logger.debug("DNS interceptor restarted")
        else:
            self.logger.debug("DNS interceptor restart skipped (HTTP-only mode)")

        # Restart HTTP server
        try:
            server.start(host=server_ip, port=80)
            self.logger.info(f"HTTP server restarted at http://{server_ip}")
        except Exception as e:
            self.logger.error(f"Error restarting HTTP server: {e}")
            raise

    async def _cleanup_setup_portal(self) -> bool:
        """
        Comprehensive cleanup of ALL setup portal resources and state.

        Ensures idempotent, exception-safe cleanup of:
        - HTTP Server
        - DNS Interceptor
        - Update Manager Session
        - Access Point
        - LED State
        - Portal State

        ConnectionManager automatically handles connection restoration when stopping AP,
        so we just need to trigger cleanup and it will restore previous connection state.

        Returns:
            bool: True if cleanup was successful, False if issues were detected
        """
        import gc

        cleanup_successful = True

        try:
            # Stop HTTP server
            self._stop_http_server()

            # Stop DNS interceptor
            self._stop_dns_interceptor()

            # Reset Update Manager session
            if self._update_manager:
                try:
                    self._update_manager.reset_session()
                except Exception as e:
                    self.logger.warning(f"Error resetting update manager session: {e}")

            # Stop access point with automatic connection restoration
            # ConnectionManager will reconnect if we were connected before entering AP mode
            try:
                if self.connection_manager:
                    await self.connection_manager.stop_access_point(restore_connection=True)
            except Exception as ap_e:
                self.logger.warning(f"Error stopping access point: {ap_e}")
                cleanup_successful = False

            # Clear LED
            try:
                self.pixel.clear()
            except Exception as led_e:
                self.logger.warning(f"Error clearing LED: {led_e}")

            # Reset portal state
            self.portal = PortalState()

            # Force garbage collection to release socket resources
            gc.collect()

            return cleanup_successful

        except Exception as e:
            self.logger.error(f"Error during portal cleanup: {e}")
            return False
