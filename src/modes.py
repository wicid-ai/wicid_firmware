import time
import os
from scheduler import Scheduler
from configuration_manager import ConfigurationManager
from button_action_router import ButtonActionRouter

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

async def blink_for_precip(pixel_controller, color, precip_percent, is_pressed_fn=None):
    """
    Blinks the NeoPixel according to the 'rounded to nearest 10%' precipitation probability.
      - Example: 27% => 30% => 3 blinks, then hold color for a few seconds.
      - If ``is_pressed_fn`` returns True, exit mid-cycle for immediate response.
    """
    fast_blink_on = 0.3
    fast_blink_off = 0.2
    post_blink_pause = 3.0

    def should_interrupt():
        if not is_pressed_fn:
            return False
        try:
            return bool(is_pressed_fn())
        except Exception:
            return False

    if precip_percent is None:
        # No data: just hold color for a short time
        pixel_controller.set_color(color)
        for _ in range(int(1 / 0.05)):  # ~1 second, checking button
            if should_interrupt():
                return False
            await Scheduler.sleep(0.05)
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
            if should_interrupt():
                return False
            await Scheduler.sleep(0.05)

        pixel_controller.off()
        for _ in range(int(fast_blink_off / 0.05)):
            if should_interrupt():
                return False
            await Scheduler.sleep(0.05)

    # After blinking, hold color
    pixel_controller.set_color(color)
    for _ in range(int(post_blink_pause / 0.05)):
        if should_interrupt():
            return False
        await Scheduler.sleep(0.05)

    return True



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
    
    def __init__(self):
        super().__init__()
        self.weather = None
        self.update_interval = int(os.getenv("WEATHER_UPDATE_INTERVAL", "600"))
        self.last_update = None
        self.current_temp = None
        self.precip_chance = None
        self._weather_refresh_handle = None
    
    def initialize(self) -> bool:
        """Initialize weather service."""
        if not super().initialize():
            return False
        
        try:
            # Load weather ZIP from credentials
            credentials = self.connection_manager.get_credentials()
            if not credentials or not credentials.get('weather_zip'):
                self.logger.warning("No weather ZIP configured")
                return False
            
            zip_code = credentials['weather_zip']
            
            # Create weather service
            from weather_service import WeatherService
            self.weather = WeatherService(zip_code)
            
            # Get system manager singleton (periodic system checks)
            from system_manager import SystemManager
            self.system_manager = SystemManager.get_instance()
            
            self.logger.info(f"Initialized for ZIP {zip_code}")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return False
    
    async def run(self) -> None:
        """Run weather display loop."""
        self._running = True
        
        # Wait for button release
        await self.wait_for_button_release()
        
        self.logger.info("Starting display loop")
        self._start_weather_refresh_task()
        
        while self._running:
            if self.current_temp is None or self.precip_chance is None:
                await Scheduler.sleep(0.1)
                continue
            
            # Display temperature color with precipitation blinks
            current_color = temperature_color(self.current_temp)
            
            if not await blink_for_precip(self.pixel, current_color, self.precip_chance, self.is_button_pressed):
                # Button pressed during blink
                break
            
            # Check button after blink cycle
            if self.is_button_pressed():
                break
            
            # System manager checks (updates, periodic reboot)
            if self.system_manager:
                await self.system_manager.tick()
            
            await Scheduler.sleep(0.05)
        
        self._stop_weather_refresh_task()
        self.logger.info("Exiting")
    
    def cleanup(self) -> None:
        """Clean up weather mode resources."""
        super().cleanup()
        self.weather = None
        self.system_manager = None
        self._stop_weather_refresh_task()

    def _start_weather_refresh_task(self):
        """Schedule recurring weather refresh task via scheduler."""
        if self._weather_refresh_handle is not None:
            return

        scheduler = Scheduler.instance()
        self._weather_refresh_handle = scheduler.schedule_recurring(
            coroutine=self._weather_refresh_job,
            interval=self.update_interval,
            priority=40,
            name="Weather Data Refresh",
        )

    def _stop_weather_refresh_task(self):
        """Cancel scheduled weather refresh task if running."""
        if self._weather_refresh_handle is None:
            return

        try:
            scheduler = Scheduler.instance()
            scheduler.cancel(self._weather_refresh_handle)
        except Exception:
            pass
        finally:
            self._weather_refresh_handle = None

    async def _weather_refresh_job(self):
        """Fetch latest weather data without blocking the display loop."""
        if not self._running or self.weather is None:
            return

        try:
            temp = self.weather.get_current_temperature()
            precip = self.weather.get_precip_chance_in_window(0, 4)

            if temp is not None:
                self.current_temp = temp
            if precip is not None:
                self.precip_chance = precip
            self.last_update = time.monotonic()
            temp_msg = f"{temp}°F" if temp is not None else "n/a"
            precip_msg = f"{precip}%" if precip is not None else "n/a"
            self.logger.info(f"Weather update: {temp_msg}, {precip_msg} precip chance")
        except Exception as err:
            self.logger.error(f"Weather refresh failed: {err}")
            await Scheduler.sleep(0.5)


