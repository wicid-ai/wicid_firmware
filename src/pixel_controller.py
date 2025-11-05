import time
import board
import neopixel
from logging_helper import get_logger

class _OperationContext:
    """Context manager for LED operations that auto-restores previous state."""
    
    def __init__(self, pixel_controller, operation_method):
        self.pixel_controller = pixel_controller
        self.operation_method = operation_method
        self.saved_state = None
    
    def __enter__(self):
        # Save current state
        self.saved_state = self.pixel_controller._save_state()
        # Start the operation
        self.operation_method()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore previous state
        self.pixel_controller._restore_state(self.saved_state)
        return False


class PixelController:
    """
    Singleton class that encapsulates NeoPixel control for a single-pixel device.
    
    Provides semantic, high-level operations (indicate_downloading, indicate_setup_mode, etc.)
    that hide implementation details. All animations are non-blocking and time-based.
    
    External code should:
    - Call semantic operation methods to express intent
    - Call tick() regularly from centralized locations for smooth animations
    - Use context managers for automatic state management
    
    External code should NOT:
    - Access internal state (_mode, MODE_* constants)
    - Call low-level animation methods directly (start_flashing, start_pulsing)
    - Manage animation parameters (colors, rates)
    """
    _instance = None
    _initialized = False
    
    # Animation modes (private - do not access from external code)
    _MODE_SOLID = 0
    _MODE_PULSING = 1
    _MODE_FLASHING = 2
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PixelController, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not PixelController._initialized:
            self.logger = get_logger('wicid.pixel')
            # Initialize the NeoPixel hardware
            self.pixels = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3, auto_write=True)
            
            # Animation state
            self._mode = self._MODE_SOLID
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
            
            # Operation stack for state management
            self._state_stack = []
            
            PixelController._initialized = True

    def set_color(self, rgb):
        try:
            r, g, b = rgb
            self.pixels[0] = (int(r), int(g), int(b))
            # Some builds require explicit show
            if hasattr(self.pixels, 'show'):
                self.pixels.show()
        except Exception as e:
            self.logger.warning(f"set_color error: {e}")

    def off(self):
        self.set_color((0, 0, 0))

    def _apply_brightness(self, rgb, brightness):
        r, g, b = rgb
        br = max(0.0, min(1.0, float(brightness)))
        return (int(r * br), int(g * br), int(b * br))

    def _save_state(self):
        """Save current animation state for later restoration."""
        return {
            'mode': self._mode,
            'pulse_color': self._pulse_color,
            'min_b': self._min_b,
            'max_b': self._max_b,
            'step': self._step,
            'interval': self._interval,
            'brightness': self._brightness,
            'direction': self._direction,
            'flash_colors': self._flash_colors[:],
            'flash_rate': self._flash_rate,
        }
    
    def _restore_state(self, state):
        """Restore animation state from saved state."""
        if state is None:
            return
        
        self._mode = state['mode']
        self._pulse_color = state['pulse_color']
        self._min_b = state['min_b']
        self._max_b = state['max_b']
        self._step = state['step']
        self._interval = state['interval']
        self._brightness = state['brightness']
        self._direction = state['direction']
        self._flash_colors = state['flash_colors']
        self._flash_rate = state['flash_rate']
        
        # Re-initialize animation based on mode
        if self._mode == self._MODE_PULSING:
            self._last_update = time.monotonic()
            self._animation_start = time.monotonic()
            self.set_color(self._apply_brightness(self._pulse_color, self._brightness))
        elif self._mode == self._MODE_FLASHING:
            self._animation_start = time.monotonic()
            self._update_flash()
        elif self._mode == self._MODE_SOLID:
            # Keep current color
            pass
    
    def _start_pulsing(self, color=(255, 255, 255), min_b=0.3, max_b=1.0, step=0.02, interval=0.05, start_brightness=0.5):
        """Internal method to start pulsing animation."""
        self._mode = self._MODE_PULSING
        self._pulse_color = color
        self._min_b = min_b
        self._max_b = max_b
        self._step = step
        self._interval = interval
        self._brightness = start_brightness
        self._direction = 1
        self._last_update = time.monotonic()
        self._animation_start = time.monotonic()
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))
    
    def _start_flashing(self, colors=None, rate=4):
        """Internal method to start flashing animation."""
        self._mode = self._MODE_FLASHING
        if colors:
            self._flash_colors = colors
        else:
            self._flash_colors = [(0, 0, 255), (0, 255, 0)]  # Blue/Green
        self._flash_rate = rate
        self._animation_start = time.monotonic()
        self._update_flash()
    
    def _indicate_updating(self):
        """
        Internal method for all update-related operations.
        Blue/green flashing at 0.5Hz (slow) for better visibility during long operations.
        Rate reduced from 4Hz to avoid aliasing with infrequent tick() calls.
        """
        self._start_flashing([(0, 0, 255), (0, 255, 0)], rate=2)
    
    def indicate_downloading(self):
        """
        Indicate firmware download in progress.
        Shows blue/green flashing pattern.
        """
        self._indicate_updating()
    
    def indicate_verifying(self):
        """
        Indicate firmware verification in progress.
        Shows blue/green flashing pattern (same as downloading).
        """
        self._indicate_updating()
    
    def indicate_installing(self):
        """
        Indicate firmware installation in progress.
        Shows blue/green flashing pattern (same as downloading).
        """
        self._indicate_updating()
    
    def indicate_setup_mode(self):
        """
        Indicate setup mode is active.
        Shows white pulsing pattern.
        """
        self._start_pulsing(
            color=(255, 255, 255),
            min_b=0.1,
            max_b=0.7,
            step=0.03,
            interval=0.04,
            start_brightness=0.4,
        )
    
    def indicate_safe_mode(self):
        """
        Indicate safe mode entry (10+ second button hold).
        Shows blue/green flashing pattern.
        """
        self._indicate_updating()
    
    def restore_previous(self):
        """Restore the previous LED state from the state stack."""
        if self._state_stack:
            state = self._state_stack.pop()
            self._restore_state(state)
        else:
            # No saved state, turn off
            self.clear()
    
    def clear(self):
        """Turn off LED and reset to solid mode."""
        self._mode = self._MODE_SOLID
        self.off()
    
    def indicate_operation(self, operation_name):
        """
        Context manager for semantic operations.
        Automatically restores previous state on exit.
        
        Args:
            operation_name: Name of operation ('downloading', 'verifying', 'installing', 'setup_mode')
        
        Returns:
            Context manager that handles state save/restore
        
        Example:
            with pixel_controller.indicate_operation('downloading'):
                # Download code here
                pass
            # LED automatically restored to previous state
        """
        operation_map = {
            'downloading': self.indicate_downloading,
            'verifying': self.indicate_verifying,
            'installing': self.indicate_installing,
            'setup_mode': self.indicate_setup_mode,
            'safe_mode': self.indicate_safe_mode,
        }
        
        operation_method = operation_map.get(operation_name)
        if operation_method is None:
            raise ValueError(f"Unknown operation: {operation_name}")
        
        return _OperationContext(self, operation_method)
    
    # Deprecated methods - kept for backward compatibility
    
    def start_pulsing(self, color=(255, 255, 255), min_b=0.3, max_b=1.0, step=0.02, interval=0.05, start_brightness=0.5):
        """
        DEPRECATED: Use semantic methods (indicate_setup_mode, etc.) instead.
        Start pulsing animation. Updates automatically when tick() is called.
        """
        self._start_pulsing(color, min_b, max_b, step, interval, start_brightness)

    def stop_pulsing(self):
        """DEPRECATED: Use clear() or restore_previous() instead."""
        self._mode = self._MODE_SOLID

    def start_setup_mode_pulsing(self):
        """DEPRECATED: Use indicate_setup_mode() instead."""
        self.indicate_setup_mode()

    def start_flashing(self, colors=None, rate=4):
        """
        DEPRECATED: Use semantic methods (indicate_downloading, etc.) instead.
        Start flashing animation between colors.
        """
        self._start_flashing(colors, rate)
    
    def stop_flashing(self):
        """DEPRECATED: Use clear() or restore_previous() instead."""
        self._mode = self._MODE_SOLID
    
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
        if self._mode == self._MODE_PULSING:
            self._update_pulse()
        elif self._mode == self._MODE_FLASHING:
            self._update_flash()
        # _MODE_SOLID does nothing - color is already set

    def blink_success(self, times=3, on_time=0.5, off_time=0.2):
        """Blocking blink green for success indication."""
        try:
            # Save previous mode to restore after blinking
            previous_mode = self._mode
            self._mode = self._MODE_SOLID
            
            for _ in range(times):
                self.set_color((0, 255, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            
            # Restore previous animation mode
            if previous_mode == self._MODE_PULSING:
                self._start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
            elif previous_mode == self._MODE_FLASHING:
                self._start_flashing(self._flash_colors, self._flash_rate)
        except Exception as e:
            self.logger.warning(f"blink_success error: {e}")

    def blink_error(self, times=3, on_time=0.5, off_time=0.2):
        """Blocking blink red for error indication."""
        try:
            # Save previous mode to restore after blinking
            previous_mode = self._mode
            self._mode = self._MODE_SOLID
            
            for _ in range(times):
                self.set_color((255, 0, 0))
                time.sleep(on_time)
                self.off()
                time.sleep(off_time)
            
            # Restore previous animation mode
            if previous_mode == self._MODE_PULSING:
                self._start_pulsing(self._pulse_color, self._min_b, self._max_b, self._step, self._interval, self._brightness)
            elif previous_mode == self._MODE_FLASHING:
                self._start_flashing(self._flash_colors, self._flash_rate)
        except Exception as e:
            self.logger.warning(f"blink_error error: {e}")

    def flash_blue_green(self, start_time):
        """
        Flash blue and green alternately (4 times per second).
        Used for Safe Mode indicator and update installation.
        
        DEPRECATED: Use indicate_installing() or indicate_safe_mode() for new code.
        This method is kept for backward compatibility.
        
        Args:
            start_time: Monotonic timestamp when flashing started (for compatibility)
        """
        try:
            # If not already in flashing mode, start it
            if self._mode != self._MODE_FLASHING:
                self._indicate_updating()
            else:
                # Already flashing, just update
                self.tick()
        except Exception as e:
            self.logger.warning(f"flash_blue_green error: {e}")
