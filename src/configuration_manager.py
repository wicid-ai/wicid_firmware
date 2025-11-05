import os
import json
import time
import supervisor
from logging_helper import get_logger
from adafruit_httpserver import Response, Request, JSONResponse
from pixel_controller import PixelController
from utils import check_button_hold_duration, trigger_safe_mode
from dns_interceptor import DNSInterceptor
from wifi_manager import WiFiManager

class ConfigurationManager:
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
    
    # --- Centralized error strings ---
    ERR_INVALID_REQUEST = "Invalid request data."
    ERR_EMPTY_SSID = "SSID cannot be empty."
    ERR_PWD_LEN = "Password must be 8-63 characters."
    ERR_SCAN_FAIL = "Could not scan for networks. Please try again."
    ERR_INVALID_ZIP = "ZIP code must be 5 digits."

    @classmethod
    def get_instance(cls, button=None):
        """
        Get the singleton instance of ConfigurationManager.
        
        Args:
            button: Required on first call, optional on subsequent calls
            
        Returns:
            ConfigurationManager: The singleton instance
        """
        if cls._instance is None:
            if button is None:
                raise ValueError("button is required when creating ConfigurationManager instance")
            cls._instance = cls(button)
        return cls._instance

    def __init__(self, button):
        """Private constructor. Use get_instance() instead."""
        if ConfigurationManager._instance is not None:
            raise RuntimeError("Use ConfigurationManager.get_instance() instead of direct instantiation")
        
        self.ap_ssid = "WICID-Setup"
        self.ap_password = None  # Open network
        self.setup_complete = False
        self.pixel = PixelController()  # Get singleton instance
        self.wifi_manager = WiFiManager.get_instance(button)  # Get WiFiManager singleton
        self.button = button
        self.last_connection_error = None
        self.pending_ready_at = None  # monotonic timestamp for scheduled activation
        self.dns_interceptor = None  # DNS interceptor for captive portal
        self.last_request_time = None  # timestamp of last HTTP request for idle timeout tracking
        self.user_connected = False  # flag indicating user has connected to portal
        self.pending_ssid = None  # SSID to test before activation
        self.pending_password = None  # Password to test before activation
        self._initialized = False  # Track if initialize() has been called
        self.logger = get_logger('wicid.config')

    def initialize(self):
        """
        Initialize system configuration on boot.
        
        Checks if valid configuration exists and WiFi is connected.
        Enters setup mode if configuration is missing or WiFi connection fails.
        Blocks until configuration is complete and WiFi is connected.
        
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
            with open("/secrets.json", "r") as f:
                secrets = json.load(f)
            
            ssid = secrets.get('ssid', '').strip()
            password = secrets.get('password', '')
            zip_code = secrets.get('weather_zip', '')
            
            # Validate configuration is complete
            if not ssid or not password or not zip_code:
                self.logger.info("Configuration incomplete - entering setup")
                return self.run_portal(error={"message": "Configuration incomplete", "field": None})
            
            self.logger.debug(f"Configuration found for '{ssid}'")
            
            # Try to connect with existing credentials
            if self.wifi_manager.is_connected():
                self.logger.info("Already connected")
                self._initialized = True
                return True
            
            # Attempt connection with saved credentials
            self.logger.info("Connecting with saved credentials")
            success, error_msg = self.wifi_manager.ensure_connected(timeout=60)
            
            if success:
                self.logger.info("WiFi connected")
                self._initialized = True
                return True
            else:
                # Connection failed - enter setup mode
                self.logger.warning(f"Connection failed: {error_msg}")
                self.logger.info("Entering setup mode")
                friendly_message, field = self._build_connection_error(ssid, error_msg)
                return self.run_portal(error={
                    "message": friendly_message,
                    "field": field
                })
                
        except (OSError, ValueError) as e:
            # Configuration file missing or invalid
            self.logger.info(f"No configuration found: {e}")
            return self.run_portal(error={"message": "Initial setup required", "field": None})
    
    def run_portal(self, error=None):
        """
        Force entry into setup/configuration mode.
        
        Starts the captive portal regardless of existing configuration state.
        Used for:
        - Initial setup (no configuration)
        - Re-configuration (button hold from main loop)
        - Configuration errors
        
        Args:
            error: Optional error dict to display in portal ({'message': str, 'field': str})
        
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
        self.logger.info("Entering configuration mode")
        
        # Set error message if provided
        if error:
            self.last_connection_error = error
        
        # Start setup mode indicator (pulsing white LED)
        self.start_setup_indicator()
        
        # Start access point and web server
        self.start_access_point()
        
        # Run the web server (blocks until setup complete or cancelled)
        result = self.run_web_server()
        
        if result:
            self.logger.info("Configuration complete")
            self._initialized = True
            return True
        else:
            self.logger.info("Configuration cancelled - returning to caller")
            # Clean up and return False - caller decides next action
            # WiFiManager will automatically restore connection if needed
            self._cleanup_setup_portal()
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
            socket_pool = self.wifi_manager.get_socket_pool()
            self.dns_interceptor = DNSInterceptor(local_ip=ap_ip, socket_pool=socket_pool)
            
            if self.dns_interceptor.start():
                self.logger.info(f"DNS interceptor started on port 53")
                return True
            else:
                self.logger.warning("DNS interceptor failed - HTTP-only mode")
                self.dns_interceptor = None
                return False
                
        except Exception as e:
            self.logger.warning(f"DNS interceptor error: {e}")
            
            if hasattr(self, 'dns_interceptor') and self.dns_interceptor:
                try:
                    self.dns_interceptor.stop()
                except:
                    pass
            
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
            return status['healthy']
        except:
            return False

    def start_access_point(self):
        """Start the access point for setup mode using WiFiManager."""
        # Start AP through WiFiManager (handles all radio state transitions)
        ap_ip = self.wifi_manager.start_access_point(self.ap_ssid, self.ap_password)
        
        # Start DNS interceptor for captive portal functionality
        dns_success = self._start_dns_interceptor(ap_ip)
        
        if dns_success:
            self.logger.info("Captive portal: DNS + HTTP")
        else:
            self.logger.info("Captive portal: HTTP only")
        
        # Ensure setup mode indicator is active (already started in run_setup_mode)
        self.pixel.indicate_setup_mode()
        # Call tick immediately to ensure animation starts
        self.pixel.tick()

    def _get_os_from_user_agent(self, request: Request) -> str:
        """
        Parse user agent to determine operating system for captive portal handling.
        Returns: 'android', 'ios', 'windows', 'linux', 'macos', or 'unknown'
        """
        try:
            user_agent = ""
            if hasattr(request, 'headers') and request.headers:
                user_agent = request.headers.get('User-Agent', '').lower()
            
            if 'android' in user_agent or 'dalvik' in user_agent:
                return 'android'
            
            if any(ios_indicator in user_agent for ios_indicator in ['iphone', 'ipad', 'ipod', 'cfnetwork']):
                return 'ios'
            
            if 'windows' in user_agent or 'microsoft ncsi' in user_agent:
                return 'windows'
            
            if 'mac os x' in user_agent or 'darwin' in user_agent:
                return 'macos'
            
            if 'linux' in user_agent and 'android' not in user_agent:
                return 'linux'
            
            return 'unknown'
            
        except:
            return 'unknown'

    def _create_captive_redirect_response(self, request: Request, target_url: str = "/") -> Response:
        """
        Create appropriate redirect response for captive portal detection.
        Preserves setup portal functionality while triggering captive portal.
        """
        try:
            os_type = self._get_os_from_user_agent(request)
            
            # iOS devices expect HTML with meta redirect
            if os_type == 'ios':
                html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0; url={target_url}">
    <title>WICID Setup</title>
