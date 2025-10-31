"""
WiFi Manager - Centralized WiFi connection management with progressive backoff and interrupt support.

This module encapsulates ALL WiFi operations for the WICID device, including:
- Station mode connection with progressive exponential backoff
- Access Point mode for setup portal
- Button interrupt support during connection attempts
- Connection state management
- WiFi radio lifecycle management
- Graceful error handling

WiFiManager is a singleton - use WiFiManager.get_instance() to access it.
"""

import wifi
import socketpool
import ssl
import time
from utils import is_button_pressed, interruptible_sleep


class AuthenticationError(Exception):
    """Raised when WiFi authentication fails due to invalid credentials."""
    pass


class WiFiManager:
    """
    Singleton manager for all WiFi operations.
    
    Encapsulates station mode, AP mode, and all WiFi radio state management.
    Use get_instance() to access the singleton instance.
    """
    
    _instance = None
    
    # Connection timeout for a single attempt (seconds)
    CONNECTION_TIMEOUT = 10
    
    # Exponential backoff configuration
    BASE_BACKOFF_DELAY = 1.5      # Initial delay (seconds): 1.5s
    BACKOFF_MULTIPLIER = 2         # Doubles each retry: 1.5s, 3s, 6s, 12s, 24s, 48s...
    MAX_BACKOFF_TIME = 60 * 30     # Cap at 30 minutes between retries
    
    @classmethod
    def get_instance(cls, button=None):
        """
        Get the singleton instance of WiFiManager.
        
        Args:
            button: Optional button instance (only used on first call)
        
        Returns:
            WiFiManager: The singleton instance
        """
        if cls._instance is None:
            # Create instance directly without going through __init__ check
            instance = object.__new__(cls)
            instance._init_singleton(button)
            cls._instance = instance
        return cls._instance
    
    def _init_singleton(self, button=None):
        """
        Internal initialization method for singleton.
        
        Args:
            button: Optional button instance to check for interrupts during connection
        """
        self.button = button
        self.session = None
        self._connected = False
        self._ap_active = False
    
    def __init__(self, button=None):
        """
        Direct instantiation is discouraged.
        Use get_instance() instead for singleton pattern.
        
        This is kept for backwards compatibility but will create independent instances.
        """
        self._init_singleton(button)
    
    def reset_radio_to_station_mode(self):
        """
        Reset WiFi radio to station mode, clearing any AP mode state.
        This ensures the radio is ready for client connections.
        
        Call this after exiting setup/AP mode to restore normal operation.
        """
        try:
            print("Resetting WiFi radio to station mode...")
            wifi.radio.enabled = False
            time.sleep(0.3)
            wifi.radio.enabled = True
            time.sleep(0.3)
            print("✓ WiFi radio reset complete")
        except Exception as e:
            print(f"Warning: Error resetting radio: {e}")
    
    def connect_with_backoff(self, ssid, password, timeout=None, on_retry=None):
        """
        Connect to WiFi with progressive exponential backoff retry logic.
        Can be interrupted by button press if button is provided.
        
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
                print(f"WiFi connection attempt #{attempts} to '{ssid}'...")
                
                # Check for button interrupt before attempting connection
                if self.button and is_button_pressed(self.button):
                    raise KeyboardInterrupt("Connection interrupted by button press")
                
                # Convert to bytes to satisfy buffer protocol requirement
                ssid_b = bytes(ssid, 'utf-8')
                password_b = bytes(password, 'utf-8')
                
                # Attempt connection
                wifi.radio.connect(ssid_b, password_b, timeout=self.CONNECTION_TIMEOUT)
                
                # Verify connection
                if wifi.radio.connected and wifi.radio.ipv4_address:
                    print(f"✓ WiFi connected successfully! IP: {wifi.radio.ipv4_address}")
                    self._connected = True
                    
                    # Create socket pool and session
                    pool = socketpool.SocketPool(wifi.radio)
                    self.session = None  # Will be created by caller if needed
                    
                    return True, None
                else:
                    print("✗ Connection failed - no IP address obtained")
                    raise ConnectionError("Failed to obtain IP address")
                    
            except KeyboardInterrupt:
                # Re-raise keyboard interrupt to allow caller to handle mode changes
                raise
            
            except TimeoutError as e:
                # Timeout indicates network unreachable, not authentication failure
                # Reset auth failure counter and retry with backoff
                auth_failure_count = 0
                print(f"Connection attempt #{attempts} timed out: {e}")
                result = self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry
            
            except RuntimeError as e:
                error_msg = str(e)
                print(f"Connection attempt #{attempts} failed: RuntimeError - {e}")
                
                # Check for explicit authentication failure message
                # Note: Can be transient even with valid credentials (router/radio states)
                if "authentication failure" in error_msg.lower():
                    auth_failure_count += 1
                    print(f"Authentication failure detected ({auth_failure_count}/3)")
                    
                    # Only raise after 3 consecutive auth failures to avoid false positives
                    # Total time: ~6-7 seconds with short backoff between attempts
                    if auth_failure_count >= 3:
                        print("Persistent authentication failure - credentials likely invalid")
                        raise AuthenticationError("WiFi authentication failure. Please check your password.")
                else:
                    # Reset counter on non-auth errors
                    auth_failure_count = 0
                
                # Network unreachable or other transient errors - retry with backoff
                result = self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry
            
            except ConnectionError as e:
                errno_code = getattr(e, 'errno', None)
                error_msg = str(e)
                print(f"Connection attempt #{attempts} failed: ConnectionError - {e}")
                print(f"Error errno: {errno_code}")
                
                # Check for explicit authentication failure message
                # Note: Can be transient even with valid credentials (router/radio states)
                if "authentication failure" in error_msg.lower():
                    auth_failure_count += 1
                    print(f"Authentication failure detected ({auth_failure_count}/3)")
                    
                    # Only raise after 3 consecutive auth failures to avoid false positives
                    # Intermittent auth failures can occur with valid credentials due to:
                    # - Router processing previous disconnect
                    # - WiFi radio initialization timing
                    # - Router rate limiting
                    # Total time to fail: ~6-7 seconds with short backoff between attempts
                    if auth_failure_count >= 3:
                        print("Persistent authentication failure - credentials likely invalid")
                        raise AuthenticationError("WiFi authentication failure. Please check your password.")
                else:
                    # Reset counter on non-auth errors
                    auth_failure_count = 0
                
                # Network unreachable or other transient errors - retry with backoff
                # "No network with that ssid" could be typo OR temporary outage - retry cycle handles both
                result = self._handle_retry_or_fail(attempts, str(e), start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry
            
            except AuthenticationError:
                # Re-raise authentication errors immediately (fail fast)
                raise
            
            except Exception as e:
                error_msg = str(e)
                print(f"Connection attempt #{attempts} failed: {error_msg}")
                
                # Reset auth failure counter for generic errors
                auth_failure_count = 0
                
                # Network unreachable or other transient errors - retry with backoff
                result = self._handle_retry_or_fail(attempts, error_msg, start_time, timeout, on_retry)
                if result:  # Timeout exceeded
                    return result
                # Continue loop for retry
    
    def _handle_retry_or_fail(self, attempts, error_msg, start_time, timeout=None, on_retry=None):
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
            print(f"Retry timeout exceeded ({elapsed_time:.1f}s). Giving up.")
            return False, f"Unable to connect to WiFi after {attempts} attempts over {elapsed_time:.1f} seconds."
        
        # Calculate exponential backoff time: base * (2^(attempts-1))
        # Attempt 1: 1.5s, 2: 3s, 3: 6s, 4: 12s, 5: 24s, 6: 48s, 7: 96s...
        wait_time = self.BASE_BACKOFF_DELAY * (self.BACKOFF_MULTIPLIER ** (attempts - 1))
        
        # Cap wait time at maximum backoff (30 minutes)
        if wait_time > self.MAX_BACKOFF_TIME:
            wait_time = self.MAX_BACKOFF_TIME
            print(f"Backoff capped at {self.MAX_BACKOFF_TIME}s ({self.MAX_BACKOFF_TIME/60:.0f} minutes)")
        
        # Call retry callback if provided
        if on_retry:
            on_retry(attempts, wait_time)
        
        print(f"Waiting {wait_time:.1f}s before retry...")
        
        # Wait with button interrupt checking
        if not interruptible_sleep(wait_time, self.button):
            raise KeyboardInterrupt("Connection interrupted by button press during backoff")
        
        # Return None to signal caller to continue retry loop
        return None
    
    def connect_once(self, ssid, password):
        """
        Attempt to connect to WiFi once without retry logic.
        
        Args:
            ssid: WiFi network SSID
            password: WiFi network password
        
        Returns:
            tuple: (success: bool, error_dict or None)
        """
        print(f"Testing connection to '{ssid}'...")
        
        # Convert to bytes to satisfy buffer protocol requirement
        ssid_b = bytes(ssid, 'utf-8')
        password_b = bytes(password, 'utf-8')
        
        # Attempt connection with explicit exception handling
        start_time = time.monotonic()
        connection_success = False
        error_result = None
        
        try:
            wifi.radio.connect(ssid_b, password_b, timeout=self.CONNECTION_TIMEOUT)
            elapsed = time.monotonic() - start_time
            print(f"Connection attempt completed in {elapsed:.1f}s")
            
            # Verify connection success
            if wifi.radio.connected and wifi.radio.ipv4_address:
                print(f"✓ Connected successfully! IP: {wifi.radio.ipv4_address}")
                self._connected = True
                connection_success = True
                return True, None
            else:
                # Connection method returned but no connection established
                print("✗ Connection failed - no IP address obtained")
                error_result = (False, {"message": "Failed to obtain IP address", "field": "ssid"})
        
        except TimeoutError as e:
            # Explicit timeout during connection
            elapsed = time.monotonic() - start_time
            print(f"Connection timed out after {elapsed:.1f}s: {e}")
            error_result = (False, {"message": "Connection timed out. Please check your password and network.", "field": "password"})
        
        except RuntimeError as e:
            # RuntimeError often indicates authentication or connection failures
            elapsed = time.monotonic() - start_time
            error_msg = str(e).lower()
            print(f"Connection failed after {elapsed:.1f}s: RuntimeError - {e}")
            print(f"Error type: RuntimeError, errno: {getattr(e, 'errno', 'N/A')}")
            
            # Check for authentication failure
            if "auth" in error_msg or "password" in error_msg:
                error_result = (False, {"message": "WiFi authentication failure. Please check your password.", "field": "password"})
            elif "no matching" in error_msg or "not found" in error_msg:
                error_result = (False, {"message": "WiFi network not found. Please check the network name.", "field": "ssid"})
            else:
                error_result = (False, {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"})
        
        except ConnectionError as e:
            # ConnectionError typically indicates network-level failures
            elapsed = time.monotonic() - start_time
            errno_code = getattr(e, 'errno', None)
            error_msg = str(e).lower()
            print(f"Connection failed after {elapsed:.1f}s: ConnectionError - {e}")
            print(f"Error type: ConnectionError, errno: {errno_code}")
            
            # Check for authentication failure by errno or message
            if errno_code in (-3, 7, 15, 202) or "auth" in error_msg or "password" in error_msg:
                error_result = (False, {"message": "WiFi authentication failure. Please check your password.", "field": "password"})
            elif "not found" in error_msg or "no matching" in error_msg:
                error_result = (False, {"message": "WiFi network not found. Please check the network name.", "field": "ssid"})
            else:
                error_result = (False, {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"})
        
        except OSError as e:
            # OSError can indicate various system-level connection problems
            elapsed = time.monotonic() - start_time
            errno_code = getattr(e, 'errno', None)
            print(f"Connection failed after {elapsed:.1f}s: OSError - {e}")
            print(f"Error type: OSError, errno: {errno_code}")
            error_result = (False, {"message": "WiFi connection error. Please try again.", "field": "ssid"})
        
        except Exception as e:
            # Catch-all for unexpected exceptions
            elapsed = time.monotonic() - start_time
            print(f"Connection failed after {elapsed:.1f}s: Unexpected {type(e).__name__} - {e}")
            print(f"Error type: {type(e).__name__}, errno: {getattr(e, 'errno', 'N/A')}")
            error_result = (False, {"message": "Unable to connect to WiFi. Please check your settings.", "field": "ssid"})
        
        finally:
            # Only reset radio if connection failed - ensures clean state for AP restart
            if not connection_success and error_result:
                try:
                    wifi.radio.enabled = False
                    time.sleep(0.1)
                    wifi.radio.enabled = True
                    print("WiFi radio reset after failed connection")
                except Exception as e:
                    print(f"Warning: Error resetting WiFi after failure: {e}")
        
        return error_result if error_result else (False, {"message": "Unknown connection failure", "field": "ssid"})
    
    def disconnect(self):
        """Disconnect from WiFi."""
        try:
            if wifi.radio.connected:
                wifi.radio.enabled = False
                wifi.radio.enabled = True
                self._connected = False
                print("WiFi disconnected")
        except Exception as e:
            print(f"Error disconnecting WiFi: {e}")
    
    def is_connected(self):
        """Check if currently connected to WiFi."""
        return self._connected and wifi.radio.connected
    
    def reconnect(self, ssid, password, timeout=None):
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
        print("Reconnecting to WiFi after setup mode exit...")
        
        # Reset radio to station mode (clears any AP mode state)
        self.reset_radio_to_station_mode()
        
        # Reset connection state
        self._connected = False
        self.session = None
        
        # Reconnect using standard backoff logic
        return self.connect_with_backoff(ssid, password, timeout)
    
    def create_session(self):
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
        pool = socketpool.SocketPool(wifi.radio)
        self.session = adafruit_requests.Session(pool, ssl.create_default_context())
        return self.session
    
    def get_mac_address(self):
        """
        Get the WiFi MAC address as a hex string.
        
        Returns:
            str: MAC address in format "aa:bb:cc:dd:ee:ff"
        """
        mac_binary = wifi.radio.mac_address
        return mac_binary.hex(':')
    
    def start_access_point(self, ssid, password=None):
        """
        Start WiFi access point for setup mode.
        Handles all necessary radio state transitions and configuration.
        
        Args:
            ssid: Access point SSID
            password: Optional password (None for open network)
        
        Returns:
            str: AP IP address
        
        Raises:
            RuntimeError: If AP fails to start
        """
        print("Starting access point...")
        
        # Disconnect from any existing WiFi connection before starting AP
        try:
            if wifi.radio.connected:
                print("Disconnecting from current network...")
                wifi.radio.stop_station()
                time.sleep(0.3)
        except Exception as e:
            print(f"Warning during disconnect: {e}")
        
        # Initialize/reset WiFi radio to ensure it's in a known good state
        try:
            wifi.radio.enabled = False
            time.sleep(0.2)
            wifi.radio.enabled = True
            time.sleep(0.2)
            print("WiFi radio initialized")
        except Exception as e:
            print(f"WiFi radio initialization warning: {e}")
        
        # Use bytes for SSID/password to satisfy older firmware buffer requirements
        ssid_b = bytes(ssid, "utf-8")
        pwd_b = bytes(password, "utf-8") if password else None
        
        try:
            # Configure AP IP address before starting
            try:
                import ipaddress
                wifi.radio.set_ipv4_address_ap(
                    ipv4=ipaddress.IPv4Address("192.168.4.1"),
                    netmask=ipaddress.IPv4Address("255.255.255.0"),
                    gateway=ipaddress.IPv4Address("192.168.4.1")
                )
                print("AP IP configured: 192.168.4.1")
            except Exception as ip_err:
                print(f"Could not set AP IP (will use default): {ip_err}")
            
            # Start the access point
            if pwd_b:
                wifi.radio.start_ap(ssid_b, pwd_b)
            else:
                # Open network; signature varies by version
                try:
                    wifi.radio.start_ap(ssid_b)
                except TypeError:
                    wifi.radio.start_ap(ssid_b, None)
        except Exception as e:
            print(f"start_ap failed: {e}")
            raise RuntimeError(f"Failed to start access point: {e}")
        
        print(f"AP Mode Active. Connect to: {ssid}")
        self._ap_active = True
        self._connected = False  # Not in station mode
        
        # Wait for AP IP address to be assigned
        ap_ip = None
        for attempt in range(10):
            ap_ip = wifi.radio.ipv4_address_ap
            if ap_ip:
                break
            time.sleep(0.1)
        
        if not ap_ip:
            ap_ip = "192.168.4.1"
        
        print(f"IP address: {ap_ip}")
        return str(ap_ip)
    
    def stop_access_point(self):
        """
        Stop access point and reset radio to station mode.
        Called when exiting setup mode.
        """
        if not self._ap_active:
            return
        
        print("Stopping access point...")
        self.reset_radio_to_station_mode()
        self._ap_active = False
        print("✓ Access point stopped")
    
    def is_ap_active(self):
        """Check if access point mode is currently active."""
        return self._ap_active
    
    def get_socket_pool(self):
        """
        Get a socket pool for the current WiFi radio.
        Used by DNS interceptor and other network services.
        
        Returns:
            socketpool.SocketPool instance
        """
        return socketpool.SocketPool(wifi.radio)
    
    def get_ap_ip_address(self):
        """
        Get the current access point IP address.
        
        Returns:
            str: AP IP address, or "192.168.4.1" if not available
        """
        ap_ip = wifi.radio.ipv4_address_ap
        return str(ap_ip) if ap_ip else "192.168.4.1"
    
    def scan_networks(self):
        """
        Scan for available WiFi networks.
        
        Yields:
            Network objects with ssid, rssi, channel, etc.
        """
        try:
            for network in wifi.radio.start_scanning_networks():
                yield network
        finally:
            try:
                wifi.radio.stop_scanning_networks()
            except Exception as e:
                print(f"Warning: Error stopping network scan: {e}")
    
    def validate_ssid_exists(self, ssid):
        """
        Check if a given SSID exists in the available networks.
        
        Args:
            ssid: SSID to validate
        
        Returns:
            bool: True if SSID found in scan results
        """
        try:
            scan_results = wifi.radio.start_scanning_networks()
            
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
            print(f"Error during SSID validation scan: {e}")
            return False
        finally:
            try:
                wifi.radio.stop_scanning_networks()
            except Exception as e:
                print(f"Warning: Error stopping scan: {e}")
