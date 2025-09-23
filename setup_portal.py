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
from pixel_controller import PixelController

class SetupPortal:
    def __init__(self, button):
        self.ap_ssid = "WICID-Setup"
        self.ap_password = None  # Open network
        self.setup_complete = False
        self.pixel = PixelController()  # Get singleton instance
        self.button = button

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
        self.pixel.start_pulsing(color=(255, 255, 255), min_b=0.1, max_b=0.7, step=0.03, interval=0.04, start_brightness=0.4)

    def pulse_white(self, brightness=1.0):
        """Compatibility helper; keep method but delegate to PixelController."""
        try:
            self.pixel.set_color((int(255*brightness), int(255*brightness), int(255*brightness)))
            return True
        except Exception as e:
            print(f"Error in pulse_white: {e}")
            return False

    def check_setup_button(self):
        """Check if setup button is pressed"""
        return not self.button.value

    def save_credentials(self, ssid, password, zip_code, timezone):
        """Save WiFi credentials and settings to secrets.py"""
        secrets_content = f'''# This file is where you keep secret settings, passwords, and tokens!
# If you put them in the code you risk committing that info or sharing it

secrets = {{
    'ssid' : '{ssid}',
    'password' : '{password}',
    'weather_zip': '{zip_code}',
    'weather_timezone': '{timezone}',
    'update_interval': 1200  # Default update interval in seconds (20 minutes)
}}
'''
        try:
            # If USB is connected, CircuitPython volume is mounted read-only from the device perspective
            if getattr(supervisor.runtime, "usb_connected", False):
                print("USB is connected; cannot write settings while mounted over USB.")
                return False, "USB_CONNECTED"
            # Remount FS as writable
            try:
                storage.remount("/", False)
            except Exception as e:
                print(f"remount RW failed or not needed: {e}")
            with open("/secrets.py", "w") as f:
                f.write(secrets_content)
            # Flush and remount as read-only for safety
            try:
                storage.remount("/", True)
            except Exception as e:
                print(f"remount RO failed: {e}")
            print("Credentials saved successfully")
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
        
        # Serve the main page with current settings
        @server.route("/")
        def base(request: Request):
            try:
                import secrets
                current_settings = {
                    'ssid': secrets.secrets.get('ssid', ''),
                    'zip_code': secrets.secrets.get('weather_zip', '02138'),
                    'timezone': secrets.secrets.get('weather_timezone', 'America/New_York')
                }
                # We'll inject these settings into the HTML
                with open('/www/index.html') as f:
                    html = f.read()
                settings_script = f'<script>window.currentSettings = {json.dumps(current_settings)};</script>'
                html = html.replace('</head>', f'{settings_script}</head>')
                return Response(request, html, content_type='text/html')
            except Exception as e:
                print(f"Error serving index: {e}")
                return FileResponse(request, "index.html", "/www")
        
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
                return Response(
                    request,
                    json.dumps({"networks": networks}),
                    content_type='application/json'
                )
                
            except Exception as e:
                print(f"Error scanning networks: {e}")
                wifi.radio.stop_scanning_networks()  # Ensure scanning is stopped
                return Response(
                    request,
                    json.dumps({"networks": [], "error": str(e)}),
                    content_type='application/json',
                    status=500
                )

        # Handle form submission
        @server.route("/configure", "POST")
        def configure(request: Request):
            try:
                # Parse JSON data
                data = request.json()
                if not data:
                    return Response(
                        request,
                        json.dumps({"status": "error", "message": "No data provided"}),
                        content_type='application/json',
                        status=400
                    )
                
                # Save credentials
                ok, err = self.save_credentials(
                    data.get('ssid', ''),
                    data.get('password', ''),
                    data.get('zip_code', '02138'),
                    data.get('timezone', 'America/New_York')
                )
                if ok:
                    self.setup_complete = True
                    return Response(
                        request,
                        json.dumps({"status": "success"}),
                        content_type='application/json'
                    )
                
                # Provide a specific error if USB is connected
                message = "Failed to save settings"
                if err == "USB_CONNECTED":
                    message = "Device is connected over USB in read-only mode. Unplug USB or eject CIRCUITPY, then retry."
                return Response(
                    request,
                    json.dumps({"status": "error", "message": message}),
                    content_type='application/json',
                    status=400
                )
                
            except Exception as e:
                print(f"Error in configure: {e}")
                return Response(
                    request,
                    json.dumps({"status": "error", "message": str(e)}),
                    content_type='application/json',
                    status=500
                )
        
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
                
                # Check for any button press to exit
                if not self.button.value:
                    print("Button pressed, exiting setup...")
                    # Wait for button release before exiting
                    while not self.button.value:
                        time.sleep(0.1)
                    time.sleep(0.2)  # Small debounce
                    return False
                
                time.sleep(0.01)  # Shorter sleep for more responsive button
                
            except Exception as e:
                print(f"Server error: {e}")
                time.sleep(1)
        
        # Cleanup
        server.stop()
        return self.setup_complete
