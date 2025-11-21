"""
Unit tests for ButtonController (hardware abstraction layer).

ButtonController relies on DigitalInOut, so these tests inject a mock
DigitalInOut implementation to avoid requiring real hardware.

Run via REPL:
    >>> import tests
    >>> tests.run_unit()

Or run specific test class:
    >>> from tests.unit.test_button_controller import TestButtonControllerBasic
    >>> import unittest
    >>> unittest.main(module='tests.unit.test_button_controller', exit=False)
"""

import sys

# Add root to path for imports (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Add tests directory to path for test helpers
if "/tests" not in sys.path:
    sys.path.insert(0, "/tests")

# Import unittest framework
from unittest import TestCase

from button_controller import ButtonController
from hardware_mocks import MockDigitalInOut
from logging_helper import logger
from test_helpers import create_mock_button_pin


class TestButtonControllerBasic(TestCase):
    """Basic ButtonController functionality tests using mock Pin."""

    def setUp(self):
        """Set up each test."""
        self.logger = logger("test.button_controller")
        self.mock_pin = create_mock_button_pin(pin_number=42)
        self._controller_kwargs = {
            "button_pin": self.mock_pin,
            "input_factory": lambda pin: MockDigitalInOut(pin),
        }

    def tearDown(self):
        """Clean up after each test."""
        # Clean up any controller instances
        if hasattr(self, "controller") and self.controller is not None:
            try:
                self.controller.deinit()
            except Exception:
                pass

    def test_button_controller_init(self):
        """Verify ButtonController initializes with mock pin."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        self.assertIsNotNone(controller, "ButtonController created")
        self.assertEqual(controller.button_pin, self.mock_pin, "Pin matches mock")
        self.assertFalse(controller.is_pressed(), "Initial state is not pressed")

        controller.deinit()

    def test_button_controller_deinit(self):
        """Verify ButtonController cleanup works."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        # Should not raise exception
        controller.deinit()

        # Should be safe to call multiple times
        controller.deinit()

    def test_button_controller_properties(self):
        """Verify ButtonController properties are accessible."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        # Verify properties
        self.assertEqual(controller.button_pin, self.mock_pin, "button_pin property works")
        self.assertFalse(controller.is_pressed(), "is_pressed available")

        controller.deinit()

    def test_mock_pin_simulation(self):
        """Verify mock pin can simulate button press/release."""
        # Test initial state (not pressed)
        self.assertTrue(self.mock_pin.value, "Initial state is high (not pressed)")

        # Simulate button press
        self.mock_pin.simulate_press()
        self.assertFalse(self.mock_pin.value, "Press sets value to False (active low)")

        # Simulate button release
        self.mock_pin.simulate_release()
        self.assertTrue(self.mock_pin.value, "Release sets value to True")

        # Test direct value manipulation
        self.mock_pin.value = False
        self.assertFalse(self.mock_pin.value, "Direct value assignment works")

    def test_button_controller_with_simulated_input(self):
        """Verify ButtonController can be created with mock pin."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        # Verify controller was created successfully
        self.assertIsNotNone(controller, "Controller created with mock pin")
        self.assertEqual(controller.button_pin, self.mock_pin, "Controller uses mock pin")

        # Simulate button press by toggling underlying digital input value
        controller._digital_in.simulate_value(False)
        self.assertTrue(controller.is_pressed(), "Controller reports pressed state")

        controller._digital_in.simulate_value(True)
        self.assertFalse(controller.is_pressed(), "Controller reports released state")

        controller.deinit()
