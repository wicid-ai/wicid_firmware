import time
import board
import neopixel

class PixelController:
    """
    Singleton class that encapsulates NeoPixel control for a single-pixel device.
    Provides time-based animations that update automatically when tick() is called.
    
    All animations are non-blocking and time-based for consistent, reliable patterns
    regardless of what other operations are happening.
    """
    _instance = None
    _initialized = False
    
    # Animation modes
    MODE_SOLID = 0
    MODE_PULSING = 1
    MODE_FLASHING = 2
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PixelController, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not PixelController._initialized:
            # Initialize the NeoPixel hardware
            self.pixels = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3, auto_write=True)
            
            # Animation state
            self._mode = self.MODE_SOLID
            self._animation_start = None
            self._last_update = time.monotonic()
            
            # Pulsing parameters
            self._pulse_color = (255, 255, 255)
            self._min_b = 0.3
            self._max_b = 1.0
            self._step = 0.02
            self._interval = 0.05
            self._brightness = 0.5
            self._direction = 1
            
            # Flashing parameters
            self._flash_colors = [(0, 0, 255), (0, 255, 0)]  # Blue/Green
            self._flash_rate = 4  # Hz
            
            PixelController._initialized = True

    def set_color(self, rgb):
        try:
            r, g, b = rgb
            self.pixels[0] = (int(r), int(g), int(b))
            # Some builds require explicit show
            if hasattr(self.pixels, 'show'):
                self.pixels.show()
        except Exception as e:
            print(f"PixelController.set_color error: {e}")

    def off(self):
        self.set_color((0, 0, 0))

    def _apply_brightness(self, rgb, brightness):
        r, g, b = rgb
        br = max(0.0, min(1.0, float(brightness)))
        return (int(r * br), int(g * br), int(b * br))

    def start_pulsing(self, color=(255, 255, 255), min_b=0.3, max_b=1.0, step=0.02, interval=0.05, start_brightness=0.5):
        """Start pulsing animation. Updates automatically when tick() is called."""
        self._mode = self.MODE_PULSING
        self._pulse_color = color
        self._min_b = min_b
        self._max_b = max_b
        self._step = step
        self._interval = interval
        self._brightness = start_brightness
        self._direction = 1
        self._last_update = time.monotonic()
        self._animation_start = time.monotonic()
        # Set initial color
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))

    def stop_pulsing(self):
        """Stop pulsing animation."""
        self._mode = self.MODE_SOLID

    def start_setup_mode_pulsing(self):
        """
        Start pulsing white to indicate setup mode is active.
        Uses the same pattern for button hold indication and setup mode itself.
        """
        self.start_pulsing(
            color=(255, 255, 255),
            min_b=0.1,
            max_b=0.7,
            step=0.03,
            interval=0.04,
            start_brightness=0.4,
        )

    def start_flashing(self, colors=None, rate=4):
        """
        Start flashing animation between colors.
        Updates automatically when tick() is called.
        
        Args:
            colors: List of RGB tuples to cycle through (default: blue/green)
            rate: Flash rate in Hz (default: 4)
        """
        self._mode = self.MODE_FLASHING
        if colors:
            self._flash_colors = colors
        else:
            self._flash_colors = [(0, 0, 255), (0, 255, 0)]  # Blue/Green
        self._flash_rate = rate
        self._animation_start = time.monotonic()
        self._update_flash()
    
    def stop_flashing(self):
        """Stop flashing animation."""
        self._mode = self.MODE_SOLID
    
    def _update_pulse(self):
        """Update pulsing animation based on time."""
        now = time.monotonic()
        time_since_last = now - self._last_update
        if time_since_last < self._interval:
            return
        self._last_update = now
        # Update brightness
        self._brightness += self._step * self._direction
        if self._brightness >= self._max_b:
            self._brightness = self._max_b
            self._direction = -1
        elif self._brightness <= self._min_b:
            self._brightness = self._min_b
            self._direction = 1
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))
    
    def _update_flash(self):
        """Update flashing animation based on time."""
        if self._animation_start is None:
            return
        elapsed = time.monotonic() - self._animation_start
        cycle = int(elapsed * self._flash_rate) % len(self._flash_colors)
        self.set_color(self._flash_colors[cycle])
    
    def tick(self):
        """
        Update current animation based on time.
        Call this frequently (e.g., in main loop or during operations) for smooth animations.
        Time-based approach ensures consistent animation regardless of call frequency.
        """
        if self._mode == self.MODE_PULSING:
            self._update_pulse()
        elif self._mode == self.MODE_FLASHING:
            self._update_flash()
        # MODE_SOLID does nothing - color is already set

    def blink_success(self, times=3, on_time=0.5, off_time=0.2):
        """Blocking blink green for success indication."""
        try:
            # Save previous mode to restore after blinking
            previous_mode = self._mode
            self._mode = self.MODE_SOLID
            
            for _ in range(times):
                self.set_color((0, 255, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            
            # Restore previous animation mode
            if previous_mode == self.MODE_PULSING:
                self.start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
            elif previous_mode == self.MODE_FLASHING:
                self.start_flashing(self._flash_colors, self._flash_rate)
        except Exception as e:
            print(f"PixelController.blink_success error: {e}")

    def blink_error(self, times=3, on_time=0.5, off_time=0.2):
        """Blocking blink red for error indication."""
        try:
            # Save previous mode to restore after blinking
            previous_mode = self._mode
            self._mode = self.MODE_SOLID
            
            for _ in range(times):
                self.set_color((255, 0, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            
            # Restore previous animation mode
            if previous_mode == self.MODE_PULSING:
                self.start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
            elif previous_mode == self.MODE_FLASHING:
                self.start_flashing(self._flash_colors, self._flash_rate)
        except Exception as e:
            print(f"PixelController.blink_error error: {e}")

    def flash_blue_green(self, start_time):
        """
        Flash blue and green alternately (4 times per second).
        Used for Safe Mode indicator and update installation.
        
        DEPRECATED: Use start_flashing() for new code. This method is kept for
        compatibility with boot_support.py but now uses the time-based animation system.
        
        Args:
            start_time: Monotonic timestamp when flashing started (for compatibility)
        """
        try:
            # If not already in flashing mode, start it
            if self._mode != self.MODE_FLASHING:
                self.start_flashing([(0, 0, 255), (0, 255, 0)], rate=4)
            else:
                # Already flashing, just update
                self.tick()
        except Exception as e:
            print(f"PixelController.flash_blue_green error: {e}")