</head>
<body>
    <p>Redirecting to WICID setup...</p>
    <script>window.location.href = "{target_url}";</script>
</body>
</html>'''
                return Response(request, html_content, content_type="text/html")
            
            # All other operating systems use HTTP 302 redirect
            else:
                return Response(request, "", status=(302, "Found"), headers={"Location": target_url})
                
        except:
            # Fallback to simple redirect
            try:
                return Response(request, "", status=(302, "Found"), headers={"Location": target_url})
            except:
                # Last resort: HTML redirect
                fallback_html = f'<html><head><meta http-equiv="refresh" content="0; url={target_url}"></head><body>Redirecting...</body></html>'
                return Response(request, fallback_html, content_type="text/html")

    # --- Logging helper ---
    def _log(self, msg: str):
        self.logger.debug(msg)

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
            self._log(f"Password length check crashed: {e}")
            raise
        
        # Validate ZIP code format (5 digits)
        if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
            return self._json_error(request, self.ERR_INVALID_ZIP, field="zip_code")
        
        return None

    def _scan_ssids(self):
        """Scan for WiFi networks and return a list of available SSIDs.
        Uses WiFiManager for scanning (ensures scanning is stopped).
        """
        self._log("Starting network scan for SSID validation")
        try:
            ssids = [net.ssid for net in self.wifi_manager.scan_networks() if getattr(net, 'ssid', None)]
            self._log(f"Found SSIDs: {ssids}")
            return ssids
        except Exception as e:
            self._log(f"Network scan error: {e}")
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
        return Response(request, json.dumps(body), content_type='application/json', status=(code, text))

    def save_credentials(self, ssid, password, zip_code):
        """Save WiFi credentials and weather ZIP to secrets.json."""
        try:
            # Save all user settings to secrets.json (no config.json anymore)
            secrets = {
                "ssid": ssid,
                "password": password,
                "weather_zip": zip_code
            }
            
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

    def blink_success(self):
        """Blink green to indicate success"""
        try:
            self.pixel.blink_success()
        except Exception as e:
            self.logger.warning(f"Error in blink_success: {e}")

    def run_web_server(self):
        """Run a simple web server to handle the setup interface"""
        from adafruit_httpserver import Server, Request, Response, FileResponse
        
        pool = self.wifi_manager.get_socket_pool()
        server = Server(pool, "/www", debug=False)
        
        # Initialize idle timeout tracking
        self.last_request_time = time.monotonic()
        setup_idle_timeout = int(os.getenv("SETUP_IDLE_TIMEOUT", "300"))
        
        # Helper to mark user as connected and clear retry state
        def _mark_user_connected():
            if not self.user_connected:
                self.user_connected = True
                self.wifi_manager.clear_retry_count()
                self.logger.debug("User connected to portal")
            self.last_request_time = time.monotonic()
        
        # Serve the main page, pre-populating with settings and showing previous errors
        @server.route("/")
        def base(request: Request):
            _mark_user_connected()
            try:
                # Load current settings
                current_settings = {
                    'ssid': '', 'password': '', 'zip_code': ''
                }
                try:
                    with open("/secrets.json", "r") as f:
                        secrets = json.load(f)
                    
                    current_settings['ssid'] = secrets.get('ssid', '')
                    current_settings['password'] = secrets.get('password', '')
                    current_settings['zip_code'] = secrets.get('weather_zip', '')
                except:
                    pass  # Use empty values if secrets can't be loaded

                # Package data for the frontend
                try:
                    page_data = {
                        'settings': current_settings,
                        'error': self.last_connection_error
                    }
                    self.last_connection_error = None

                    # Inject the data into the HTML
                    with open('/www/index.html', 'r') as f:
                        html = f.read()
                    
                    data_script = f'<script>window.WICID_PAGE_DATA = {json.dumps(page_data)};</script>'
                    html = html.replace('</head>', f'{data_script}</head>')
                    
                    return Response(request, html, content_type='text/html')
                    
                except:
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
                try:
                    with open("/manifest.json", "r") as f:
                        manifest = json.load(f)
                    machine_types = manifest.get("target_machine_types", [])
                    if machine_types:
                        machine_type = machine_types[0]
                except Exception:
                    pass
                
                return self._json_ok(request, {
                    "machine_type": machine_type,
                    "os_version": os_version_string,
                    "wicid_version": wicid_version
                })
                
            except Exception as e:
                self.logger.error(f"Error getting system info: {e}")
                return self._json_error(request, "Could not retrieve system information.", code=500, text="Internal Server Error")
        
        # WiFi network scanning endpoint
        @server.route("/scan", "GET")
        def scan_networks(request: Request):
            _mark_user_connected()
            try:
                self.logger.debug("Scanning for WiFi networks")
                networks = []
                
                # Scan for available networks using WiFiManager
                for network in self.wifi_manager.scan_networks():
                    # Only add networks with SSIDs (skip hidden networks)
                    if network.ssid:
                        network_info = {
                            'ssid': network.ssid,
                            'rssi': network.rssi,
                            'channel': network.channel,
                            'authmode': str(network.authmode)
                        }
                        # Avoid duplicates (same SSID can appear on multiple channels)
                        if not any(n['ssid'] == network.ssid for n in networks):
                            networks.append(network_info)
                
                # Sort by signal strength (RSSI, higher is better)
                networks.sort(key=lambda x: x['rssi'], reverse=True)
                
                self.logger.debug(f"Found {len(networks)} networks")
                return self._json_ok(request, {"networks": networks})
                
            except Exception as e:
                self.logger.error(f"Error scanning networks: {e}")
                return self._json_error(request, "Could not scan for networks. Please try again.", code=500, text="Internal Server Error")

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
                self._log("Starting configure function")
                data = request.json()
                self._log(f"JSON parsed successfully, type: {type(data)}")
                
                # Validate that JSON parsing returned a dictionary
                if not isinstance(data, dict):
                    self._log(f"JSON parsing failed, got: {type(data)} = {data}")
                    return self._json_error(request, self.ERR_INVALID_REQUEST)
                
                self._log("Extracting form data")
                ssid = data.get('ssid', '').strip()
                password = data.get('password', '')
                zip_code = data.get('zip_code', '')
                self._log(f"Extracted - SSID: '{ssid}', password length: {len(password)}")

                # --- Stage 1: Pre-flight Checks (AP remains active) ---
                self._log("Stage 1: Performing pre-flight checks...")

                self._log(f"About to check password length. Password type: {type(password)}, value: {repr(password)}")
                resp = self._validate_config_input(request, ssid, password, zip_code)
                if resp:
                    return resp
                self._log("Input validation passed")

                # Check if SSID is a real, scanned network
                try:
                    available_ssids = self._scan_ssids()
                except Exception as scan_e:
                    self._log(f"SSID validation scan failed: {scan_e}")
                    return self._json_error(request, self.ERR_SCAN_FAIL, field="ssid", code=500, text="Internal Server Error")

                if ssid not in available_ssids:
                    return self._json_error(request, self._net_not_found_message(ssid), field="ssid")

                # Pre-checks passed - save credentials and prepare for activation
                self._log("✓ Pre-flight checks passed. Saving credentials...")
                save_ok, save_err = self.save_credentials(ssid, password, zip_code)
                if not save_ok:
                    self._log(f"✗ Failed to save credentials: {save_err}")
                    return self._json_error(request, f"Could not save settings: {save_err}", code=500, text="Internal Server Error")
                
                self._log("✓ Credentials saved. Waiting for user activation...")
                # Credentials saved - wait for user to explicitly request restart via /restart-now
                return self._json_ok(request, {"status": "precheck_success", "restart_delay": 0})

            except Exception as e:
                self._log(f"Fatal error in /configure: {e}")
                self.last_connection_error = {"message": "An unexpected server error occurred.", "field": None}
                self.pixel.blink_error()
                try:
                    self.start_access_point()
                except Exception as ap_e:
                    self._log(f"Could not restart AP after fatal error: {ap_e}")
                # Do not send a response here, as the connection is likely dead.
                # The client will time out, which is expected in a fatal server error.
                return None

        # Handle manual restart request
        @server.route("/restart-now", "POST")
        def restart_now(request: Request):
            _mark_user_connected()
            try:
                self._log("Manual restart requested by user")
                # Schedule activation 2 seconds in the future to allow client to detect portal closing
                self.pending_ready_at = time.monotonic() + 2.0
                return self._json_ok(request, {"status": "restarting"})
            except Exception as e:
                self._log(f"Error in /restart-now: {e}")
                return self._json_error(request, "Restart failed", code=500, text="Internal Server Error")
        
        
        # Start the server
        server_ip = self.wifi_manager.get_ap_ip_address()
        server.start(host=server_ip, port=80)
        self.logger.info(f"Server started at http://{server_ip}")

        # Wait for initial button release (from the press that got us into setup)
        while not self.button.value:
            self.pixel.tick()  # Keep pulsing animation active
            time.sleep(0.1)
        
        # Small debounce delay - keep pulsing during delay
        debounce_end = time.monotonic() + 0.5
        while time.monotonic() < debounce_end:
            self.pixel.tick()
            time.sleep(0.05)
        
        self.logger.info("Starting main server loop")
        self.logger.info("Visit: http://192.168.4.1/ while connected to WICID-Setup")
        
        # Main server loop - listen for button press to exit
        while not self.setup_complete:
            try:
                # Poll HTTP server for incoming requests
                server.poll()
                
                # Poll DNS interceptor for incoming queries (if active)
                if self.dns_interceptor:
                    try:
                        self.dns_interceptor.poll()
                        self._check_dns_interceptor_health()
                    except Exception as dns_e:
                        self.logger.error(f"DNS interceptor error: {dns_e}")
                        self._stop_dns_interceptor()
                
                # Update LED pulsing via controller
                self.pixel.tick()

                # Check for idle timeout (no user interaction)
                if self.last_request_time is not None:
                    idle_time = time.monotonic() - self.last_request_time
                    if idle_time >= setup_idle_timeout:
                        self.logger.info(f"Setup idle timeout exceeded ({idle_time:.0f}s). Restarting to retry...")
                        # Comprehensive cleanup before restarting
                        self._cleanup_setup_portal()
                        supervisor.reload()

                # If credentials were saved, wait for delay then test and activate
                if self.pending_ready_at is not None and time.monotonic() >= self.pending_ready_at:
                    self.logger.info("Testing credentials")
                    
                    # Stop HTTP server first to stop accepting new requests
                    try:
                        server.stop()
                        self.logger.debug("HTTP server stopped")
                    except Exception as e:
                        self.logger.warning(f"Error stopping HTTP server: {e}")
                    
                    # Stop DNS interceptor
                    self._stop_dns_interceptor()
                    self.logger.debug("DNS interceptor stopped")
                    
                    # Test credentials while AP is still broadcasting
                    # Client stays connected if credentials fail
                    if self.pending_ssid and self.pending_password:
                        self.logger.debug(f"Testing credentials for '{self.pending_ssid}'")
                        success, error_msg = self.wifi_manager.test_credentials_from_ap(
                            self.pending_ssid, 
                            self.pending_password
                        )
                        
                        if success:
                            self.logger.info("Credentials validated")
                            
                            # Flash green to indicate success
                            try:
                                self.pixel.blink_success()
                            except Exception as led_e:
                                self.logger.warning(f"Error flashing LED: {led_e}")
                            
                            # Stop HTTP server and DNS (already stopped above)
                            # AP stopped by WiFiManager after successful connection
                            
                            # Stop access point (already connected to WiFi in station mode)
                            try:
                                self.wifi_manager.stop_access_point()
                                self.logger.info("Access point stopped")
                            except Exception as e:
                                self.logger.warning(f"Error stopping access point: {e}")
                            
                            # Verify WiFi connection preserved, reconnect if needed
                            # ESP32 firmware bug sometimes loses connection when stopping AP
                            if not self.wifi_manager.is_connected():
                                self.logger.warning("WiFi connection lost after stopping AP - reconnecting")
                                success, error_msg = self.wifi_manager.ensure_connected(timeout=30)
                                if not success:
                                    self.logger.error(f"Failed to reconnect after AP stop: {error_msg}")
                                    # Fall through to continue anyway - modes will handle reconnection
                                else:
                                    self.logger.info("WiFi reconnected successfully")
                            else:
                                self.logger.debug("WiFi connection preserved after AP stop")
                            
                            # Final cleanup (state, LED, etc.)
                            self._cleanup_setup_portal()
                            
                            # Check for firmware updates
                            self.logger.info("Checking for updates")
                            try:
                                # Create session for update check
                                session = self.wifi_manager.create_session()
                                
                                from update_manager import UpdateManager
                                update_manager = UpdateManager(session)
                                
                                # Check and download updates (this will reboot if update found)
                                # Returns False if no update or download failed
                                update_found = update_manager.check_download_and_reboot(delay_seconds=1)
                                
                                if not update_found:
                                    # No update available - continue running
                                    self.logger.info("No updates available - continuing")
                                    self.setup_complete = True
                                    return True
                                # If update found, device will reboot above (never reaches here)
                                
                            except Exception as update_e:
                                self.logger.error(f"Update check failed: {update_e}")
                                # Continue running even if update check fails - already connected
                                self.logger.info("Setup complete - continuing")
                                self.setup_complete = True
                                return True
                        else:
                            self.logger.warning(f"Credential test failed: {error_msg}")
                            
                            # Flash red to indicate failure
                            try:
                                self.pixel.blink_error()
                            except Exception as led_e:
                                self.logger.warning(f"Error flashing LED: {led_e}")
                            
                            # Credentials failed - restart portal services
                            # Client is still connected to AP and can see error
                            self.last_connection_error = {
                                "message": error_msg or "WiFi connection test failed",
                                "field": "password"
                            }
                            
                            # Cancel pending activation
                            self.pending_ready_at = None
                            self.pending_ssid = None
                            self.pending_password = None
                            
                            # Restart portal services
                            self.logger.info("Restarting portal services")
                            try:
                                self._restart_portal_services(server, server_ip)
                                self.logger.info("Portal services restarted")
                            except Exception as restart_e:
                                self.logger.error(f"Error restarting portal services: {restart_e}")
                                # If restart fails, cleanup and let outer loop restart
                                self._cleanup_setup_portal()
                    else:
                        self.logger.warning("No credentials to test - ignoring activation request")
                        # Edge case: /restart-now called without /configure
                        # Reset pending state and stay in portal
                        self.pending_ready_at = None
                        # Portal continues running normally
                
                # Check for button press: 10s hold = Safe Mode, any other press = exit setup
                if not self.button.value:
                    hold_result = check_button_hold_duration(self.button, self.pixel)
                    
                    if hold_result == 'safe_mode':
                        self.logger.info("Safe Mode requested (10 second hold)")
                        # Comprehensive cleanup before triggering safe mode
                        self._cleanup_setup_portal()
                        trigger_safe_mode()
                        # This will restart, so we never reach here
                    else:
                        # Short press or 3-second hold: exit setup mode
                        self.logger.debug("Button pressed, exiting setup")
                        # Comprehensive cleanup before exiting
                        cleanup_successful = self._cleanup_setup_portal()
                        
                        if not cleanup_successful:
                            self.logger.warning("Cleanup completed with issues")
                        
                        time.sleep(0.2)  # Small debounce
                        return False
                
                # Small sleep to prevent busy-waiting while maintaining smooth LED animation
                # 5ms is fast enough for smooth pulsing (tick interval is 40ms) while being CPU-friendly
                time.sleep(0.005)
                
            except Exception as e:
                self.logger.error(f"Server error: {e}")
                time.sleep(1)
        
        # Comprehensive cleanup
        self._cleanup_setup_portal()
        server.stop()
        return self.setup_complete
    
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
        
        WiFiManager automatically handles connection restoration when stopping AP,
        so we just need to trigger cleanup and it will restore previous connection state.
        
        Returns:
            bool: True if cleanup was successful, False if issues were detected
        """
        cleanup_successful = True
        
        try:
            # Stop DNS interceptor
            self._stop_dns_interceptor()
            
            # Verify DNS interceptor is fully stopped
            if hasattr(self, 'dns_interceptor') and self.dns_interceptor:
                # _stop_dns_interceptor() already calls stop() which handles cleanup
                # Just ensure the reference is cleared
                self.dns_interceptor = None
            
            # Stop access point with automatic connection restoration
            # WiFiManager will reconnect if we were connected before entering AP mode
            try:
                self.wifi_manager.stop_access_point(restore_connection=True)
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
    
