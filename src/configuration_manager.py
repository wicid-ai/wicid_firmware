import json
import os
import time

import supervisor  # type: ignore[import-untyped]  # CircuitPython-only module
from adafruit_httpserver import JSONResponse, Request, Response

from connection_manager import ConnectionManager
from dns_interceptor import DNSInterceptor
from logging_helper import logger
from manager_base import ManagerBase
from pixel_controller import PixelController
from scheduler import Scheduler
from utils import suppress


class ConfigurationManager(ManagerBase):
    """
    Singleton manager for device configuration lifecycle.

    Handles:
    - Configuration state management (missing/invalid/valid)
    - Portal lifecycle (AP, DNS, HTTP server)
    - Credential validation and testing
    - Update checking after successful connection
    - Restart decisions for configuration scenarios

    Use get_instance() to access the singleton instance.
    """

    _instance = None
    PROGRESS_STEP_PERCENT = 2  # Minimum % delta required to emit progress updates
    UPDATE_SERVICE_INTERVAL_MS = 200  # Interval between servicing HTTP during updates

    # --- Centralized error strings ---
    ERR_INVALID_REQUEST = "Invalid request data."
    ERR_EMPTY_SSID = "SSID cannot be empty."
    ERR_PWD_LEN = "Password must be 8-63 characters."
    ERR_SCAN_FAIL = "Could not scan for networks. Please try again."
    ERR_INVALID_ZIP = "ZIP code must be 5 digits."

    @classmethod
    def get_instance(cls):
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

    def _init(self):
        """Internal initialization method."""
        self.ap_ssid = "WICID-Setup"
        self.ap_password = None  # Open network
        self.setup_complete = False
        self.pixel = PixelController()  # Get singleton instance
        self.connection_manager = ConnectionManager.instance()  # Get ConnectionManager singleton
        self.last_connection_error = None
        self.pending_ready_at = None  # monotonic timestamp for scheduled activation
        self.dns_interceptor = None  # DNS interceptor for captive portal
        self.last_request_time = None  # timestamp of last HTTP request for idle timeout tracking
        self.user_connected = False  # flag indicating user has connected to portal
        self.pending_ssid = None  # SSID to test before activation
        self.pending_password = None  # Password to test before activation

        # Async validation state tracking
        self.validation_state = "idle"  # idle | validating_wifi | checking_updates | success | error
        self.validation_result = None  # dict with validation results
        self.validation_started_at = None  # timestamp when validation started
        self.validation_trigger = False  # flag to trigger validation in main loop
        self.activation_mode = None  # "continue" (no update) | "update" (download update)

        # Update progress tracking
        self.update_state = "idle"  # idle | downloading | verifying | unpacking | restarting | error
        self.update_trigger = False  # flag to trigger update in main loop
        self.update_progress_message = None  # detailed progress message for UI
        self.update_progress_pct = None  # progress percentage (0-100)
        self._update_manager = None  # Lazy-initialized UpdateManager
        self._http_server = None  # Store server reference for update polling
        self._last_progress_notify_state = None
        self._last_progress_notify_message = None
        self._last_progress_notify_pct = None
        self._last_progress_pct_value = None
        self._last_update_service_time = 0.0
        self._active_button_session = None  # Tracks session controller while portal active

        self.logger = logger("wicid.config")
        self._initialized = False  # Track if initialize() has been called (different from ManagerBase._initialized)

        # ManagerBase initialization flag
        self._manager_initialized = True

    def __init__(self):
        """Private constructor. Use get_instance() instead."""
        # Guard against re-initialization
        if getattr(self, "_manager_initialized", False):
            return
        # If _instance is already set, don't override it
        if ConfigurationManager._instance is None:
            ConfigurationManager._instance = self
        self._init()

    def shutdown(self):
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
                    self._cleanup_setup_portal()

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

    async def initialize(self, portal_runner=None):
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

        # Check if configuration exists
        try:
            with open("/secrets.json") as f:
                secrets = json.load(f)

            ssid = secrets.get("ssid", "").strip()
            password = secrets.get("password", "")
            zip_code = secrets.get("weather_zip", "")

            # Validate configuration is complete
            if not ssid or not password or not zip_code:
                self.logger.info("Configuration incomplete - entering setup")
                if portal_runner is None:
                    raise ValueError("portal_runner is required to enter setup mode")
                return await portal_runner(error=None)

            self.logger.debug(f"Configuration found for '{ssid}'")

            # Try to connect with existing credentials
            if self.connection_manager.is_connected():
                self.logger.info("Already connected")
                self._initialized = True
                return True

            # Attempt connection with saved credentials
            self.logger.info("Connecting with saved credentials")
            success, error_msg = await self.connection_manager.ensure_connected(timeout=60)

            if success:
                self.logger.info("WiFi connected")
                self._initialized = True
                return True
            else:
                # Connection failed - enter setup mode
                self.logger.warning(f"Connection failed: {error_msg}")
                self.logger.info("Entering setup mode")
                friendly_message, field = self._build_connection_error(ssid, error_msg)
                if portal_runner is None:
                    raise ValueError("portal_runner is required to enter setup mode")
                return await portal_runner(error={"message": friendly_message, "field": field})

        except (OSError, ValueError) as e:
            # Configuration file missing or invalid - normal for first boot
            self.logger.info(f"No configuration found: {e}")
            if portal_runner is None:
                raise ValueError("portal_runner is required to enter setup mode") from e
            return await portal_runner(error=None)

    async def run_portal(self, error=None, button_session=None):
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

        # Set error message if provided
        if error:
            self.last_connection_error = error

        # Reset button state tracking for this portal session
        if hasattr(self._active_button_session, "reset"):
            self._active_button_session.reset()

        # Start setup mode indicator (pulsing white LED)
        self.start_setup_indicator()

        # Start access point and web server
        self.start_access_point()

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
            self._cleanup_setup_portal()
            self._active_button_session = None
            return False

    def _build_connection_error(self, ssid: str, raw_error: str):
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

    def start_setup_indicator(self):
        """Begin pulsing white to indicate setup mode is active."""
        self.pixel.indicate_setup_mode()

    def _start_dns_interceptor(self, ap_ip):
        """
        Start the DNS interceptor for captive portal functionality.

        Args:
            ap_ip: Access point IP address

        Returns:
            bool: True if DNS interceptor started successfully
        """
        try:
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

    def _stop_dns_interceptor(self):
        """Stop the DNS interceptor and clean up resources"""
        if self.dns_interceptor:
            try:
                self.dns_interceptor.stop()
            except Exception as e:
                self.logger.warning(f"Error stopping DNS interceptor: {e}")
            finally:
                self.dns_interceptor = None

    def _check_dns_interceptor_health(self):
        """Check DNS interceptor health"""
        if not self.dns_interceptor:
            return False

        try:
            status = self.dns_interceptor.get_status()
            return status["healthy"]
        except Exception:
            return False

    def start_access_point(self):
        """Start the access point for setup mode using the connection manager."""
        # Start AP through ConnectionManager (handles all radio state transitions)
        ap_ip = self.connection_manager.start_access_point(self.ap_ssid, self.ap_password)

        # Start DNS interceptor for captive portal functionality
        dns_success = self._start_dns_interceptor(ap_ip)

        if dns_success:
            self.logger.info("Captive portal: DNS + HTTP")
        else:
            self.logger.info("Captive portal: HTTP only")

        # Ensure setup mode indicator is active whenever portal is running
        self.pixel.indicate_setup_mode()
        # Scheduler automatically handles LED animation updates at 25Hz

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
    def _validate_config_input(self, request: Request, ssid: str, password: str, zip_code: str):
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

    def _scan_ssids(self):
        """Scan for WiFi networks and return a list of available SSIDs.
        Uses the connection manager for scanning (ensures scanning is stopped).
        """
        self.logger.debug("Starting network scan for SSID validation")
        try:
            ssids = [net.ssid for net in self.connection_manager.scan_networks() if getattr(net, "ssid", None)]
            self.logger.debug(f"Found SSIDs: {ssids}")
            return ssids
        except Exception as e:
            self.logger.error(f"Network scan error: {e}")
            raise

    # --- Response helpers to keep code DRY and API-compatible ---
    def _json_ok(self, request: Request, data: dict):
        """Return a JSONResponse with 200 OK."""
        return JSONResponse(request, data)

    def _json_error(self, request: Request, message: str, field=None, code: int = 400, text: str = "Bad Request"):
        """Return an error JSON response with explicit status tuple.

        Using the base Response with a (code, text) tuple is compatible across library versions.
        """
        body = {"status": "error", "error": {"message": message, "field": field}}
        return Response(request, json.dumps(body), content_type="application/json", status=(code, text))

    def save_credentials(self, ssid, password, zip_code):
        """Save WiFi credentials and weather ZIP to secrets.json."""
        try:
            # Save all user settings to secrets.json (no config.json anymore)
            secrets = {"ssid": ssid, "password": password, "weather_zip": zip_code}

            with open("/secrets.json", "w") as f:
                json.dump(secrets, f)
            os.sync()

            # Store credentials for later testing before activation
            self.pending_ssid = ssid
            self.pending_password = password

            self.logger.info("Credentials saved")
            return True, None

        except Exception as e:
            self.logger.error(f"Error saving credentials: {e}")
            return False, str(e)

    async def blink_success(self):
        """Blink green to indicate success"""
        try:
            await self.pixel.blink_success()
        except Exception as e:
            self.logger.warning(f"Error in blink_success: {e}")

    async def run_web_server(self):
        """Run a simple web server to handle the setup interface"""
        from adafruit_httpserver import FileResponse, Request, Response, Server

        pool = self.connection_manager.get_socket_pool()
        server = Server(pool, "/www", debug=False)

        # Store server reference for update polling
        self._http_server = server

        # Initialize idle timeout tracking
        self.last_request_time = time.monotonic()
        setup_idle_timeout = int(os.getenv("SETUP_IDLE_TIMEOUT", "300"))

        # Helper to mark user as connected and clear retry state
        def _mark_user_connected():
            if not self.user_connected:
                self.user_connected = True
                self.connection_manager.clear_retry_count()
                self.logger.debug("User connected to portal")
            self.last_request_time = time.monotonic()

        # Serve the main page, pre-populating with settings and showing previous errors
        @server.route("/")
        def base(request: Request):
            _mark_user_connected()
            try:
                # Load current settings
                current_settings = {"ssid": "", "password": "", "zip_code": ""}
                with suppress(Exception):
                    with open("/secrets.json") as f:
                        secrets = json.load(f)

                    current_settings["ssid"] = secrets.get("ssid", "")
                    current_settings["password"] = secrets.get("password", "")
                    current_settings["zip_code"] = secrets.get("weather_zip", "")

                # Package data for the frontend
                try:
                    page_data = {"settings": current_settings, "error": self.last_connection_error}
                    self.last_connection_error = None

                    # Inject the data into the HTML
                    with open("/www/index.html") as f:
                        html = f.read()

                    data_script = f"<script>window.WICID_PAGE_DATA = {json.dumps(page_data)};</script>"
                    html = html.replace("</head>", f"{data_script}</head>")

                    return Response(request, html, content_type="text/html")

                except Exception:
                    return FileResponse(request, "index.html", "/www")

            except Exception as e:
                self.logger.warning(f"Error serving index page: {e}")
                return FileResponse(request, "index.html", "/www")

        # System information endpoint
        @server.route("/system-info", "GET")
        def system_info(request: Request):
            _mark_user_connected()
            try:
                from utils import get_machine_type, get_os_version_string_pretty_print

                # Get basic system info
                machine_type = get_machine_type()
                os_version_string = get_os_version_string_pretty_print()
                wicid_version = os.getenv("VERSION", "unknown")

                # Load manifest for detailed machine type
                with suppress(Exception):
                    with open("/manifest.json") as f:
                        manifest = json.load(f)
                    machine_types = manifest.get("target_machine_types", [])
                    if machine_types:
                        machine_type = machine_types[0]

                return self._json_ok(
                    request,
                    {"machine_type": machine_type, "os_version": os_version_string, "wicid_version": wicid_version},
                )

            except Exception as e:
                self.logger.error(f"Error getting system info: {e}")
                return self._json_error(
                    request, "Could not retrieve system information.", code=500, text="Internal Server Error"
                )

        # WiFi network scanning endpoint
        @server.route("/scan", "GET")
        def scan_networks(request: Request):
            _mark_user_connected()
            try:
                self.logger.debug("Scanning for WiFi networks")
                networks = []

                # Scan for available networks using the connection manager
                for network in self.connection_manager.scan_networks():
                    # Only add networks with SSIDs (skip hidden networks)
                    if network.ssid:
                        network_info = {
                            "ssid": network.ssid,
                            "rssi": network.rssi,
                            "channel": network.channel,
                            "authmode": str(network.authmode),
                        }
                        # Avoid duplicates (same SSID can appear on multiple channels)
                        if not any(n["ssid"] == network.ssid for n in networks):
                            networks.append(network_info)

                # Sort by signal strength (RSSI, higher is better)
                networks.sort(key=lambda x: x["rssi"], reverse=True)

                self.logger.debug(f"Found {len(networks)} networks")
                return self._json_ok(request, {"networks": networks})

            except Exception as e:
                self.logger.error(f"Error scanning networks: {e}")
                return self._json_error(
                    request, "Could not scan for networks. Please try again.", code=500, text="Internal Server Error"
                )

        # Android connectivity check endpoints
        @server.route("/generate_204", "GET")
        def android_generate_204(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        @server.route("/gen_204", "GET")
        def android_gen_204(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        @server.route("/connectivitycheck/gstatic/generate_204", "GET")
        def android_gstatic_204(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        # iOS connectivity check endpoints
        @server.route("/hotspot-detect.html", "GET")
        def ios_hotspot_detect(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        @server.route("/library/test/success.html", "GET")
        def ios_library_success(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        # Windows/Linux connectivity check endpoints
        @server.route("/ncsi.txt", "GET")
        def windows_ncsi(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        @server.route("/connecttest.txt", "GET")
        def windows_connecttest(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        # Generic captive portal detection route
        @server.route("/redirect", "GET")
        def generic_captive_redirect(request: Request):
            _mark_user_connected()
            return self._create_captive_redirect_response(request)

        # Handle form submission with two-stage validation
        @server.route("/configure", "POST")
        def configure(request: Request):
            _mark_user_connected()
            try:
                self.logger.debug("Starting configure function")
                data = request.json()
                self.logger.debug(f"JSON parsed successfully, type: {type(data)}")

                # Validate that JSON parsing returned a dictionary
                if not isinstance(data, dict):
                    self.logger.error(f"JSON parsing failed, got: {type(data)} = {data}")
                    return self._json_error(request, self.ERR_INVALID_REQUEST)

                self.logger.debug("Extracting form data")
                ssid = data.get("ssid", "").strip()
                password = data.get("password", "")
                zip_code = data.get("zip_code", "")
                self.logger.debug(f"Extracted - SSID: '{ssid}', password length: {len(password)}")

                # --- Stage 1: Pre-flight Checks (AP remains active) ---
                self.logger.debug("Stage 1: Performing pre-flight checks...")

                self.logger.debug(
                    f"About to check password length. Password type: {type(password)}, value: {repr(password)}"
                )
                resp = self._validate_config_input(request, ssid, password, zip_code)
                if resp:
                    return resp
                self.logger.debug("Input validation passed")

                # Check if SSID is a real, scanned network
                try:
                    available_ssids = self._scan_ssids()
                except Exception as scan_e:
                    self.logger.warning(f"SSID validation scan failed: {scan_e}")
                    return self._json_error(
                        request, self.ERR_SCAN_FAIL, field="ssid", code=500, text="Internal Server Error"
                    )

                if ssid not in available_ssids:
                    return self._json_error(request, self._net_not_found_message(ssid), field="ssid")

                # Pre-checks passed - save credentials and trigger async validation
                self.logger.debug("✓ Pre-flight checks passed. Saving credentials...")
                save_ok, save_err = self.save_credentials(ssid, password, zip_code)
                if not save_ok:
                    self.logger.error(f"✗ Failed to save credentials: {save_err}")
                    return self._json_error(
                        request, f"Could not save settings: {save_err}", code=500, text="Internal Server Error"
                    )

                self.logger.debug("✓ Credentials saved. Triggering async validation...")
                # Initialize validation state and trigger validation in main loop
                self.validation_state = "validating_wifi"
                self.validation_result = None
                self.validation_started_at = time.monotonic()
                self.validation_trigger = True

                return self._json_ok(request, {"status": "validation_started", "status_url": "/validation-status"})

            except Exception as e:
                self.logger.error(f"Fatal error in /configure: {e}")
                self.last_connection_error = {"message": "An unexpected server error occurred.", "field": None}
                try:
                    scheduler = Scheduler.instance()
                    scheduler.schedule_now(
                        coroutine=self.pixel.blink_error,
                        priority=5,
                        name="Portal Blink Error",
                    )
                except Exception as led_e:
                    self.logger.warning(f"Error scheduling blink_error: {led_e}")
                try:
                    self.start_access_point()
                except Exception as ap_e:
                    self.logger.error(f"Could not restart AP after fatal error: {ap_e}")
                # Do not send a response here, as the connection is likely dead.
                # The client will time out, which is expected in a fatal server error.
                return None

        # Get validation status (polled by client during async validation)
        @server.route("/validation-status", "GET")
        def validation_status(request: Request):
            _mark_user_connected()
            try:
                # Check for validation timeout (2 minutes)
                if self.validation_started_at is not None:
                    elapsed = time.monotonic() - self.validation_started_at
                    if elapsed > 120:
                        self.validation_state = "error"
                        self.validation_result = {
                            "error": {"message": "Validation timed out. Please try again.", "field": None}
                        }
                        self.validation_trigger = False

                # Build response based on current state
                response_data = {"state": self.validation_state}

                if self.validation_state == "validating_wifi":
                    response_data["message"] = "Testing WiFi credentials..."
                elif self.validation_state == "checking_updates":
                    response_data["message"] = "Checking for updates..."
                elif self.validation_state == "success":
                    if self.validation_result:
                        response_data["message"] = "Validation complete"
                        response_data["update_available"] = self.validation_result.get("update_available", False)
                        if self.validation_result.get("update_available"):
                            response_data["update_info"] = self.validation_result.get("update_info", {})
                elif self.validation_state == "error":
                    if self.validation_result and "error" in self.validation_result:
                        response_data["error"] = self.validation_result["error"]
                    else:
                        response_data["error"] = {"message": "Validation failed", "field": None}

                return self._json_ok(request, response_data)

            except Exception as e:
                self.logger.error(f"Error in /validation-status: {e}")
                return self._json_error(
                    request, "Could not get validation status", code=500, text="Internal Server Error"
                )

        # Handle activation request (no update case)
        @server.route("/activate", "POST")
        def activate(request: Request):
            _mark_user_connected()
            try:
                self.logger.info("Activation requested (no update)")
                # Validation must be in success state
                if self.validation_state != "success":
                    return self._json_error(
                        request, "Cannot activate - validation not complete", code=400, text="Bad Request"
                    )

                # Set activation mode and schedule activation
                self.activation_mode = "continue"
                self.pending_ready_at = time.monotonic() + 4.0
                return self._json_ok(request, {"status": "activating"})

            except Exception as e:
                self.logger.error(f"Error in /activate: {e}")
                return self._json_error(request, "Activation failed", code=500, text="Internal Server Error")

        # Handle update installation request
        @server.route("/update-now", "POST")
        def update_now(request: Request):
            _mark_user_connected()
            try:
                self.logger.info("Update installation requested by user")
                # Validation must be in success state with update available
                if self.validation_state != "success":
                    return self._json_error(
                        request, "Cannot install update - validation not complete", code=400, text="Bad Request"
                    )

                if not self.validation_result or not self.validation_result.get("update_available"):
                    return self._json_error(
                        request, "Cannot install update - no update available", code=400, text="Bad Request"
                    )

                # Trigger async update process
                self.update_state = "downloading"
                self.update_trigger = True
                self.activation_mode = "update"

                return self._json_ok(request, {"status": "update_started", "status_url": "/update-status"})
            except Exception as e:
                self.logger.error(f"Error in /update-now: {e}")
                return self._json_error(request, "Update installation failed", code=500, text="Internal Server Error")

        # Get update progress status (polled by client during update)
        @server.route("/update-status", "GET")
        def update_status(request: Request):
            _mark_user_connected()
            try:
                response_data = {"state": self.update_state}

                # Use detailed progress message from UpdateManager if available
                if self.update_progress_message:
                    response_data["message"] = self.update_progress_message
                else:
                    # Fallback to simple state-based messages
                    if self.update_state == "downloading":
                        response_data["message"] = "Downloading update..."
                    elif self.update_state == "verifying":
                        response_data["message"] = "Verifying download..."
                    elif self.update_state == "unpacking":
                        response_data["message"] = "Unpacking update..."
                    elif self.update_state == "restarting":
                        response_data["message"] = "Restarting device..."
                    elif self.update_state == "error":
                        response_data["message"] = "Update failed"
                        response_data["error"] = True

                # Include progress percentage if available
                if self.update_progress_pct is not None:
                    response_data["progress"] = self.update_progress_pct

                return self._json_ok(request, response_data)

            except Exception as e:
                self.logger.error(f"Error in /update-status: {e}")
                return self._json_error(request, "Could not get update status", code=500, text="Internal Server Error")

        # Start the server
        server_ip = self.connection_manager.get_ap_ip_address()
        server.start(host=server_ip, port=80)
        self.logger.info(f"Server started at http://{server_ip}")

        # Small debounce delay
        debounce_end = time.monotonic() + 0.5
        while time.monotonic() < debounce_end:
            await Scheduler.sleep(0.05)

        self.logger.info("Starting main server loop")
        self.logger.info("Visit: http://192.168.4.1/ while connected to WICID-Setup")

        # Main server loop - listen for button press to exit
        while not self.setup_complete:
            try:
                # Service HTTP server and DNS interceptor
                # Note: Pixel controller animation now handled by scheduler
                self.tick()

                # Check for idle timeout (no user interaction)
                if self.last_request_time is not None:
                    idle_time = time.monotonic() - self.last_request_time
                    if idle_time >= setup_idle_timeout:
                        self.logger.info(f"Setup idle timeout exceeded ({idle_time:.0f}s). Restarting to retry...")
                        # Comprehensive cleanup before restarting
                        self._cleanup_setup_portal()
                        supervisor.reload()

                # Execute async validation if triggered
                if self.validation_trigger and self.validation_state in ["validating_wifi", "checking_updates"]:
                    await self._execute_async_validation()

                # Execute async update if triggered
                if self.update_trigger and self.update_state in ["downloading", "verifying", "unpacking"]:
                    await self._execute_async_update(server, server_ip)

                # If activation scheduled (after validation or user action), execute activation
                # Note: Update mode is handled by _execute_async_update, not here
                if self.pending_ready_at is not None and time.monotonic() >= self.pending_ready_at:
                    if self.activation_mode == "continue":
                        # Continue mode: credentials validated, no update available
                        self.logger.info("Executing activation (continue mode)")

                        # Stop HTTP server first to stop accepting new requests
                        try:
                            server.stop()
                            self.logger.debug("HTTP server stopped")
                        except Exception as e:
                            self.logger.warning(f"Error stopping HTTP server: {e}")

                        # Stop DNS interceptor
                        self._stop_dns_interceptor()
                        self.logger.debug("DNS interceptor stopped")

                        # Flash green to indicate success
                        try:
                            await self.pixel.blink_success()
                        except Exception as led_e:
                            self.logger.warning(f"Error flashing LED: {led_e}")

                        # Stop access point (already connected to WiFi in station mode from validation)
                        try:
                            self.connection_manager.stop_access_point()
                            self.logger.info("Access point stopped")
                        except Exception as e:
                            self.logger.warning(f"Error stopping access point: {e}")

                        # Verify WiFi connection preserved, reconnect if needed
                        if not self.connection_manager.is_connected():
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

                        # Final cleanup (state, LED, etc.)
                        self._cleanup_setup_portal()

                        self.logger.info("Setup complete - continuing in normal mode")
                        self.setup_complete = True
                        return True
                    else:
                        # Unknown or update mode (update is handled by _execute_async_update)
                        self.logger.debug(f"Ignoring pending_ready_at for mode: {self.activation_mode}")
                        self.pending_ready_at = None

                # Check for button interrupt via session
                if self._active_button_session and self._active_button_session.safe_mode_ready():
                    self.logger.info("Safe Mode requested (setup portal)")
                    self._cleanup_setup_portal()
                    # Session handoff requeues SAFE action for ModeManager
                    return False

                exit_reason = (
                    self._active_button_session.consume_exit_request() if self._active_button_session else None
                )
                if exit_reason:
                    self.logger.debug(f"Setup exit requested via {exit_reason}")

                    cleanup_successful = self._cleanup_setup_portal()

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
        self._cleanup_setup_portal()
        server.stop()
        self._active_button_session = None
        return self.setup_complete

    def tick(self):
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

    def _update_progress_callback(self, state, message, progress_pct):
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

        state_changed = state != self._last_progress_notify_state
        message_changed = message != self._last_progress_notify_message
        progress_changed = self._progress_delta_trigger(progress_pct)

        self.update_state = state
        self.update_progress_message = message
        self.update_progress_pct = progress_pct

        force_progress = (
            state == "downloading" or state == "verifying" or state == "unpacking"
        ) and progress_pct is not None

        if not (state_changed or message_changed or progress_changed or force_progress):
            return

        self._last_progress_notify_state = state
        self._last_progress_notify_message = message
        self._last_progress_notify_pct = progress_pct
        self._last_progress_pct_value = self._normalize_progress(progress_pct)

        self.logger.debug(f"Update progress: {state} - {message} ({progress_pct}%)")

    def _normalize_progress(self, progress_pct):
        """Convert progress value to int 0-100 when possible; return None otherwise."""
        if progress_pct is None:
            return None
        try:
            progress_val = int(progress_pct)
            return max(0, min(progress_val, 100))
        except (ValueError, TypeError):
            return None

    def _progress_delta_trigger(self, progress_pct):
        """
        Determine if progress change alone warrants emitting an update.

        Returns True when:
        - Progress switches between determinate/indeterminate
        - Numeric progress changes by PROGRESS_STEP_PERCENT or more
        - Non-numeric progress value changes
        """
        normalized = self._normalize_progress(progress_pct)
        last_normalized = self._last_progress_pct_value

        # Determinate progress comparison
        if normalized is not None:
            if last_normalized is None:
                return True
            return abs(normalized - last_normalized) >= self.PROGRESS_STEP_PERCENT

        # Indeterminate progress - defer to raw value comparison
        return progress_pct != self._last_progress_notify_pct

    def _service_update_timeslice(self):
        """Allow update loop to service HTTP/DNS without re-entering frequently."""
        now = time.monotonic()
        if (now - self._last_update_service_time) * 1000.0 < self.UPDATE_SERVICE_INTERVAL_MS:
            return
        self._last_update_service_time = now
        try:
            self.tick()
        except Exception as e:
            self.logger.debug(f"Error servicing update requests: {e}")

    async def _sleep_with_portal_service(self, seconds):
        """Sleep while continuing to service portal networking."""
        target = time.monotonic() + max(0.0, seconds)
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                break
            self._service_update_timeslice()
            await Scheduler.sleep(min(0.1, remaining))

    def _get_update_manager(self):
        """
        Get or create UpdateManager instance with progress callback.

        Lazy initialization ensures UpdateManager has WiFi access and callback configured.

        Returns:
            UpdateManager: Instance with progress callback configured
        """
        if self._update_manager is None:
            from update_manager import UpdateManager

            self._update_manager = UpdateManager(
                progress_callback=self._update_progress_callback, service_callback=self._service_update_timeslice
            )
        return self._update_manager

    async def _execute_async_update(self, server, server_ip):
        """
        Execute async update workflow using UpdateManager.

        UpdateManager handles download, verification, and extraction with proper
        LED feedback and error handling. We observe progress via callback.

        Called from main server loop when update_trigger is set.
        """
        try:
            if self.update_state == "downloading":
                self.logger.info("Initiating update download")
                update_manager = self._get_update_manager()

                # UpdateManager cached update_info from check_for_updates()
                try:
                    download_success = await update_manager.download_update()
                except ValueError as e:
                    self.logger.error(f"Update download failed: {e}")
                    await self._handle_setup_update_failure(server, f"Invalid update request: {e}")
                    return
                except RuntimeError as e:
                    # Critical programming errors - re-raise to propagate to main() and trigger reboot
                    self.logger.critical(f"Critical update download error: {e}")
                    self.update_state = "error"
                    self.update_trigger = False
                    raise

                if not download_success:
                    self.logger.error("Update download failed")
                    await self._handle_setup_update_failure(server, "Download failed")
                    return

                self.logger.info("Update ready for installation")

                # Move to restarting state
                self.update_state = "restarting"
                self.update_trigger = False

                # Give client time to see "Restarting..." (2 seconds)
                await self._sleep_with_portal_service(2)

                # Stop server and AP
                try:
                    server.stop()
                    self.logger.debug("HTTP server stopped")
                except Exception as e:
                    self.logger.warning(f"Error stopping HTTP server: {e}")

                self._stop_dns_interceptor()

                try:
                    self.connection_manager.stop_access_point()
                except Exception as e:
                    self.logger.warning(f"Error stopping AP: {e}")

                # Hard reset to trigger update installation in boot.py
                self.logger.info("Rebooting to install update")
                import microcontroller

                microcontroller.reset()

        except Exception as e:
            self.logger.error(f"Error during async update: {e}")
            await self._handle_setup_update_failure(server, f"Async update error: {e}")

    async def _handle_setup_update_failure(self, server, reason):
        """
        Gracefully exit setup mode after an update failure and resume normal mode.
        """
        self.logger.warning(f"Update failed in setup mode: {reason}. Continuing with current firmware.")
        self.update_trigger = False
        self.update_state = "restarting"
        self.update_progress_message = "Restarting device..."
        self.update_progress_pct = 100
        self.pending_ready_at = None
        self.activation_mode = None
        self.setup_complete = True

        try:
            server.stop()
            self.logger.debug("HTTP server stopped after update failure")
        except Exception as e:
            self.logger.debug(f"HTTP server stop after failure raised: {e}")

        try:
            self._cleanup_setup_portal()
        except Exception as cleanup_error:
            self.logger.warning(f"Cleanup after update failure reported: {cleanup_error}")

        # Allow the client to poll one last status update before restarting
        await self._sleep_with_portal_service(1)
        supervisor.reload()

    async def _execute_async_validation(self):
        """
        Execute async validation workflow: test WiFi credentials and check for updates.
        Updates validation_state and validation_result as it progresses.
        Called from main server loop when validation_trigger is set.
        """
        try:
            # Test WiFi credentials
            if self.validation_state == "validating_wifi":
                if not self.pending_ssid or not self.pending_password:
                    self.logger.error("No credentials to validate")
                    self.validation_state = "error"
                    self.validation_result = {
                        "error": {"message": "No credentials available for validation", "field": None}
                    }
                    self.validation_trigger = False
                    return

                self.logger.info(f"Validating WiFi credentials for '{self.pending_ssid}'")
                success, error_msg = await self.connection_manager.test_credentials_from_ap(
                    self.pending_ssid, self.pending_password
                )

                if not success:
                    # Credentials failed
                    self.logger.warning(f"WiFi validation failed: {error_msg}")
                    self.validation_state = "error"

                    # Extract error message from dict if present
                    if isinstance(error_msg, dict):
                        error_message = error_msg.get("message", "WiFi connection test failed")
                        error_field = error_msg.get("field", "password")
                    else:
                        error_message = str(error_msg) if error_msg else "WiFi connection test failed"
                        error_field = "password"

                    self.validation_result = {"error": {"message": error_message, "field": error_field}}
                    self.validation_trigger = False

                    # Clear credentials for retry
                    self.pending_ssid = None
                    self.pending_password = None
                    return

                # WiFi validation successful - move to update check
                self.logger.info("WiFi credentials validated successfully")
                self.validation_state = "checking_updates"
                # Don't return - continue to update check

            # Check for updates
            if self.validation_state == "checking_updates":
                try:
                    update_manager = self._get_update_manager()

                    # Check for updates
                    update_info = update_manager.check_for_updates()

                    if update_info:
                        # Update available
                        self.logger.info(f"Update available: {update_info.get('version')}")
                        self.validation_state = "success"
                        self.validation_result = {"update_available": True, "update_info": update_info}
                    else:
                        # No update available
                        self.logger.info("No updates available")
                        self.validation_state = "success"
                        self.validation_result = {"update_available": False}

                    self.validation_trigger = False

                except Exception as update_e:
                    # Update check failed - but WiFi works, so continue anyway
                    self.logger.warning(f"Update check failed: {update_e}")
                    self.validation_state = "success"
                    self.validation_result = {"update_available": False}
                    self.validation_trigger = False

        except Exception as e:
            self.logger.error(f"Error during async validation: {e}")
            self.validation_state = "error"
            self.validation_result = {"error": {"message": f"Validation error: {e}", "field": None}}
            self.validation_trigger = False

    def _restart_portal_services(self, server, server_ip):
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

    def _cleanup_setup_portal(self):
        """
        Cleanup of setup portal resources and state.

        ConnectionManager automatically handles connection restoration when stopping AP,
        so we just need to trigger cleanup and it will restore previous connection state.

        Returns:
            bool: True if cleanup was successful, False if issues were detected
        """
        cleanup_successful = True

        try:
            # Stop DNS interceptor
            self._stop_dns_interceptor()

            # Verify DNS interceptor is fully stopped
            if hasattr(self, "dns_interceptor") and self.dns_interceptor:
                # _stop_dns_interceptor() already calls stop() which handles cleanup
                # Just ensure the reference is cleared
                self.dns_interceptor = None

            # Stop access point with automatic connection restoration
            # ConnectionManager will reconnect if we were connected before entering AP mode
            try:
                self.connection_manager.stop_access_point(restore_connection=True)
            except Exception as ap_e:
                self.logger.warning(f"Error stopping access point: {ap_e}")
                cleanup_successful = False

            # Clear LED
            try:
                self.pixel.clear()
            except Exception as led_e:
                self.logger.warning(f"Error clearing LED: {led_e}")

            # Reset setup state
            self.setup_complete = False
            self.pending_ready_at = None
            self.last_connection_error = None

            return cleanup_successful

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            return False
