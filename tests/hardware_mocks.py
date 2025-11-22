"""
Hardware mocks for WICID firmware tests.

Provides comprehensive mocks that simulate CircuitPython hardware behavior,
including async_button compatibility, event simulation, and hardware state tracking.

Design Goals:
- Full compatibility with async_button.Button library
- Support for both polling (is_pressed) and async event handling
- Realistic state transitions and timing
- Easy test setup with sensible defaults

Usage:
    >>> from hardware_mocks import MockAsyncButton
    >>> button = MockAsyncButton()
    >>> button.simulate_press()  # Simulate hardware press
    >>> assert button.is_pressed()
    >>> await button.wait_for_press()  # Async event handling
"""

import time

from app_typing import Any, Callable, Optional


class MockPin:
    """
    Mock Pin object compatible with async_button.Button.

    Simulates a GPIO pin with value changes, pull configuration,
    and listener notifications for async event handling.

    This mock is designed to work seamlessly with async_button.Button,
    which requires a Pin object (not DigitalInOut).

    Features:
    - Value property for state simulation
    - Pull enum for configuration compatibility
    - Listener support for async event detection
    - simulate_press/release helpers for testing

    Example:
        >>> pin = MockPin(pin_number=42)
        >>> pin.simulate_press()  # Set to active-low pressed state
        >>> assert pin.value == False  # Active-low: False = pressed
        >>> pin.simulate_release()
        >>> assert pin.value == True   # Active-low: True = not pressed
    """

    # Mock Pin.Pull enum matching CircuitPython's digitalio.Pull
    class Pull:
        """Mock Pull configuration enum."""

        UP = 1
        DOWN = 2

    def __init__(self, pin_number: int | None = None, initial_value: bool = True) -> None:
        """
        Initialize mock pin.

        Args:
            pin_number: Optional pin number for identification/debugging
            initial_value: Initial pin value (default True = high/not pressed for active-low button)
        """
        self.pin_number = pin_number
        self._value = initial_value
        self._listeners: list[Callable[[bool], None]] = []  # For async event simulation

    @property
    def value(self) -> bool:
        """
        Get pin value.

        Returns:
            bool: True = high/not pressed (for active-low button),
                  False = low/pressed (for active-low button)
        """
        return self._value

    @value.setter
    def value(self, val: bool) -> None:
        """
        Set pin value and notify listeners.

        This simulates hardware state changes and triggers
        async event listeners (used by async_button.Button).

        Args:
            val: New pin value (bool)
        """
        old_value = self._value
        self._value = val

        # Notify listeners of value change (for async_button event detection)
        if old_value != val:
            for listener in self._listeners:
                listener(val)

    def simulate_press(self) -> None:
        """
        Simulate button press (set value to False for active-low button).

        Convenience method for tests. Triggers async event listeners.
        """
        self.value = False

    def simulate_release(self) -> None:
        """
        Simulate button release (set value to True for active-low button).

        Convenience method for tests. Triggers async event listeners.
        """
        self.value = True

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        """
        Add a listener for value changes.

        Used by async_button.Button to detect hardware events.

        Args:
            callback: Function to call when value changes, signature: callback(new_value)
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[bool], None]) -> None:
        """
        Remove a value change listener.

        Args:
            callback: Function to remove from listeners
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def __repr__(self) -> str:
        """String representation for debugging."""
        state = "LOW" if self._value is False else "HIGH"
        if self.pin_number is not None:
            return f"MockPin(pin={self.pin_number}, value={state})"
        return f"MockPin(value={state})"


class MockDigitalInOut:
    """
    Minimal DigitalInOut-compatible mock for ButtonController tests.

    Provides the subset of the API needed by ButtonController:
    - switch_to_input / direction / pull attributes
    - value property (active-high)
    - deinit method
    """

    def __init__(self, pin: Any) -> None:
        self.pin = pin
        self.value = True  # Default to not pressed (active-low button)
        self.direction: Optional[str] = None
        self.pull: Any = None

    def switch_to_input(self, pull: Any = None) -> None:
        self.direction = "input"
        self.pull = pull

    def deinit(self) -> None:
        """Release mock resources (no-op)."""
        pass

    def simulate_value(self, value: bool) -> None:
        """Helper for tests to change the observed value."""
        self.value = value


