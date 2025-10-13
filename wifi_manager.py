"""
WiFi Manager - Centralized WiFi connection management with progressive backoff and interrupt support.

This module encapsulates all WiFi connection logic for the WICID device, including:
- Progressive exponential backoff retry logic
- Button interrupt support during connection attempts
- Connection state management
- Graceful error handling
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
    """Manages WiFi connections with progressive backoff and interrupt support."""
    
    # Maximum wait time between retries (4 hours)
    MAX_BACKOFF_TIME = 60 * 60 * 4
    # Base delay for exponential backoff (seconds)
    BASE_BACKOFF_DELAY = 1.5
    # Backoff multiplier for exponential retry delays
    BACKOFF_MULTIPLIER = 2
    # Connection timeout in seconds
    CONNECTION_TIMEOUT = 10
    
    def __init__(self, button=None):
        """
        Initialize the WiFi manager.
        
        Args:
            button: Optional button instance to check for interrupts during connection
        """
        self.button = button
        self.session = None
        self._connected = False
    
    def connect_with_backoff(self, ssid, password, on_retry=None):
        """
        Connect to WiFi with progressive exponential backoff retry logic.
        Can be interrupted by button press if button is provided.
        
        Hard failures (authentication errors) will not be retried.
        
        Args:
            ssid: WiFi network SSID
            password: WiFi network password
            on_retry: Optional callback function called on each retry attempt(attempt_num, wait_time)
        
        Returns:
            tuple: (success: bool, error_message: str or None)
        
        Raises:
            KeyboardInterrupt: If button is pressed during connection attempt
        """
        attempts = 0
        
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
            
            except RuntimeError as e:
                error_msg = str(e).lower()
                print(f"Connection attempt #{attempts} failed: RuntimeError - {e}")
                
                # Check for hard failures that should not be retried
                if "auth" in error_msg or "password" in error_msg:
                    print("✗ Authentication failure detected - triggering setup mode")
                    raise AuthenticationError(f"Invalid WiFi credentials: {str(e)}")
                
                # Soft failures can be retried
                result = self._handle_retry_or_fail(attempts, str(e), on_retry)
                if result:  # Max retries exceeded
                    return result
                # Continue loop for retry
            
            except ConnectionError as e:
                errno_code = getattr(e, 'errno', None)
                error_msg = str(e).lower()
                print(f"Connection attempt #{attempts} failed: ConnectionError - {e}")
                print(f"Error errno: {errno_code}")
                
                # Check for authentication failure by errno code or message content
                if errno_code in (-3, 7, 15, 202) or "auth" in error_msg or "password" in error_msg:
                    print("✗ Authentication failure detected - triggering setup mode")
                    raise AuthenticationError(f"Invalid WiFi credentials: {str(e)}")
                
                # Soft failures can be retried
                result = self._handle_retry_or_fail(attempts, str(e), on_retry)
                if result:  # Max retries exceeded
                    return result
                # Continue loop for retry
                
            except Exception as e:
                error_msg = str(e)
                print(f"Connection attempt #{attempts} failed: {error_msg}")
                result = self._handle_retry_or_fail(attempts, error_msg, on_retry)
                if result:  # Max retries exceeded
                    return result
                # Continue loop for retry
    
    def _handle_retry_or_fail(self, attempts, error_msg, on_retry=None):
        """
        Handle retry logic for soft failures.
        
        Returns:
            tuple: (False, error_message) if max retries exceeded
            None: if should continue retrying
        """
        # Calculate exponential backoff time: base * (2^(attempts-1))
        # Attempt 1: 1.5s, 2: 3s, 3: 6s, 4: 12s, 5: 24s, 6: 48s, 7: 96s...
        wait_time = self.BASE_BACKOFF_DELAY * (self.BACKOFF_MULTIPLIER ** (attempts - 1))
        
        # Check if we've exceeded max backoff time
        if wait_time >= self.MAX_BACKOFF_TIME:
            print(f"Max backoff time reached ({self.MAX_BACKOFF_TIME}s). Giving up.")
            return False, f"Connection failed after {attempts} attempts: {error_msg}"
        
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
