"""HTTP route handlers for the configuration portal."""

import json
import os
import time

from adafruit_httpserver import (  # type: ignore[import-not-found, attr-defined]  # CircuitPython-only module
    FileResponse,
    Request,
    Response,
)

from core.app_typing import Any
from core.logging_helper import logger
from utils.utils import suppress


class PortalRoutes:
    """
    HTTP route handlers for the configuration portal.

    Extracted from ConfigurationManager to improve testability and separation of concerns.
    Each route handler is a method that takes a Request and returns a Response.
    """

    # Consolidated captive portal detection paths
    CAPTIVE_PORTAL_PATHS = [
        "/generate_204",  # Android primary
        "/gen_204",  # Android alternate
        "/connectivitycheck/gstatic/generate_204",  # Android Chrome
        "/hotspot-detect.html",  # iOS primary
        "/library/test/success.html",  # iOS alternate
        "/ncsi.txt",  # Windows
        "/connecttest.txt",  # Windows alternate
        "/redirect",  # Generic fallback
    ]

    def __init__(self, config_manager: Any) -> None:
        """
        Initialize route handlers with reference to ConfigurationManager.

        Args:
            config_manager: ConfigurationManager instance for accessing state and methods
        """
        self.config = config_manager
        self.logger = logger("wicid.portal_routes")

    def _mark_user_connected(self) -> None:
        """Mark user as connected and update request timestamp."""
        if not self.config.portal.user_connected:
            self.config.portal.user_connected = True
            if self.config.connection_manager:
                self.config.connection_manager.clear_retry_count()
            self.logger.debug("User connected to portal")
        self.config.portal.last_request_time = time.monotonic()

    def handle_index(self, request: Request) -> Response:
        """Serve the main configuration page with current settings and errors."""
        self._mark_user_connected()
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
                page_data = {"settings": current_settings, "error": self.config.portal.last_connection_error}
                self.config.portal.last_connection_error = None

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

    def handle_system_info(self, request: Request) -> Response:
        """Return system information (machine type, OS version, WICID version)."""
        self._mark_user_connected()
        try:
            from utils.utils import get_machine_type, get_os_version_string_pretty_print

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

            return self.config._json_ok(
                request,
                {"machine_type": machine_type, "os_version": os_version_string, "wicid_version": wicid_version},
            )

        except Exception as e:
            self.logger.error(f"Error getting system info: {e}")
            return self.config._json_error(
                request, "Could not retrieve system information.", code=500, text="Internal Server Error"
            )

    def handle_scan(self, request: Request) -> Response:
        """Scan for available WiFi networks and return sorted list."""
        self._mark_user_connected()
        try:
            self.logger.debug("Scanning for WiFi networks")
            networks: list[dict[str, Any]] = []

            if not self.config.connection_manager:
                return self.config._json_error(request, "ConnectionManager not initialized")

            # Scan for available networks using the connection manager
            for network in self.config.connection_manager.scan_networks():
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
            return self.config._json_ok(request, {"networks": networks})

        except Exception as e:
            self.logger.error(f"Error scanning networks: {e}")
            return self.config._json_error(
                request, "Could not scan for networks. Please try again.", code=500, text="Internal Server Error"
            )

    def handle_captive_redirect(self, request: Request) -> Response:
        """Handle all captive portal detection requests with appropriate redirects."""
        self._mark_user_connected()
        return self.config._create_captive_redirect_response(request)

    def handle_configure(self, request: Request) -> Response:
        """Handle configuration form submission and trigger async validation."""
        self._mark_user_connected()
        try:
            self.logger.debug("Starting configure function")
            data = request.json()
            self.logger.debug(f"JSON parsed successfully, type: {type(data)}")

            # Validate that JSON parsing returned a dictionary
            if not isinstance(data, dict):
                self.logger.error(f"JSON parsing failed, got: {type(data)} = {data}")
                return self.config._json_error(request, self.config.ERR_INVALID_REQUEST)

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
            resp = self.config._validate_config_input(request, ssid, password, zip_code)
            if resp:
                return resp
            self.logger.debug("Input validation passed")

            # Check if SSID is a real, scanned network
            try:
                available_ssids = self.config._scan_ssids()
            except Exception as scan_e:
                self.logger.warning(f"SSID validation scan failed: {scan_e}")
                return self.config._json_error(
                    request, self.config.ERR_SCAN_FAIL, field="ssid", code=500, text="Internal Server Error"
                )

            if ssid not in available_ssids:
                return self.config._json_error(request, self.config._net_not_found_message(ssid), field="ssid")

            # Pre-checks passed - save credentials and trigger async validation
            self.logger.debug("✓ Pre-flight checks passed. Saving credentials...")
            save_ok, save_err = self.config.save_credentials(ssid, password, zip_code)
            if not save_ok:
                self.logger.error(f"✗ Failed to save credentials: {save_err}")
                return self.config._json_error(
                    request, f"Could not save settings: {save_err}", code=500, text="Internal Server Error"
                )

            self.logger.debug("✓ Credentials saved. Triggering async validation...")
            # Initialize validation state and trigger validation in main loop
            self.config.validation.state = "validating_wifi"
            self.config.validation.result = None
            self.config.validation.started_at = time.monotonic()
            self.config.validation.trigger = True

            return self.config._json_ok(request, {"status": "validation_started", "status_url": "/validation-status"})

        except Exception as e:
            self.logger.error(f"Fatal error in /configure: {e}")
            self.config.portal.last_connection_error = {
                "message": "An unexpected server error occurred.",
                "field": None,
            }

            # Schedule error blink and AP restart using scheduler
            try:
                from core.scheduler import Scheduler

                scheduler = Scheduler.instance()
                scheduler.schedule_now(
                    coroutine=self.config.pixel.blink_error,
                    priority=5,
                    name="Portal Blink Error",
                )
            except Exception as led_e:
                self.logger.warning(f"Error scheduling blink_error: {led_e}")

            try:
                from core.scheduler import Scheduler

                scheduler = Scheduler.instance()
                scheduler.schedule_now(
                    coroutine=self.config.start_access_point,
                    priority=5,
                    name="Restart AP After Error",
                )
            except Exception as ap_e:
                self.logger.error(f"Could not restart AP after fatal error: {ap_e}")

            return None

    def handle_validation_status(self, request: Request) -> Response:
        """Return current validation status (polled by client)."""
        self._mark_user_connected()
        try:
            # Check for validation timeout (2 minutes)
            if self.config.validation.started_at is not None:
                elapsed = time.monotonic() - self.config.validation.started_at
                if elapsed > 120:
                    self.config.validation.state = "error"
                    self.config.validation.result = {
                        "error": {"message": "Validation timed out. Please try again.", "field": None}
                    }
                    self.config.validation.trigger = False

            # Build response based on current state
            response_data: dict[str, Any] = {"state": self.config.validation.state}

            if self.config.validation.state == "validating_wifi":
                response_data["message"] = "Testing WiFi credentials..."
            elif self.config.validation.state == "checking_updates":
                response_data["message"] = "Checking for updates..."
            elif self.config.validation.state == "success":
                if self.config.validation.result:
                    response_data["message"] = "Validation complete"
                    response_data["update_available"] = self.config.validation.result.get("update_available", False)
                    if self.config.validation.result.get("update_available"):
                        response_data["update_info"] = self.config.validation.result.get("update_info", {})
            elif self.config.validation.state == "error":
                if self.config.validation.result and "error" in self.config.validation.result:
                    response_data["error"] = self.config.validation.result["error"]
                else:
                    response_data["error"] = {"message": "Validation failed", "field": None}

            return self.config._json_ok(request, response_data)

        except Exception as e:
            self.logger.error(f"Error in /validation-status: {e}")
            return self.config._json_error(
                request, "Could not get validation status", code=500, text="Internal Server Error"
            )

    def handle_activate(self, request: Request) -> Response:
        """Handle activation request (no update case)."""
        self._mark_user_connected()
        try:
            self.logger.info("Activation requested (no update)")
            # Validation must be in success state
            if self.config.validation.state != "success":
                return self.config._json_error(
                    request, "Cannot activate - validation not complete", code=400, text="Bad Request"
                )

            # Set activation mode and schedule activation
            self.config.validation.activation_mode = "continue"
            self.config.portal.pending_ready_at = time.monotonic() + 4.0
            return self.config._json_ok(request, {"status": "activating"})

        except Exception as e:
            self.logger.error(f"Error in /activate: {e}")
            return self.config._json_error(request, "Activation failed", code=500, text="Internal Server Error")

    def handle_update_now(self, request: Request) -> Response:
        """Handle update installation request."""
        self._mark_user_connected()
        try:
            self.logger.info("Update installation requested by user")
            # Validation must be in success state with update available
            if self.config.validation.state != "success":
                return self.config._json_error(
                    request, "Cannot install update - validation not complete", code=400, text="Bad Request"
                )

            if not self.config.validation.result or not self.config.validation.result.get("update_available"):
                return self.config._json_error(
                    request, "Cannot install update - no update available", code=400, text="Bad Request"
                )

            # Trigger async update process
            self.config.update.state = "downloading"
            self.config.update.trigger = True
            self.config.validation.activation_mode = "update"

            return self.config._json_ok(request, {"status": "update_started", "status_url": "/update-status"})
        except Exception as e:
            self.logger.error(f"Error in /update-now: {e}")
            return self.config._json_error(
                request, "Update installation failed", code=500, text="Internal Server Error"
            )

    def handle_update_status(self, request: Request) -> Response:
        """Return current update progress (polled by client)."""
        self._mark_user_connected()
        try:
            response_data: dict[str, Any] = {"state": self.config.update.state}

            # Use detailed progress message from UpdateManager if available
            if self.config.update.progress_message:
                response_data["message"] = self.config.update.progress_message
            else:
                # Fallback to simple state-based messages
                if self.config.update.state == "downloading":
                    response_data["message"] = "Downloading update..."
                elif self.config.update.state == "verifying":
                    response_data["message"] = "Verifying download..."
                elif self.config.update.state == "unpacking":
                    response_data["message"] = "Unpacking update..."
                elif self.config.update.state == "restarting":
                    response_data["message"] = "Restarting device..."
                elif self.config.update.state == "error":
                    response_data["message"] = "Update failed"
                    response_data["error"] = True

            # Include progress percentage if available
            if self.config.update.progress_pct is not None:
                response_data["progress"] = self.config.update.progress_pct

            return self.config._json_ok(request, response_data)

        except Exception as e:
            self.logger.error(f"Error in /update-status: {e}")
            return self.config._json_error(
                request, "Could not connect to network.", field="password", code=500, text="Internal Server Error"
            )

    def register_routes(self, server: Any) -> None:
        """
        Register all route handlers with the HTTP server.

        Args:
            server: The HTTP server instance to register routes on
        """
        # Main page
        server.route("/")(self.handle_index)

        # API endpoints
        server.route("/system-info", "GET")(self.handle_system_info)
        server.route("/scan", "GET")(self.handle_scan)
        server.route("/configure", "POST")(self.handle_configure)
        server.route("/validation-status", "GET")(self.handle_validation_status)
        server.route("/activate", "POST")(self.handle_activate)
        server.route("/update-now", "POST")(self.handle_update_now)
        server.route("/update-status", "GET")(self.handle_update_status)

        # Consolidated captive portal detection endpoints
        for path in self.CAPTIVE_PORTAL_PATHS:
            server.route(path, "GET")(self.handle_captive_redirect)
