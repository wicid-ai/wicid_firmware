import time

import board  # type: ignore[import-not-found]  # CircuitPython-only module
import neopixel  # type: ignore[import-not-found]  # CircuitPython-only module

from app_typing import Any, Dict, List, Optional
from logging_helper import logger
from scheduler import Scheduler


class _OperationContext:
    """Async context manager for LED operations that auto-restores previous state."""

    def __init__(self, pixel_controller: "PixelController", operation_method: Any) -> None:
        self.pixel_controller = pixel_controller
        self.operation_method = operation_method
        self.saved_state: Optional[Dict[str, Any]] = None

    async def __aenter__(self) -> "_OperationContext":
        # Save current state
        self.saved_state = self.pixel_controller._save_state()
        # Start the operation
        if callable(self.operation_method):
            self.operation_method()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
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

    def __new__(cls) -> "PixelController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls, pixel: Any = None) -> "PixelController":
        """
        Get the PixelController singleton instance.

        Args:
            pixel: Optional NeoPixel instance. If None, creates from board.NEOPIXEL

        Returns:
            The global PixelController instance
        """
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._init(pixel)
        return cls._instance

    def __init__(self, pixel: Any = None) -> None:
        """
        Initialize PixelController (called via singleton pattern).

        Args:
            pixel: Optional NeoPixel instance. If None, creates from board.NEOPIXEL
        """
        if PixelController._initialized:
            return
        self._init(pixel)

    def _init(self, pixel: Any = None) -> None:
        """
        Internal initialization method.

        Args:
            pixel: Optional NeoPixel instance. If None, creates from board.NEOPIXEL
        """
        self.logger = logger("wicid.pixel")

        # Initialize the NeoPixel hardware
        if pixel is None:
            self.pixels = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3, auto_write=True)
        else:
            self.pixels = pixel

        # Animation state (frame-based, not time-based)
        self._mode = self._MODE_SOLID
        self._frame_counter = 0

        # Pulsing parameters
        self._pulse_color = (255, 255, 255)
        self._min_b = 0.3
        self._max_b = 1.0
        self._brightness = 0.5
        self._direction = 1

        # Flashing parameters
        self._flash_colors = [(0, 0, 255), (0, 255, 0)]  # Blue/Green
        self._flash_frame_duration = 12  # Frames per color change at 25Hz (0.5s per color)
        self._manual_tick_interval = 0.04  # seconds between manual animation ticks
        self._last_manual_tick = 0.0

        # Operation stack for state management
        self._state_stack: List[Dict[str, Any]] = []

        # Register LED animation task with scheduler (25Hz = 40ms period)
        animation_period = 0.04
        scheduler = Scheduler.instance()
        self._task_handle = scheduler.schedule_periodic(
            coroutine=self._animation_task,
            period=animation_period,
            priority=0,  # Highest priority (critical real-time)
            name="LED Animation",
        )

        PixelController._initialized = True
        self.logger.info("PixelController initialized with scheduled animation task")

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        try:
            r, g, b = rgb
            self.pixels[0] = (int(r), int(g), int(b))
            # Some builds require explicit show
            if hasattr(self.pixels, "show"):
                self.pixels.show()
        except Exception as e:
            self.logger.warning(f"set_color error: {e}")

    def off(self) -> None:
        self.set_color((0, 0, 0))

    def _apply_brightness(self, rgb: tuple[int, int, int], brightness: float) -> tuple[int, int, int]:
        r, g, b = rgb
        br = max(0.0, min(1.0, float(brightness)))
        return (int(r * br), int(g * br), int(b * br))

    def _save_state(self) -> dict[str, Any]:
        """Save current animation state for later restoration."""
        return {
            "mode": self._mode,
            "pulse_color": self._pulse_color,
            "min_b": self._min_b,
            "max_b": self._max_b,
            "brightness": self._brightness,
            "direction": self._direction,
            "flash_colors": self._flash_colors[:],
            "flash_frame_duration": self._flash_frame_duration,
            "frame_counter": self._frame_counter,
        }

    def _restore_state(self, state: dict[str, Any] | None) -> None:
        """Restore animation state from saved state."""
        if state is None:
            return

        self._mode = state["mode"]
        self._pulse_color = state["pulse_color"]
        self._min_b = state["min_b"]
        self._max_b = state["max_b"]
        self._brightness = state["brightness"]
        self._direction = state["direction"]
        self._flash_colors = state["flash_colors"]
        self._flash_frame_duration = state["flash_frame_duration"]
        self._frame_counter = state["frame_counter"]

        # Re-render current frame based on mode
        if self._mode == self._MODE_PULSING:
            self.set_color(self._apply_brightness(self._pulse_color, self._brightness))
        elif self._mode == self._MODE_FLASHING:
            self._render_flash_frame()
        elif self._mode == self._MODE_SOLID:
            # Keep current color
            pass

    def _start_pulsing(
        self,
        color: tuple[int, int, int] = (255, 255, 255),
        min_b: float = 0.3,
        max_b: float = 1.0,
        start_brightness: float = 0.5,
    ) -> None:
        """Internal method to start pulsing animation (frame-based)."""
        self._mode = self._MODE_PULSING
        self._pulse_color = color
        self._min_b = min_b
        self._max_b = max_b
        self._brightness = start_brightness
        self._direction = 1
        self._frame_counter = 0
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))

    def _start_flashing(self, colors: list[tuple[int, int, int]] | None = None, frame_duration: int = 12) -> None:
        """Internal method to start flashing animation (frame-based).

        Args:
            colors: List of RGB colors to flash between
            frame_duration: Frames per color (at 25Hz, 12 frames = 0.5s per color)
        """
        self._mode = self._MODE_FLASHING
        if colors:
            self._flash_colors = colors
        else:
            self._flash_colors = [(0, 0, 255), (0, 255, 0)]  # Blue/Green
        self._flash_frame_duration = frame_duration
        self._frame_counter = 0
        self._render_flash_frame()

    def _indicate_updating(self) -> None:
        """
        Internal method for all update-related operations.
        Blue/green flashing (slow) for better visibility during long operations.
        """
        self._start_flashing([(0, 0, 255), (0, 255, 0)], frame_duration=12)

    def indicate_downloading(self) -> None:
        """
        Indicate firmware download in progress.
        Shows blue/green flashing pattern.
        """
        self._indicate_updating()

    def indicate_verifying(self) -> None:
        """
        Indicate firmware verification in progress.
        Shows blue/green flashing pattern (same as downloading).
        """
        self._indicate_updating()

    def indicate_installing(self) -> None:
        """
        Indicate firmware installation in progress.
        Shows blue/green flashing pattern (same as downloading).
        """
        self._indicate_updating()

    def indicate_setup_mode(self) -> None:
        """
        Indicate setup mode is active.
        Shows white pulsing pattern.
        """
        self._start_pulsing(
            color=(255, 255, 255),
            min_b=0.1,
            max_b=0.7,
            start_brightness=0.4,
        )

    def indicate_safe_mode(self) -> None:
        """
        Indicate safe mode entry (10+ second button hold).
        Shows blue/green flashing pattern.
        """
        self._indicate_updating()

    def restore_previous(self) -> None:
        """Restore the previous LED state from the state stack."""
        if self._state_stack:
            state = self._state_stack.pop()
            self._restore_state(state)
        else:
            # No saved state, turn off
            self.clear()

    def clear(self) -> None:
        """Turn off LED and reset to solid mode."""
        self._mode = self._MODE_SOLID
        self.off()

    def indicate_operation(self, operation_name: str) -> _OperationContext:
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
            "downloading": self.indicate_downloading,
            "verifying": self.indicate_verifying,
            "installing": self.indicate_installing,
            "setup_mode": self.indicate_setup_mode,
            "safe_mode": self.indicate_safe_mode,
        }

        operation_method = operation_map.get(operation_name)
        if operation_method is None:
            raise ValueError(f"Unknown operation: {operation_name}")

        return _OperationContext(self, operation_method)

    def _render_pulse_frame(self) -> None:
        """Render one frame of pulsing animation (frame-based, called at 25Hz)."""
        # Update brightness every frame (0.02 step at 25Hz = 0.5 brightness change per second)
        self._brightness += 0.02 * self._direction
        if self._brightness >= self._max_b:
            self._brightness = self._max_b
            self._direction = -1
        elif self._brightness <= self._min_b:
            self._brightness = self._min_b
            self._direction = 1
        self.set_color(self._apply_brightness(self._pulse_color, self._brightness))

    def _render_flash_frame(self) -> None:
        """Render one frame of flashing animation (frame-based, called at 25Hz)."""
        # Calculate which color to show based on frame counter
        cycle_position = (self._frame_counter // self._flash_frame_duration) % len(self._flash_colors)
        self.set_color(self._flash_colors[cycle_position])

    def _advance_frame(self) -> None:
        """Advance animation frame regardless of execution context."""
        self._frame_counter += 1
        if self._mode == self._MODE_PULSING:
            self._render_pulse_frame()
        elif self._mode == self._MODE_FLASHING:
            self._render_flash_frame()

    async def _animation_task(self) -> None:
        """
        Scheduler task that renders a single animation frame.
        Invoked at 25Hz via the scheduler's periodic scheduling.
        """
        self._advance_frame()

    async def blink_success(
        self, times: int = 3, on_time: float = 0.5, off_time: float = 0.2, restore_previous_state: bool = True
    ) -> None:
        """Non-blocking async blink green for success indication.

        Args:
            times: Number of blinks
            on_time: Seconds LED stays on per blink
            off_time: Seconds LED stays off per blink
            restore_previous_state: If False, keep LED in solid mode after blinking
        """
        try:
            # Save previous state
            saved_state = self._save_state()
            self._mode = self._MODE_SOLID

            for _ in range(times):
                self.set_color((0, 255, 0))
                await Scheduler.sleep(on_time)
                self.off()
                await Scheduler.sleep(off_time)

            # Restore previous animation state if requested
            if restore_previous_state:
                self._restore_state(saved_state)
        except Exception as e:
            self.logger.warning(f"blink_success error: {e}")

    async def blink_error(
        self, times: int = 3, on_time: float = 0.5, off_time: float = 0.2, restore_previous_state: bool = True
    ) -> None:
        """Non-blocking async blink red for error indication."""
        try:
            # Save previous state
            saved_state = self._save_state()
            self._mode = self._MODE_SOLID

            for _ in range(times):
                self.set_color((255, 0, 0))
                await Scheduler.sleep(on_time)
                self.off()
                await Scheduler.sleep(off_time)

            # Restore previous animation state if requested
            if restore_previous_state:
                self._restore_state(saved_state)
        except Exception as e:
            self.logger.warning(f"blink_error error: {e}")

    def flash_blue_green(self, start_time: float) -> None:
        """
        Flash blue and green alternately.
        Used for Safe Mode indicator and update installation.

        DEPRECATED: Use indicate_installing() or indicate_safe_mode() for new code.
        This method is kept for backward compatibility.

        Args:
            start_time: Monotonic timestamp when flashing started (for compatibility, ignored)

        Note: Animation is now scheduler-driven. No manual updates needed.
        """
        try:
            # If not already in flashing mode, start it
            if self._mode != self._MODE_FLASHING:
                self._indicate_updating()
            # Scheduler automatically updates animation at 25Hz
        except Exception as e:
            self.logger.warning(f"flash_blue_green error: {e}")

    def manual_tick(self) -> None:
        """
        Advance animation frame manually when scheduler isn't running yet.
        Used during early boot/update installation before the async scheduler starts.
        """
        now = time.monotonic()
        if now - self._last_manual_tick < self._manual_tick_interval:
            return
        self._last_manual_tick = now
        try:
            self._advance_frame()
        except Exception as e:
            self.logger.debug(f"manual_tick error: {e}")