class MockAsyncButton:
    """
    Mock async_button.Button with realistic event simulation.

    This mock provides a complete async_button.Button-compatible interface
    with full support for both polling (is_pressed) and async event handling
    (wait_for_press, wait_for_release, wait_for_click).

    Supports:
    - Synchronous state checking (is_pressed)
    - Async event waiting (wait_for_press, wait_for_release, wait_for_click)
    - Click detection (single, double, triple, long)
    - Realistic timing for click duration tracking
    - Event history for test assertions

    This is the PRIMARY mock for button testing. Use this instead of
    creating async_button.Button with MockPin for more predictable
    test behavior.

    Example:
        >>> button = MockAsyncButton()
        >>> button.simulate_press()
        >>> assert button.is_pressed()
        >>> button.simulate_release()
        >>> assert not button.is_pressed()
        >>> # Async usage:
        >>> await button.simulate_press_async()
        >>> await button.wait_for_press()  # Would trigger immediately
    """

    def __init__(self, pin: MockPin | None = None, value_when_pressed: bool = False) -> None:
        """
        Initialize mock async button.

        Args:
            pin: Optional MockPin instance (created automatically if None)
            value_when_pressed: Pin value when button is pressed (default False for active-low)
        """
        self._pin = pin or MockPin()
        self._value_when_pressed = value_when_pressed
        self._pressed = False
        self._event_history: list[
            tuple[str, float] | tuple[str, float, float | None]
        ] = []  # Track events for test assertions
        self._press_start_time: float | None = None  # Track press duration

        # Event queues for async waiting (simplified for testing)
        self._press_events: list[float] = []
        self._release_events: list[float] = []
        self._click_events: list[tuple[str, float]] = []

    def is_pressed(self) -> bool:
        """
        Check if button is currently pressed.

        This is the primary polling interface used by InputManager.

        Returns:
            bool: True if button is pressed, False otherwise
        """
        return self._pressed

    def simulate_press(self) -> None:
        """
        Simulate a button press event.

        Updates internal state and records event for async waiting.
        Use this in tests to simulate hardware button presses.
        """
        if not self._pressed:
            self._pressed = True
            self._press_start_time = time.monotonic()
            self._pin.value = self._value_when_pressed
            self._event_history.append(("press", time.monotonic()))
            self._press_events.append(time.monotonic())

    def simulate_release(self) -> None:
        """
        Simulate a button release event.

        Updates internal state, calculates press duration, and records
        event for async waiting.
        """
        if self._pressed:
            self._pressed = False
            duration = None
            if self._press_start_time is not None:
                duration = time.monotonic() - self._press_start_time
            self._pin.value = not self._value_when_pressed
            self._event_history.append(("release", time.monotonic(), duration))
            self._release_events.append(time.monotonic())

            # Determine click type based on duration
            if duration is not None:
                if duration < 0.05:
                    click_type = "short"
                elif duration >= 2.0:
                    click_type = "long"
                else:
                    click_type = "single"
                self._click_events.append((click_type, time.monotonic()))

    def simulate_click(self, duration: float = 0.1) -> None:
        """
        Simulate a complete click (press + release).

        Args:
            duration: How long to hold the button (seconds)
        """
        self.simulate_press()
        time.sleep(duration)
        self.simulate_release()

    async def wait_for_press(self) -> float | None:
        """
        Async wait for button press event.

        Compatible with async_button.Button interface.
        In tests, this returns immediately if a press event is queued.
        """
        # Simplified for testing: return immediately if pressed
        if self._press_events:
            return self._press_events.pop(0)
        # In real async context, would await event
        return None

    async def wait_for_release(self) -> float | None:
        """
        Async wait for button release event.

        Compatible with async_button.Button interface.
        """
        if self._release_events:
            return self._release_events.pop(0)
        return None

    async def wait_for_click(self, click_type: str | None = None) -> float | None:
        """
        Async wait for button click event.

        Args:
            click_type: Optional filter ('single', 'double', 'long', etc.)

        Compatible with async_button.Button interface.
        """
        if self._click_events:
            event_type, timestamp = self._click_events.pop(0)
            if click_type is None or event_type == click_type:
                return timestamp
        return None

    def get_event_history(self) -> list[tuple[str, float] | tuple[str, float, float | None]]:
        """
        Get history of button events for test assertions.

        Returns:
            list: List of (event_type, timestamp, ...) tuples

        Example:
            >>> button = MockAsyncButton()
            >>> button.simulate_click()
            >>> history = button.get_event_history()
            >>> assert ('press', ...) in history
            >>> assert ('release', ..., ...) in history
        """
        return self._event_history.copy()

    def clear_event_history(self) -> None:
        """Clear event history and queues."""
        self._event_history.clear()
        self._press_events.clear()
        self._release_events.clear()
        self._click_events.clear()

    def deinit(self) -> None:
        """
        Deinitialize button (no-op for mock).

        Provided for API compatibility with async_button.Button.
        """
        self._event_history.append(("deinit", time.monotonic()))

    @property
    def pin(self) -> MockPin:
        """Get the underlying pin object."""
        return self._pin

    def __repr__(self) -> str:
        """String representation for debugging."""
        state = "PRESSED" if self._pressed else "RELEASED"
        return f"MockAsyncButton(state={state}, events={len(self._event_history)})"


