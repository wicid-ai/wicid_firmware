import time
import board
import neopixel

class PixelController:
    """
    Singleton class that encapsulates NeoPixel control for a single-pixel device.
    Provides helper methods for solid colors, pulsing, blinking, and a non-blocking tick() updater.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PixelController, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not PixelController._initialized:
            # Initialize the NeoPixel hardware
            self.pixels = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3, auto_write=True)
            self._pulsing = False
            self._pulse_color = (255, 255, 255)
            self._min_b = 0.3
            self._max_b = 1.0
            self._step = 0.02
            self._interval = 0.05
            self._brightness = 0.5
            self._direction = 1
            self._last_update = time.monotonic()
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
        self._pulsing = True
        self._pulse_color = color
        self._min_b = min_b
        self._max_b = max_b
        self._step = step
        self._interval = interval
        self._brightness = start_brightness
        self._direction = 1
        self._last_update = time.monotonic()
        # Set initial color
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))

    def stop_pulsing(self):
        self._pulsing = False

    def tick(self):
        if not self._pulsing:
            return
        now = time.monotonic()
        if now - self._last_update < self._interval:
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

    def blink_success(self, times=3, on_time=0.5, off_time=0.2):
        try:
            was_pulsing = self._pulsing
            self.stop_pulsing()
            for _ in range(times):
                self.set_color((0, 255, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            if was_pulsing:
                self.start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
        except Exception as e:
            print(f"PixelController.blink_success error: {e}")

    def blink_error(self, times=3, on_time=0.5, off_time=0.2):
        try:
            was_pulsing = self._pulsing
            self.stop_pulsing()
            for _ in range(times):
                self.set_color((255, 0, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            if was_pulsing:
                self.start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
        except Exception as e:
            print(f"PixelController.blink_error error: {e}")

    def flash_blue_green(self, start_time):
        """
        Flash blue and green alternately (4 times per second).
        Used for Safe Mode indicator and update installation.
        
        Args:
            start_time: Monotonic timestamp when flashing started
        """
        try:
            cycle = int((time.monotonic() - start_time) * 4) % 2
            if cycle == 0:
                self.set_color((0, 0, 255))  # Blue
            else:
                self.set_color((0, 255, 0))  # Green
        except Exception as e:
            print(f"PixelController.flash_blue_green error: {e}")
