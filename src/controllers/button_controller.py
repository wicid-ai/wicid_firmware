"""
ButtonController - hardware abstraction for the physical button.

Provides a simple polling interface that is scheduler-friendly
and does not spin up its own asyncio tasks.
"""

import board  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
import digitalio  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

from core.app_typing import Any


class ButtonController:
    """
    Hardware abstraction for the physical button.

    Wraps `digitalio.DigitalInOut` so InputManager can poll the button at a high rate
    without any background asyncio helpers that might interfere with the scheduler.
    """

    def __init__(self, logger: Any, button_pin: Any = None, input_factory: Any = None) -> None:
        """
        Initialize ButtonController.

        Args:
            logger: Logger instance for logging
            button_pin: Optional Pin object. If None, uses board.BUTTON
            input_factory: Optional callable used to construct a DigitalInOut-like
                object. Tests can inject mocks here to avoid real hardware access.
        """
        self._logger = logger
        self._input_factory = input_factory or digitalio.DigitalInOut

        self._button_pin = button_pin if button_pin is not None else board.BUTTON
        self._digital_in = self._input_factory(self._button_pin)

        # Configure input with pull-up (button is active-low)
        try:
            # CircuitPython DigitalInOut
            self._digital_in.switch_to_input(pull=digitalio.Pull.UP)
        except AttributeError:
            # Fallback for mocks that expose direction/pull attributes directly
            # Using setattr to avoid vulture flagging these as unused attributes
            setattr(self._digital_in, "direction", digitalio.Direction.INPUT)  # noqa: B010
            setattr(self._digital_in, "pull", digitalio.Pull.UP)  # noqa: B010

    @property
    def button_pin(self) -> Any:
        """Return the raw Pin object."""
        return self._button_pin

    def is_pressed(self) -> bool:
        """
        Return True if the button is currently pressed.

        The physical button is wired as active-low.

        Returns:
            bool: True if button is pressed, False otherwise
        """
        try:
            return not bool(self._digital_in.value)
        except Exception as exc:
            self._logger.warning(f"Button read failed: {exc}")
            return False

    def deinit(self) -> None:
        """Deinitialize hardware resources."""
        try:
            if hasattr(self, "_digital_in") and self._digital_in is not None:
                self._digital_in.deinit()
        except Exception:
            # Best-effort cleanup; ignore hardware-specific errors
            pass
        finally:
            self._digital_in = None
