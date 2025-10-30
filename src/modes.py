import time
import board
import digitalio
import wifi
import socketpool
import ssl
import adafruit_requests
import json
import storage
import os
from pixel_controller import PixelController

def temperature_color(temp_f):
    """
    Returns an (R, G, B) color biased toward warmer hues,
    clamped between 0°F and 100°F (white->purple->blue->green->yellow->orange->red).
    """
    color_steps = [
        (0,   (55, 55, 55)),   # really cold: white
        (15,  (54,   1,   63)),   # cold: purple
        (35,  (0,    0,   220)),  # cool: blue
        (50,  (0,    100, 220)),  # lighter blue
        (60,  (0,    160, 100)),  # teal
        (70,  (10,   220,  10)),  # greenish
        (80,  (255,  135,  0)),   # yellow
        (90,  (255,  60,   0)),   # orange
        (100, (235,  0,    0)),   # red
    ]

    if temp_f is None:
        return (128, 128, 128)  # neutral gray if unknown

    if temp_f <= color_steps[0][0]:
        return color_steps[0][1]
    if temp_f >= color_steps[-1][0]:
        return color_steps[-1][1]

    for i in range(len(color_steps) - 1):
        lower_temp, lower_color = color_steps[i]
        upper_temp, upper_color = color_steps[i + 1]
        if lower_temp <= temp_f <= upper_temp:
            span = upper_temp - lower_temp
            ratio = (temp_f - lower_temp) / span
            r = int(lower_color[0] + ratio * (upper_color[0] - lower_color[0]))
            g = int(lower_color[1] + ratio * (upper_color[1] - lower_color[1]))
            b = int(lower_color[2] + ratio * (upper_color[2] - lower_color[2]))
            return (r, g, b)

    return color_steps[-1][1]

def blink_for_precip(pixel_controller, color, precip_percent, button=None):
    """
    Blinks the NeoPixel according to the 'rounded to nearest 10%' precipitation probability.
      - Example: 27% => 30% => 3 blinks, then hold color for a few seconds.
      - If a button is provided, check it inside the blink to exit mid-cycle.
    """
    fast_blink_on = 0.3
    fast_blink_off = 0.2
    post_blink_pause = 3.0

    if precip_percent is None:
        # No data: just hold color for a short time
        pixel_controller.set_color(color)
        for _ in range(int(1 / 0.05)):  # ~1 second, checking button
            if button and not button.value:
                return False
            time.sleep(0.05)
        return True

    blink_count = round(precip_percent / 10.0)
    if blink_count > 10:
        blink_count = 10
    if blink_count < 0:
        blink_count = 0

    for _ in range(blink_count):
        pixel_controller.set_color(color)
        # Break the on/off into small increments, so we can detect button press
        for _ in range(int(fast_blink_on / 0.05)):
            if button and not button.value:
                return False
            time.sleep(0.05)

        pixel_controller.off()
        for _ in range(int(fast_blink_off / 0.05)):
            if button and not button.value:
                return False
            time.sleep(0.05)

    # After blinking, hold color
    pixel_controller.set_color(color)
    for _ in range(int(post_blink_pause / 0.05)):
        if button and not button.value:
            return False
        time.sleep(0.05)

    return True

def run_current_weather_mode(button, weather, update_interval=600):
    """
    The default 'current_weather_mode':
      - Periodically fetches current temperature & near-future precip chance.
      - Continuously shows blink_for_precip based on that data.
      - Returns to code.py when the user presses the button.
    """
    pixel_controller = PixelController()  # Get singleton instance
    
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    last_update = None
    current_temp = None
    precip_chance_in_window = None

    while True:
        now = time.monotonic()

        if last_update is None or (now - last_update) >= update_interval:
            print(f"Updating weather data for zip code {weather.zip_code}")
            current_temp = weather.get_current_temperature()
            precip_chance_in_window = weather.get_precip_chance_in_window(0, 4)
            last_update = now
            print("Current temp (°F):", current_temp)
            print("Precip chance next 4h (%):", precip_chance_in_window)

        current_color = temperature_color(current_temp)

        # If blink_for_precip returns False, user pressed button
        if not blink_for_precip(pixel_controller, current_color, precip_chance_in_window, button):
            break

        # Also check for button press after each blink cycle
        if not button.value:
            break  # Return immediately while button still pressed

        time.sleep(0.05)

def run_temp_demo_mode(button):
    """
    Continuously cycles 0°F->100°F, slower pacing,
    then goes dark 2s, repeats.
    Returns when user presses button.
    """
    pixel_controller = PixelController()  # Get singleton instance
    
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        print("Temp Demo Mode: 0->100°F cycle")

        # Slower step time
        step_time = 0.15
        for temp_f in range(101):
            color = temperature_color(temp_f)
            pixel_controller.set_color(color)

            # Check button in small increments
            for _ in range(int(step_time / 0.05)):
                if not button.value:  # pressed
                    return  # Return immediately while button still pressed
                time.sleep(0.05)

        # After 100°F, turn LED off and pause
        pixel_controller.off()
        pause_time = 2.0
        for _ in range(int(pause_time / 0.05)):
            if not button.value:
                return  # Return immediately while button still pressed
            time.sleep(0.05)


def run_precip_demo_mode(button):
    """
    Forces a color corresponding to 10°F, uses blink_for_precip with 30%,
    loops continuously until the user presses button to exit.
    """
    pixel_controller = PixelController()  # Get singleton instance
    
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        print("Precip Demo Mode: color=10°F, precip=30%")

        color_for_10f = temperature_color(10)
        # If the user presses button mid-blink, exit
        if not blink_for_precip(pixel_controller, color_for_10f, 30, button):
            break

        if not button.value:  # pressed
            break  # Return immediately while button still pressed

def run_setup_mode(button, error=None):
    """
    Enters setup mode with setup portal for WiFi configuration.
    Returns when setup is complete or user cancels with button press.
    
    Args:
        button: The button instance to check for user input
        error: Optional error dict to display in the portal (with 'message' and 'field')
    """
    from setup_portal import SetupPortal
    
    print("Entering setup mode...")
    
    # Begin pulsing immediately to indicate setup entry (if not already pulsing)
    pixel_controller = PixelController()
    if not pixel_controller._pulsing:
        pixel_controller.start_setup_mode_pulsing()
    # Call tick to ensure animation updates
    pixel_controller.tick()

    # Wait for any current button press to be released
    while not button.value:
        pixel_controller.tick()  # Keep pulsing animation active
        time.sleep(0.1)
    
    # Small delay to debounce - keep pulsing during delay
    debounce_end = time.monotonic() + 0.5
    while time.monotonic() < debounce_end:
        pixel_controller.tick()
        time.sleep(0.05)
    
    # Create and run the setup portal
    portal = SetupPortal(button)
    
    # Set error message if provided
    if error:
        portal.last_connection_error = error
    
    try:
        # LED already pulsing; start access point infrastructure
        portal.start_access_point()
        
        # Run web server
        setup_complete = portal.run_web_server()
        
        if setup_complete:
            # Blink green to indicate success
            portal.blink_success()
            print("Setup completed successfully")
            return True
        else:
            print("Setup cancelled by user")
            # Brief delay to prevent immediate re-entry
            time.sleep(1)
            return False
            
    except Exception as e:
        print(f"Error in setup mode: {e}")
        # Blink red to indicate error
        pixel_controller = PixelController()  # Get singleton instance
        pixel_controller.blink_error()
        return False
