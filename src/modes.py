import time
import board
import digitalio
import json
import storage
import os
from logging_helper import get_logger
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

def run_current_weather_mode(button, weather, update_interval=600, system_monitor=None):
    """
    The default 'current_weather_mode':
      - Periodically fetches current temperature & near-future precip chance.
      - Continuously shows blink_for_precip based on that data.
      - Returns to code.py when the user presses the button.
    
    Args:
        button: Button instance
        weather: Weather service instance
        update_interval: Seconds between weather updates
        system_monitor: Optional SystemMonitor instance for periodic system checks
    """
    logger_func = get_logger('wicid.modes.weather')
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
            logger_func.debug(f"Updating weather data for zip code {weather.zip_code}")
            current_temp = weather.get_current_temperature()
            precip_chance_in_window = weather.get_precip_chance_in_window(0, 4)
            last_update = now
            logger_func.info(f"Weather update: {current_temp}°F, {precip_chance_in_window}% precip chance")

        current_color = temperature_color(current_temp)

        # If blink_for_precip returns False, user pressed button
        if not blink_for_precip(pixel_controller, current_color, precip_chance_in_window, button):
            break

        # Also check for button press after each blink cycle
        if not button.value:
            break  # Return immediately while button still pressed

        # Allow system monitor to perform periodic checks (update checks, reboots)
        if system_monitor:
            system_monitor.tick()

        time.sleep(0.05)

def run_temp_demo_mode(button):
    """
    Continuously cycles 0°F->100°F, slower pacing,
    then goes dark 2s, repeats.
    Returns when user presses button.
    """
    logger_func = get_logger('wicid.modes.temp_demo')
    pixel_controller = PixelController()  # Get singleton instance
    
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        logger_func.debug("Temp Demo Mode: 0->100°F cycle")

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
    logger_func = get_logger('wicid.modes.precip_demo')
    pixel_controller = PixelController()  # Get singleton instance
    
    # Ensure button is released before starting
    while not button.value:
        time.sleep(0.05)

    while True:
        logger_func.debug("Precip Demo Mode: color=10°F, precip=30%")

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
    from configuration_manager import ConfigurationManager
    
    logger = get_logger('wicid.modes.setup')
    logger.info("Entering setup mode")
    
    # Begin pulsing immediately to indicate setup entry
    pixel_controller = PixelController()
    pixel_controller.indicate_setup_mode()
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
    
    # Get ConfigurationManager singleton and run portal
    config_mgr = ConfigurationManager.get_instance(button)
    
    try:
        # run_portal handles setup indicator, AP, web server, and lifecycle
        return config_mgr.run_portal(error=error)
            
    except Exception as e:
        logger.error(f"Error in setup mode: {e}")
        # Blink red to indicate error
        pixel_controller = PixelController()  # Get singleton instance
        pixel_controller.blink_error()
        return False


# ============================================================================
# Mode Classes (New Architecture)
# ============================================================================

from mode_interface import Mode


class WeatherMode(Mode):
    """
    Main weather mode showing current temperature and precipitation probability.
    
    Displays:
    - LED color based on current temperature
    - Blinks to indicate precipitation probability (0-100%, rounded to nearest 10%)
    """
    
    name = "Weather"
    requires_wifi = True
    order = 0  # Primary mode
    
    def __init__(self, button):
        super().__init__(button)
        self.weather = None
        self.system_monitor = None
        self.update_interval = int(os.getenv("WEATHER_UPDATE_INTERVAL", "600"))
        self.last_update = None
        self.current_temp = None
        self.precip_chance = None
    
    def initialize(self) -> bool:
        """Initialize weather service."""
        if not super().initialize():
            return False
        
        try:
            # Load weather ZIP from credentials
            credentials = self.wifi_manager.get_credentials()
            if not credentials or not credentials.get('weather_zip'):
                self.logger.warning("No weather ZIP configured")
                return False
            
            zip_code = credentials['weather_zip']
            
            # Create weather service
            from weather import Weather
            session = self.wifi_manager.create_session()
            self.weather = Weather(session, zip_code)
            
            # Create system monitor
            from system_monitor import SystemMonitor
            self.system_monitor = SystemMonitor()
            
            self.logger.info(f"Initialized for ZIP {zip_code}")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return False
    
    def run(self) -> None:
        """Run weather display loop."""
        self._running = True
        
        # Wait for button release
        while not self.button.value:
            time.sleep(0.05)
        
        self.logger.info("Starting display loop")
        
        while self._running:
            now = time.monotonic()
            
            # Update weather data periodically
            if self.last_update is None or (now - self.last_update) >= self.update_interval:
                self.logger.debug(f"Updating weather data for ZIP {self.weather.zip_code}")
                self.current_temp = self.weather.get_current_temperature()
                self.precip_chance = self.weather.get_precip_chance_in_window(0, 4)
                self.last_update = now
                self.logger.info(f"Weather update: {self.current_temp}°F, {self.precip_chance}% precip chance")
            
            # Display temperature color with precipitation blinks
            current_color = temperature_color(self.current_temp)
            
            if not blink_for_precip(self.pixel, current_color, self.precip_chance, self.button):
                # Button pressed during blink
                break
            
            # Check button after blink cycle
            if not self.button.value:
                break
            
            # System monitor checks (updates, periodic reboot)
            if self.system_monitor:
                self.system_monitor.tick()
            
            time.sleep(0.05)
        
        self.logger.info("Exiting")
    
    def cleanup(self) -> None:
        """Clean up weather mode resources."""
        super().cleanup()
        self.weather = None
        self.system_monitor = None


class TempDemoMode(Mode):
    """
    Temperature demo mode - cycles through 0°F to 100°F showing color gradient.
    """
    
    name = "TempDemo"
    requires_wifi = False
    order = 10  # Secondary mode
    
    def run(self) -> None:
        """Run temperature demo loop."""
        self._running = True
        
        # Wait for button release
        while not self.button.value:
            time.sleep(0.05)
        
        self.logger.info("Starting demo")
        
        while self._running:
            self.logger.debug("Temp Demo: 0->100°F cycle")
            
            # Cycle through temperatures
            step_time = 0.15
            for temp_f in range(101):
                color = temperature_color(temp_f)
                self.pixel.set_color(color)
                
                # Check button in small increments
                for _ in range(int(step_time / 0.05)):
                    if not self.button.value:
                        self._running = False
                        return
                    time.sleep(0.05)
            
            # Pause with LED off
            self.pixel.off()
            pause_time = 2.0
            for _ in range(int(pause_time / 0.05)):
                if not self.button.value:
                    self._running = False
                    return
                time.sleep(0.05)
        
        self.logger.info("Exiting")


class PrecipDemoMode(Mode):
    """
    Precipitation demo mode - shows blink pattern for 30% precipitation chance at 10°F.
    """
    
    name = "PrecipDemo"
    requires_wifi = False
    order = 20  # Secondary mode
    
    def run(self) -> None:
        """Run precipitation demo loop."""
        self._running = True
        
        # Wait for button release
        while not self.button.value:
            time.sleep(0.05)
        
        self.logger.info("Starting demo (10°F, 30% precip)")
        
        color_for_10f = temperature_color(10)
        
        while self._running:
            # Show precipitation blink pattern
            if not blink_for_precip(self.pixel, color_for_10f, 30, self.button):
                # Button pressed during blink
                break
            
            # Check button after blink cycle
            if not self.button.value:
                break
        
        self.logger.debug("Exiting")