class MockPixel:
    """
    Mock NeoPixel/DotStar LED for testing display-dependent components.

    Simulates a single RGB LED compatible with PixelController and other
    LED/display code. Tracks color changes without requiring real hardware.

    This allows testing PixelController and display-dependent modes without
    hardware conflicts or visual dependencies.

    Features:
    - RGB color tracking
    - Brightness control
    - auto_write mode simulation
    - Operation history for test assertions
    - NeoPixel-compatible indexing API

    Example:
        >>> pixel = MockPixel()
        >>> pixel.fill((255, 0, 0))  # Red
        >>> assert pixel.color == (255, 0, 0)
        >>> pixel.brightness = 0.5
        >>> history = pixel.get_history()
        >>> assert ('fill', (255, 0, 0)) in history
    """

    def __init__(self) -> None:
        """Initialize mock pixel."""
        self._color: Any = (0, 0, 0)  # RGB tuple, default to off - using Any to allow variable-length tuples
        self._brightness = 1.0  # 0.0 to 1.0
        self._auto_write = True
        self._pixel_history: list[tuple[str, Any]] = []  # Track color changes for test assertions

    @property
    def brightness(self) -> float:
        """Get brightness (0.0 to 1.0)."""
        return self._brightness

    @brightness.setter
    def brightness(self, value: float) -> None:
        """Set brightness (0.0 to 1.0)."""
        self._brightness = max(0.0, min(1.0, float(value)))
        self._pixel_history.append(("brightness", self._brightness))

    @property
    def auto_write(self) -> bool:
        """Get auto_write state."""
        return self._auto_write

    @auto_write.setter
    def auto_write(self, value: bool) -> None:
        """Set auto_write state."""
        self._auto_write = bool(value)

    @property
    def color(self) -> tuple[int, int, int]:
        """Get current color as RGB tuple."""
        return self._color

    def __setitem__(self, index: int, color: tuple[int, int, int]) -> None:
        """
        Set pixel color by index (for NeoPixel-like API).

        Args:
            index: Pixel index (0 for single pixel)
            color: RGB tuple (r, g, b) where each value is 0-255
        """
        if index != 0:
            raise IndexError(f"Mock pixel only has index 0, got {index}")
        self._color = tuple(color)
        self._pixel_history.append(("set", self._color))

    def __getitem__(self, index: int) -> tuple[int, int, int]:
        """
        Get pixel color by index.

        Args:
            index: Pixel index (0 for single pixel)

        Returns:
            tuple: RGB color tuple
        """
        if index != 0:
            raise IndexError(f"Mock pixel only has index 0, got {index}")
        return self._color

    def fill(self, color: tuple[int, int, int]) -> None:
        """
        Fill all pixels with color (for NeoPixel-like API).

        Args:
            color: RGB tuple (r, g, b) where each value is 0-255
        """
        self._color = tuple(color)
        self._pixel_history.append(("fill", self._color))

    def show(self) -> None:
        """
        Update pixel display (no-op for mock, but tracks call).

        NeoPixels require explicit show() calls when auto_write is False.
        """
        self._pixel_history.append(("show", self._color))

    def deinit(self) -> None:
        """
        Deinitialize pixel (no-op for mock).

        Provided for API compatibility with real NeoPixel objects.
        """
        self._pixel_history.append(("deinit", None))

    def get_history(self) -> list[tuple[str, Any]]:
        """
        Get history of pixel operations for test assertions.

        Returns:
            list: List of (operation, value) tuples

        Example:
            >>> pixel = MockPixel()
            >>> pixel.fill((255, 0, 0))
            >>> pixel.brightness = 0.5
            >>> history = pixel.get_history()
            >>> assert ('fill', (255, 0, 0)) in history
            >>> assert ('brightness', 0.5) in history
        """
        return self._pixel_history.copy()

    def clear_history(self) -> None:
        """Clear operation history."""
        self._pixel_history.clear()

    def __repr__(self) -> str:
        """String representation for debugging."""
        r, g, b = self._color
        return f"MockPixel(color=({r}, {g}, {b}), brightness={self._brightness:.2f})"


class MockButtonController:
    """
    Mock ButtonController for testing without real hardware.

    Provides a scheduler-friendly polling interface that mirrors the production
    ButtonController without requiring CircuitPython Pin objects.
    """

    def __init__(self, logger: Any, button_pin: Any = None) -> None:
        """
        Initialize mock button controller.

        Args:
            logger: Logger instance (unused, kept for API compatibility)
            button_pin: Optional pin (stored for parity with real controller)
        """
        self._logger = logger
        self._button_pin = button_pin or MockPin()
        self._pressed = False

    @property
    def button_pin(self) -> Any:
        """Return the pin object."""
        return self._button_pin

    def is_pressed(self) -> bool:
        """Return simulated press state."""
        return self._pressed

    def simulate_press(self) -> None:
        """Simulate button press (convenience for tests)."""
        self._pressed = True

    def simulate_release(self) -> None:
        """Simulate button release (convenience for tests)."""
        self._pressed = False

    def simulate_click(self, duration: float = 0.1) -> None:
        """Simulate complete click (press->hold->release)."""
        self._pressed = True
        time.sleep(duration)
        self._pressed = False

    def deinit(self) -> None:
        """Deinitialize (no-op for mock)."""
        self._pressed = False
