"""
Test helpers and mocks for WICID firmware tests.

Provides reusable mock objects for testing hardware-dependent components
in isolation without resource conflicts.

This module provides convenient factory functions and re-exports from
the integration_mocks module for on-device tests, or can be used in
unit tests on desktop.

Usage Examples:

1. Basic button simulation:
    >>> from test_helpers import create_mock_button_pin
    >>> mock_pin = create_mock_button_pin()
    >>> mock_pin.simulate_press()   # Simulate button press
    >>> mock_pin.simulate_release() # Simulate button release

2. Testing ButtonController:
    >>> from test_helpers import create_mock_button_pin
    >>> from button_controller import ButtonController
    >>> mock_pin = create_mock_button_pin()
    >>> controller = ButtonController(logger, button_pin=mock_pin)

3. Testing InputManager with mock async button:
    >>> from test_helpers import create_mock_async_button
    >>> from input_manager import InputManager
    >>> mock_button = create_mock_async_button()
    >>> # Use mock_button for direct testing without ButtonController

4. Simulating button events in tests:
    >>> mock_pin = create_mock_button_pin()
    >>> mock_pin.simulate_press()
    >>> # ... test code that checks for press detection ...
    >>> mock_pin.simulate_release()

5. Using MockAsyncButton directly:
    >>> from test_helpers import create_mock_async_button
    >>> button = create_mock_async_button()
    >>> button.simulate_press()
    >>> assert button.is_pressed()
"""

# Import comprehensive mocks from integration_mocks module
from core.app_typing import Any
from tests.integration.integration_mocks import MockAsyncButton, MockPin, MockPixel


def create_mock_button_pin(pin_number: int = 42, initial_value: bool = True) -> MockPin:
    """
    Factory function to create a mock button pin for testing.

    Args:
        pin_number: Optional pin number for identification (default: 42)
        initial_value: Initial pin state (default: True = not pressed)

    Returns:
        MockPin: Configured mock pin ready for use in tests

    Example:
        >>> from tests.test_helpers import create_mock_button_pin
        >>> mock_pin = create_mock_button_pin()
        >>> controller = ButtonController(logger, button_pin=mock_pin)
    """
    return MockPin(pin_number=pin_number, initial_value=initial_value)


def create_mock_async_button(pin: Any = None, value_when_pressed: bool = False) -> MockAsyncButton:
    """
    Factory function to create a mock async button for testing.

    Args:
        pin: Optional MockPin instance (created automatically if None)
        value_when_pressed: Pin value when button is pressed (default False for active-low)

    Returns:
        MockAsyncButton: Configured mock async button ready for use in tests

    Example:
        >>> from tests.test_helpers import create_mock_async_button
        >>> button = create_mock_async_button()
        >>> button.simulate_press()
        >>> assert button.is_pressed()
    """
    return MockAsyncButton(pin=pin, value_when_pressed=value_when_pressed)


def create_mock_pixel() -> MockPixel:
    """
    Factory function to create a mock pixel for testing.

    Returns:
        MockPixel: Configured mock pixel ready for use in tests

    Example:
        >>> from tests.test_helpers import create_mock_pixel
        >>> mock_pixel = create_mock_pixel()
        >>> controller = PixelController(pixel=mock_pixel)
        >>> controller.set_color((255, 0, 0))
        >>> assert mock_pixel.color == (255, 0, 0)
    """
    return MockPixel()


def create_file_path_redirector(path_map: dict[str, str]) -> Any:
    """
    Create a mock for open() that redirects paths to test directories.

    This helper eliminates the need for # noqa: SIM115 comments by properly
    returning file objects that can be used in context managers.

    Args:
        path_map: Dictionary mapping device paths to test directory paths
                  Example: {"/settings.toml": "/tmp/test/settings.toml"}

    Returns:
        Callable that can be used as side_effect for patching open()

    Example:
        >>> path_map = {"/settings.toml": "/tmp/test/settings.toml"}
        >>> mock_open = create_file_path_redirector(path_map)
        >>> with patch("builtins.open", side_effect=mock_open):
        ...     # Code under test will read/write to test directory
        ...     pass
    """
    import builtins

    real_open = builtins.open

    def mock_open(path: str, mode: str = "r") -> Any:
        # Redirect path if it's in the map
        actual_path = path_map.get(path, path)
        return real_open(actual_path, mode)

    return mock_open