class TempDemoMode(Mode):
    """
    Temperature demo mode - cycles through 0°F to 100°F showing color gradient.
    """
    
    name = "TempDemo"
    requires_wifi = False
    order = 10  # Secondary mode
    
    async def run(self) -> None:
        """Run temperature demo loop."""
        self._running = True
        
        # Wait for button release
        await self.wait_for_button_release()
        
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
                    if self.is_button_pressed():
                        self._running = False
                        return
                    await Scheduler.sleep(0.05)
            
            # Pause with LED off
            self.pixel.off()
            pause_time = 2.0
            for _ in range(int(pause_time / 0.05)):
                if self.is_button_pressed():
                    self._running = False
                    return
                await Scheduler.sleep(0.05)
        
        self.logger.info("Exiting")


class PrecipDemoMode(Mode):
    """
    Precipitation demo mode - shows blink pattern for 30% precipitation chance at 10°F.
    """
    
    name = "PrecipDemo"
    requires_wifi = False
    order = 20  # Secondary mode
    
    async def run(self) -> None:
        """Run precipitation demo loop."""
        self._running = True
        
        # Wait for button release
        await self.wait_for_button_release()
        
        self.logger.info("Starting demo (10°F, 30% precip)")
        
        color_for_10f = temperature_color(10)
        
        while self._running:
            # Show precipitation blink pattern
            if not await blink_for_precip(self.pixel, color_for_10f, 30, self.is_button_pressed):
                # Button pressed during blink
                break
            
            # Check button after blink cycle
            if self.is_button_pressed():
                break
        
        self.logger.debug("Exiting")


class SetupPortalMode(Mode):
    """
    Mode wrapper around the configuration portal so button handling remains centralized.
    """

    name = "SetupPortal"
    requires_wifi = False
    order = 1000  # Not part of normal cycle

    def __init__(self, error=None):
        super().__init__()
        self._error = error
        self._session = None
        self._config_mgr = ConfigurationManager.get_instance()
        self._button_router = ButtonActionRouter.instance()

    def initialize(self) -> bool:
        self._session = self._button_router.acquire_session(session_logger=self.logger)
        self._session.reset()
        return True

    async def run(self) -> bool:
        await self.wait_for_button_release()
        try:
            result = await self._config_mgr.run_portal(
                error=self._error,
                button_session=self._session,
            )
            return result
        finally:
            self._error = None

    def cleanup(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        super().cleanup()

    @classmethod
    async def execute(cls, *, error=None):
        """Convenience helper to run setup portal outside standard mode loop."""
        mode = cls(error=error)
        if not mode.initialize():
            return False
        try:
            return await mode.run()
        finally:
            mode.cleanup()
