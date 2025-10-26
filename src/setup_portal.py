import os
import wifi
import socketpool
import adafruit_requests
import json
import time
import storage
import board
import digitalio
import supervisor
from adafruit_httpserver import Response, Request, JSONResponse
from pixel_controller import PixelController
from utils import check_button_hold_duration, trigger_safe_mode

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
        self.button = button
        self.last_connection_error = None
        self.pending_ready_at = None  # monotonic timestamp for scheduled reboot

    def start_setup_indicator(self):
        """Begin pulsing white to indicate setup mode is active."""
        self.pixel.start_pulsing(
            color=(255, 255, 255),
            min_b=0.1,
            max_b=0.7,
            step=0.03,
            interval=0.04,
            start_brightness=0.4,
        )

    def start_access_point(self):
        """Start the access point for setup mode"""
        print("Starting access point...")
        # Use bytes for SSID/password to satisfy older firmware buffer requirements
        ssid_b = bytes(self.ap_ssid, "utf-8")
        pwd_b = bytes(self.ap_password, "utf-8") if self.ap_password else None
        try:
            if pwd_b:
                wifi.radio.start_ap(ssid_b, pwd_b)
            else:
                # Open network; signature varies by version
                try:
                    wifi.radio.start_ap(ssid_b)  # preferred if supported
                except TypeError:
                    wifi.radio.start_ap(ssid_b, None)  # fallback for older signatures
        except Exception as e:
            print(f"start_ap failed: {e}")
            raise
        print(f"AP Mode Active. Connect to: {self.ap_ssid}")
        print(f"IP address: {wifi.radio.ipv4_address_ap}")
        print(f"Gateway: {wifi.radio.ipv4_gateway_ap}")
        print(f"Subnet: {wifi.radio.ipv4_subnet_ap}")
        
        # Begin pulsing white to indicate setup mode - more pronounced with wider range
        self.start_setup_indicator()

    def pulse_white(self, brightness=1.0):
        """Compatibility helper; keep method but delegate to PixelController."""
        try:
            self.pixel.set_color((int(255*brightness), int(255*brightness), int(255*brightness)))
            return True
        except Exception as e:
            print(f"Error in pulse_white: {e}")

    def check_setup_button(self):
        """Check if setup button is pressed"""
        return not self.button.value

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
        Ensures scanning is stopped. Raises on failure.
        """
        self._log("DEBUG: Starting network scan for SSID validation")
        try:
            scan_results = wifi.radio.start_scanning_networks()
            self._log(f"DEBUG: Scan results type: {type(scan_results)}")
            if isinstance(scan_results, int):
                raise RuntimeError(f"Scan failed with error code {scan_results}")
            ssids = [net.ssid for net in scan_results if getattr(net, 'ssid', None)]
            self._log(f"DEBUG: Found SSIDs: {ssids}")
            return ssids
        finally:
            # Always stop scanning
            try:
                wifi.radio.stop_scanning_networks()
            except Exception as e:
                self._log(f"DEBUG: stop_scanning_networks failed: {e}")

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
        
        pool = socketpool.SocketPool(wifi.radio)
        server = Server(pool, "/www", debug=False)
        
        # Serve the main page, pre-populating with settings and showing previous errors
        @server.route("/")
        def base(request: Request):
            try:
                current_settings = {
                    'ssid': '', 'password': '', 'zip_code': ''
                }
                try:
                    # Load from secrets.json to pre-populate the form
                    with open("/secrets.json", "r") as f:
                        secrets = json.load(f)
                    
                    current_settings['ssid'] = secrets.get('ssid', '')
                    current_settings['password'] = secrets.get('password', '')
                    current_settings['zip_code'] = secrets.get('weather_zip', '')
                except Exception as load_err:
                    print(f"Could not load existing secrets: {load_err}")
                    # Use empty values if secrets can't be loaded
                    pass

                # Package all data for the frontend
                page_data = {
                    'settings': current_settings,
                    'error': self.last_connection_error
                }
                # Clear the error after displaying once
                self.last_connection_error = None

                # Inject the data into the HTML
                with open('/www/index.html', 'r') as f:
                    html = f.read()
                
                data_script = f'<script>window.WICID_PAGE_DATA = {json.dumps(page_data)};</script>'
                html = html.replace('</head>', f'{data_script}</head>')
                
                return Response(request, html, content_type='text/html')

            except Exception as e:
                print(f"Error serving index page: {e}")
                # Fallback to serving the static file if injection fails
                return FileResponse(request, "index.html", "/www")
        
        # System information endpoint
        @server.route("/system-info", "GET")
        def system_info(request: Request):
            try:
                from utils import get_machine_type, get_os_version_string
                
                # Get basic system info
                machine_type = get_machine_type()
                os_version_string = get_os_version_string()
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
                
                # Format OS version for display (use basic string operations for CircuitPython compatibility)
                os_display = os_version_string.replace("_", " ")
                
                # Load installation timestamp if available
                last_update = None
                try:
                    with open("/install_timestamp.json", "r") as f:
                        install_data = json.load(f)
                    timestamp = install_data.get("timestamp")
                    if timestamp:
                        # Convert Unix timestamp to ISO 8601 format
                        # CircuitPython doesn't have datetime, so format manually
                        last_update = timestamp
                except Exception:
                    pass
                
                return self._json_ok(request, {
                    "machine_type": machine_type,
                    "os_version": os_display,
                    "wicid_version": wicid_version,
                    "last_update": last_update
                })
                
            except Exception as e:
                print(f"Error getting system info: {e}")
                return self._json_error(request, "Could not retrieve system information.", code=500, text="Internal Server Error")
        
        # WiFi network scanning endpoint
        @server.route("/scan", "GET")
        def scan_networks(request: Request):
            try:
                print("Scanning for WiFi networks...")
                networks = []
                
                # Scan for available networks
                for network in wifi.radio.start_scanning_networks():
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
                
                wifi.radio.stop_scanning_networks()
                
                # Sort by signal strength (RSSI, higher is better)
                networks.sort(key=lambda x: x['rssi'], reverse=True)
                
                print(f"Found {len(networks)} networks")
                return self._json_ok(request, {"networks": networks})
                
            except Exception as e:
                print(f"Error scanning networks: {e}")
                wifi.radio.stop_scanning_networks()  # Ensure scanning is stopped
                return self._json_error(request, "Could not scan for networks. Please try again.", code=500, text="Internal Server Error")

        # Handle form submission with two-stage validation
        @server.route("/configure", "POST")
        def configure(request: Request):
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
        
        
        # Start the server
        server.start(host=str(wifi.radio.ipv4_address_ap), port=80)
        print(f"Server started at http://{wifi.radio.ipv4_address_ap}")

        # Wait for initial button release (from the press that got us into setup)
        while not self.button.value:
            time.sleep(0.1)
        
        # Small debounce delay
        time.sleep(0.5)
        
        print("Starting main server loop")
        print("Visit: http://192.168.4.1/ while connected to WICID-Setup")
        
        # Main server loop - listen for button press to exit
        while not self.setup_complete:
            try:
                server.poll()
                
                # Update LED pulsing via controller
                self.pixel.tick()

                # If credentials were saved, wait for delay then reboot
                if self.pending_ready_at is not None and time.monotonic() >= self.pending_ready_at:
                    print("Setup complete. Rebooting to apply new settings...")
                    # Don't flash success yet - validation happens on next boot
                    supervisor.reload()
                
                # Check for button press: 10s hold = Safe Mode, any other press = exit setup
                if not self.button.value:
                    hold_result = check_button_hold_duration(self.button, self.pixel)
                    
                    if hold_result == 'safe_mode':
                        print("Safe Mode requested (10 second hold)")
                        trigger_safe_mode()
                        # This will reboot, so we never reach here
                    else:
                        # Short press or 3-second hold: exit setup mode
                        print("Button pressed, exiting setup...")
                        time.sleep(0.2)  # Small debounce
                        return False
                
                time.sleep(0.01)  # Shorter sleep for more responsive button
                
            except Exception as e:
                print(f"Server error: {e}")
                time.sleep(1)
        
        # Cleanup
        server.stop()
        return self.setup_complete
