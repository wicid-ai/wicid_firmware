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

# Check if secrets.py exists and is valid
def check_secrets():
    try:
        import secrets
        required_keys = ['ssid', 'password', 'weather_zip', 'weather_timezone']
        if not all(key in secrets.secrets for key in required_keys):
            return False
        return True
    except (ImportError, AttributeError):
        return False

# Initialize hardware
pixel_controller = PixelController()  # Singleton handles NeoPixel initialization
button = digitalio.DigitalInOut(board.BUTTON)
button.switch_to_input(pull=digitalio.Pull.UP)

# Check if we should enter setup mode (button pressed on boot or no valid config)
enter_setup = False
if not button.value:  # Button is pressed
    print("Button pressed on boot, entering setup mode...")
    enter_setup = True
elif not check_secrets():
    print("No valid configuration found, entering setup mode...")
    enter_setup = True

if enter_setup:
    import modes
    modes.run_setup_mode(button)
    # If we get here, setup is complete or was cancelled
    supervisor.reload()  # Reboot to apply new settings

# If we get here, we have valid settings
import secrets
from weather import Weather
import modes

def main():
    try:
        # Initialize weather service
        weather = Weather()

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

        # Check for setup mode button press (hold for 3 seconds)
        def check_setup_button():
            if not button.value:  # Button is pressed
                start_time = time.monotonic()
                while not button.value:
                    if time.monotonic() - start_time >= 3:  # 3 second hold
                        return True
                    time.sleep(0.1)
            return False

        while True:
            # Check for setup mode button press
            if check_setup_button():
                print("Setup mode requested via button press")
                if modes.run_setup_mode(button):
                    # If setup was successful, reboot to apply new settings
                    supervisor.reload()
                else:
                    # If setup was cancelled, continue with normal operation
                    time.sleep(1)  # Debounce
                    continue

            # Call the selected mode function (runs until user presses button)
            current_mode = modes_list[mode_index]
            try:
                if current_mode == modes.run_current_weather_mode:
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

            # Once the mode function returns, we move on to the next
            mode_index = (mode_index + 1) % len(modes_list)

            # Brief delay so we don't bounce immediately into next mode
            time.sleep(0.1)

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


