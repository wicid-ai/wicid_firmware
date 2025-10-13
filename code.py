import time
import board
import digitalio
import os
import json
import storage
import supervisor
import wifi
import socketpool
import ssl
from pixel_controller import PixelController
from utils import check_secrets_complete, trigger_safe_mode, check_button_hold_duration

# Initialize hardware
pixel_controller = PixelController()  # Singleton handles NeoPixel initialization
button = digitalio.DigitalInOut(board.BUTTON)
button.switch_to_input(pull=digitalio.Pull.UP)

# Check if we should enter setup mode (button pressed on boot or no valid config)
enter_setup = False
is_complete, missing_keys = check_secrets_complete()

if not button.value:  # Button is pressed
    print("Button pressed on boot, entering setup mode...")
    enter_setup = True
elif not is_complete:
    print(f"Configuration incomplete (missing: {missing_keys}), entering setup mode...")
    enter_setup = True

if enter_setup:
    import modes
    modes.run_setup_mode(button)
    # If we get here, setup is complete or was cancelled
    supervisor.reload()  # Reboot to apply new settings

# If we get here, we have valid settings
import secrets
from weather import Weather
from wifi_manager import WiFiManager
from utils import check_button_held
import modes

def main():
    try:
        # Initialize WiFi Manager and connect with interruptible backoff
        from wifi_manager import AuthenticationError
        wifi_manager = WiFiManager(button)
        
        try:
            success, error_msg = wifi_manager.connect_with_backoff(
                secrets.secrets["ssid"],
                secrets.secrets["password"]
            )
            if not success:
                # If connection fails after retries, enter setup mode to fix
                print(f"Could not connect to WiFi: {error_msg}")
                print("Entering setup mode...")
                pixel_controller.blink_error()
                time.sleep(2)
                wifi_error = {
                    "message": error_msg,
                    "field": "ssid"
                }
                if modes.run_setup_mode(button, error=wifi_error):
                    # Setup completed, reboot to apply new settings
                    supervisor.reload()
                else:
                    # Setup cancelled, reboot to retry
                    print("Setup cancelled. Rebooting to retry...")
                    time.sleep(2)
                    supervisor.reload()
            # Connection successful - continue to full validation before indicating success
        
        except AuthenticationError as e:
            # Invalid credentials - enter setup mode to fix them
            print(f"Authentication failed: {e}")
            print("Entering setup mode to update credentials...")
            pixel_controller.blink_error()
            time.sleep(2)
            auth_error = {
                "message": "WiFi authentication failure. Please check your password.",
                "field": "password"
            }
            if modes.run_setup_mode(button, error=auth_error):
                # Setup completed, reboot to apply new settings
                supervisor.reload()
            else:
                # Setup cancelled, reboot anyway since credentials are invalid
                print("Setup cancelled but credentials are invalid. Rebooting...")
                time.sleep(2)
                supervisor.reload()
                
        except KeyboardInterrupt:
            # User pressed button during connection attempts
            print("Connection attempt interrupted by button press.")
            
            # Check button hold duration: 10s = Safe Mode, 3s = Setup mode, short = skip WiFi
            hold_result = check_button_hold_duration(button, pixel_controller)
            
            if hold_result == 'safe_mode':
                print("Safe Mode requested (10 second hold)")
                trigger_safe_mode()
                # This will reboot, so we never reach here
            elif hold_result == 'setup':
                print("Setup mode requested during WiFi connection")
                if modes.run_setup_mode(button):
                    # Setup completed, reboot to apply new settings
                    supervisor.reload()
                else:
                    # Setup cancelled, reboot to retry connection
                    print("Setup cancelled. Rebooting to retry connection...")
                    time.sleep(1)
                    supervisor.reload()
            else:  # 'short'
                # Short press - user wants to skip WiFi for now
                # Continue to main loop without WiFi (only demo modes will work)
                print("Skipping WiFi connection. Only demo modes available.")
                pixel_controller.set_color((255, 165, 0))  # Orange to indicate no WiFi
                time.sleep(2)
                wifi_manager = None  # Signal that WiFi is not available

        # Initialize weather service with an active session (if WiFi connected)
        weather = None
        if wifi_manager and wifi_manager.is_connected():
            try:
                weather = Weather(wifi_manager.create_session())
                
                # Check if ZIP code validation failed
                if weather.lat is None or weather.lon is None:
                    print("✗ ZIP code validation failed")
                    print("Entering setup mode to update ZIP code...")
                    pixel_controller.blink_error()
                    time.sleep(2)
                    zip_error = {
                        "message": "Could not find location data for ZIP code. Please verify and try again.",
                        "field": "zip_code"
                    }
                    if modes.run_setup_mode(button, error=zip_error):
                        # Setup completed, reboot to apply new settings
                        supervisor.reload()
                    else:
                        # Setup cancelled, continue without weather
                        print("Setup cancelled. Continuing without weather service.")
                        weather = None
                else:
                    # All checks passed - WiFi connected and ZIP validated
                    print("✓ Boot successful - all checks passed")
                    pixel_controller.blink_success()
            except Exception as e:
                print(f"Error initializing weather service: {e}")
                print("Continuing without weather service")
                weather = None
        else:
            print("Weather service unavailable (no WiFi connection)")

        # Define available modes
        modes_list = [
            modes.run_current_weather_mode,
            modes.run_temp_demo_mode,
            modes.run_precip_demo_mode
        ]
        mode_index = 0

        # Get update interval with a default of 20 minutes if not set
        try:
            UPDATE_INTERVAL = secrets.secrets.get("update_interval", 1200)
        except (AttributeError, KeyError):
            UPDATE_INTERVAL = 1200  # Default to 20 minutes


        while True:
            # Call the selected mode function (runs until user presses button)
            current_mode = modes_list[mode_index]
            try:
                if current_mode == modes.run_current_weather_mode:
                    # Skip weather mode if no WiFi available
                    if weather is None:
                        print("Skipping weather mode (no WiFi connection)")
                        mode_index = (mode_index + 1) % len(modes_list)
                        time.sleep(0.5)
                        continue
                    current_mode(button, weather, UPDATE_INTERVAL)
                else:
                    current_mode(button)
            except Exception as e:
                print(f"Error in {current_mode.__name__}: {e}")
                # Blink red to indicate error
                pixel_controller.blink_error()
                # Move to next mode on error
                mode_index = (mode_index + 1) % len(modes_list)
                continue

            # Mode exited due to button press - check button hold duration
            # 10+ seconds = Safe Mode (for development)
            # 3+ seconds = Setup mode
            # Short press = next mode
            
            hold_result = check_button_hold_duration(button, pixel_controller)
            
            if hold_result == 'safe_mode':
                print("Safe Mode requested (10 second hold)")
                trigger_safe_mode()
                # This will reboot, so we never reach here
            elif hold_result == 'setup':
                print("Setup mode requested via button hold")
                if modes.run_setup_mode(button):
                    # If setup was successful, reboot to apply new settings
                    supervisor.reload()
                else:
                    # If setup was cancelled, continue with normal operation
                    time.sleep(0.5)  # Debounce
                    continue
            else:  # 'short'
                # Short press: move to next mode
                mode_index = (mode_index + 1) % len(modes_list)

            # Brief delay so we don't bounce immediately into next mode
            time.sleep(0.2)

    except Exception as e:
        print("Fatal error in main loop:", e)
        # Blink red rapidly to indicate fatal error
        while True:
            pixel_controller.set_color((255, 0, 0))
            time.sleep(0.25)
            pixel_controller.set_color((0, 0, 0))
            time.sleep(0.25)

if __name__ == "__main__":
    main()


