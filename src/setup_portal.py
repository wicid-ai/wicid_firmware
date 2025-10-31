import os
import json
import time
import supervisor
from adafruit_httpserver import Response, Request, JSONResponse
from pixel_controller import PixelController
from utils import check_button_hold_duration, trigger_safe_mode
from dns_interceptor import DNSInterceptor
from wifi_manager import WiFiManager

class SetupPortal:
    # Delay after pre-check success to ensure response is transmitted before reboot (seconds)
    PRECHECK_DELAY_SECONDS = 2
    # --- Centralized error strings ---
    ERR_INVALID_REQUEST = "Invalid request data."
    ERR_EMPTY_SSID = "SSID cannot be empty."
    ERR_PWD_LEN = "Password must be 8-63 characters."
    ERR_SCAN_FAIL = "Could not scan for networks. Please try again."
    ERR_INVALID_ZIP = "ZIP code must be 5 digits."

    def __init__(self, button):
        self.ap_ssid = "WICID-Setup"
        self.ap_password = None  # Open network
        self.setup_complete = False
        self.pixel = PixelController()  # Get singleton instance
        self.wifi_manager = WiFiManager.get_instance(button)  # Get WiFiManager singleton
        self.button = button
        self.last_connection_error = None
        self.pending_ready_at = None  # monotonic timestamp for scheduled reboot
        self.dns_interceptor = None  # DNS interceptor for captive portal
        self.last_request_time = None  # timestamp of last HTTP request for idle timeout tracking
        self.user_connected = False  # flag indicating user has connected to portal

    def start_setup_indicator(self):
        """Begin pulsing white to indicate setup mode is active."""
        self.pixel.start_setup_mode_pulsing()

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
                print(f"DNS interceptor started - all domains redirect to {ap_ip}")
                return True
            else:
                print("DNS interceptor failed to start - using HTTP-only detection")
                self.dns_interceptor = None
                return False
                
        except Exception as e:
            print(f"Error starting DNS interceptor: {e}")
            print("Using HTTP-only detection")
            
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
                print(f"Error stopping DNS interceptor: {e}")
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
            print("Captive portal mode: DNS + HTTP detection")
        else:
            print("Captive portal mode: HTTP-only detection")
        
        # Ensure pulsing is active (already started in run_setup_mode, but verify state)
        if self.pixel._mode != PixelController.MODE_PULSING:
            self.start_setup_indicator()
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
        print(msg)

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
            self._log(f"DEBUG: Password length check crashed: {e}")
            raise
        
        # Validate ZIP code format (5 digits)
        if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
            return self._json_error(request, self.ERR_INVALID_ZIP, field="zip_code")
        
        return None

    def _scan_ssids(self):
        """Scan for WiFi networks and return a list of available SSIDs.
        Uses WiFiManager for scanning (ensures scanning is stopped).
        """
        self._log("DEBUG: Starting network scan for SSID validation")
        try:
            ssids = [net.ssid for net in self.wifi_manager.scan_networks() if getattr(net, 'ssid', None)]
            self._log(f"DEBUG: Found SSIDs: {ssids}")
            return ssids
        except Exception as e:
            self._log(f"DEBUG: Network scan error: {e}")
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
            
            print("Credentials saved successfully to secrets.json")
            return True, None
            
        except Exception as e:
            print(f"Error saving credentials: {e}")
            return False, str(e)

    def blink_success(self):
        """Blink green to indicate success"""
        try:
            self.pixel.blink_success()
        except Exception as e:
            print(f"Error in blink_success: {e}")

    def run_web_server(self):
        """Run a simple web server to handle the setup interface"""
        from adafruit_httpserver import Server, Request, Response, FileResponse
        from wifi_retry_state import clear_retry_count
        
        pool = self.wifi_manager.get_socket_pool()
        server = Server(pool, "/www", debug=False)
        
        # Initialize idle timeout tracking
        self.last_request_time = time.monotonic()
        setup_idle_timeout = int(os.getenv("SETUP_IDLE_TIMEOUT", "300"))
        
        # Helper to mark user as connected and clear retry state
        def _mark_user_connected():
            if not self.user_connected:
                self.user_connected = True
                clear_retry_count()
                print("User connected to portal - retry counter cleared")
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
                print(f"Error serving index page: {e}")
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
                print(f"Error getting system info: {e}")
                return self._json_error(request, "Could not retrieve system information.", code=500, text="Internal Server Error")
        
        # WiFi network scanning endpoint
        @server.route("/scan", "GET")
        def scan_networks(request: Request):
            _mark_user_connected()
            try:
                print("Scanning for WiFi networks...")
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
                
                print(f"Found {len(networks)} networks")
                return self._json_ok(request, {"networks": networks})
                
            except Exception as e:
                print(f"Error scanning networks: {e}")
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
                self._log("DEBUG: Starting configure function")
                data = request.json()
                self._log(f"DEBUG: JSON parsed successfully, type: {type(data)}")
                
                # Validate that JSON parsing returned a dictionary
                if not isinstance(data, dict):
                    self._log(f"JSON parsing failed, got: {type(data)} = {data}")
                    return self._json_error(request, self.ERR_INVALID_REQUEST)
                
                self._log("DEBUG: Extracting form data")
                ssid = data.get('ssid', '').strip()
                password = data.get('password', '')
                zip_code = data.get('zip_code', '')
                self._log(f"DEBUG: Extracted - SSID: '{ssid}', password length: {len(password)}")

                # --- Stage 1: Pre-flight Checks (AP remains active) ---
                self._log("Stage 1: Performing pre-flight checks...")

                self._log(f"DEBUG: About to check password length. Password type: {type(password)}, value: {repr(password)}")
                resp = self._validate_config_input(request, ssid, password, zip_code)
                if resp:
                    return resp
                self._log("DEBUG: Input validation passed")

                # Check if SSID is a real, scanned network
                try:
                    available_ssids = self._scan_ssids()
                except Exception as scan_e:
                    self._log(f"SSID validation scan failed: {scan_e}")
                    return self._json_error(request, self.ERR_SCAN_FAIL, field="ssid", code=500, text="Internal Server Error")

                if ssid not in available_ssids:
                    return self._json_error(request, self._net_not_found_message(ssid), field="ssid")

                # Pre-checks passed - save credentials and schedule reboot
                self._log("✓ Pre-flight checks passed. Saving credentials...")
                save_ok, save_err = self.save_credentials(ssid, password, zip_code)
                if not save_ok:
                    self._log(f"✗ Failed to save credentials: {save_err}")
                    return self._json_error(request, f"Could not save settings: {save_err}", code=500, text="Internal Server Error")
                
                self._log("✓ Credentials saved. Scheduling reboot...")
                # Schedule reboot to allow client to receive response and show success
                self.pending_ready_at = time.monotonic() + self.PRECHECK_DELAY_SECONDS
                return self._json_ok(request, {"status": "precheck_success"})

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
        
        
        # Start the server
        server_ip = self.wifi_manager.get_ap_ip_address()
        server.start(host=server_ip, port=80)
        print(f"Server started at http://{server_ip}")

        # Wait for initial button release (from the press that got us into setup)
        while not self.button.value:
            self.pixel.tick()  # Keep pulsing animation active
            time.sleep(0.1)
        
        # Small debounce delay - keep pulsing during delay
        debounce_end = time.monotonic() + 0.5
        while time.monotonic() < debounce_end:
            self.pixel.tick()
            time.sleep(0.05)
        
        print("Starting main server loop")
        print("Visit: http://192.168.4.1/ while connected to WICID-Setup")
        
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
                        print(f"DNS interceptor error: {dns_e}")
                        self._stop_dns_interceptor()
                
                # Update LED pulsing via controller
                self.pixel.tick()

                # Check for idle timeout (no user interaction)
                if self.last_request_time is not None:
                    idle_time = time.monotonic() - self.last_request_time
                    if idle_time >= setup_idle_timeout:
                        print(f"Setup idle timeout exceeded ({idle_time:.0f}s). Rebooting to retry...")
                        # Comprehensive cleanup before rebooting
                        self._cleanup_setup_portal()
                        supervisor.reload()

                # If credentials were saved, wait for delay then reboot
                if self.pending_ready_at is not None and time.monotonic() >= self.pending_ready_at:
                    print("Setup complete. Rebooting to apply new settings...")
                    # Comprehensive cleanup before rebooting
                    self._cleanup_setup_portal()
                    # Don't flash success yet - validation happens on next boot
                    supervisor.reload()
                
                # Check for button press: 10s hold = Safe Mode, any other press = exit setup
                if not self.button.value:
                    hold_result = check_button_hold_duration(self.button, self.pixel)
                    
                    if hold_result == 'safe_mode':
                        print("Safe Mode requested (10 second hold)")
                        # Comprehensive cleanup before triggering safe mode
                        self._cleanup_setup_portal()
                        trigger_safe_mode()
                        # This will reboot, so we never reach here
                    else:
                        # Short press or 3-second hold: exit setup mode
                        print("Button pressed, exiting setup...")
                        # Comprehensive cleanup before exiting
                        cleanup_successful = self._cleanup_setup_portal()
                        
                        if not cleanup_successful:
                            print("⚠ Warning: Cleanup completed with issues")
                        
                        time.sleep(0.2)  # Small debounce
                        return False
                
                # Small sleep to prevent busy-waiting while maintaining smooth LED animation
                # 5ms is fast enough for smooth pulsing (tick interval is 40ms) while being CPU-friendly
                time.sleep(0.005)
                
            except Exception as e:
                print(f"Server error: {e}")
                time.sleep(1)
        
        # Comprehensive cleanup
        self._cleanup_setup_portal()
        server.stop()
        return self.setup_complete
    
    def _cleanup_setup_portal(self):
        """
        Cleanup of setup portal resources and state.
        
        Note: WiFi radio reset is handled by WiFiManager.reconnect() when caller
        reconnects to station mode, so we don't manage WiFi state here.
        
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
            
            # Stop LED pulsing
            try:
                self.pixel.stop_pulsing()
                self.pixel.off()
            except Exception as led_e:
                print(f"Error stopping LED: {led_e}")
            
            # Reset setup state
            self.setup_complete = False
            self.pending_ready_at = None
            self.last_connection_error = None
            
            return cleanup_successful
            
        except Exception as e:
            print(f"Error during cleanup: {e}")
            return False
    
