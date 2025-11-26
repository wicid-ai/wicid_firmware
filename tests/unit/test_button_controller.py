"""
Unit tests for ButtonController (hardware abstraction layer).

ButtonController relies on DigitalInOut, so these tests inject a mock
DigitalInOut implementation to avoid requiring real hardware.

See tests.unit for instructions on running tests.
"""

# Import from unit package - path setup happens automatically
from controllers.button_controller import ButtonController
from core.logging_helper import logger
from tests.hardware_mocks import MockDigitalInOut
from tests.test_helpers import create_mock_button_pin
from tests.unit import TestCase


class TestButtonControllerBasic(TestCase):
    """Basic ButtonController functionality tests using mock Pin."""

    def setUp(self) -> None:
        """Set up each test."""
        self.logger = logger("test.button_controller")
        self.mock_pin = create_mock_button_pin(pin_number=42)
        self._controller_kwargs = {
            "button_pin": self.mock_pin,
            "input_factory": lambda pin: MockDigitalInOut(pin),
        }

    def tearDown(self) -> None:
        """Clean up after each test."""
        # Individual tests are responsible for deinitializing controllers they create.
        pass

    def test_button_controller_init(self) -> None:
        """Verify ButtonController initializes with mock pin."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        self.assertIsNotNone(controller, "ButtonController created")
        self.assertEqual(controller.button_pin, self.mock_pin, "Pin matches mock")
        self.assertFalse(controller.is_pressed(), "Initial state is not pressed")

        controller.deinit()

    def test_button_controller_deinit(self) -> None:
        """Verify ButtonController cleanup works."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        # Should not raise exception
        controller.deinit()

        # Should be safe to call multiple times
        controller.deinit()

    def test_button_controller_properties(self) -> None:
        """Verify ButtonController properties are accessible."""
        controller = ButtonController(self.logger, **self._controller_kwargs)

        # Verify properties
        self.assertEqual(controller.button_pin, self.mock_pin, "button_pin property works")
        self.assertFalse(controller.is_pressed(), "is_pressed available")

        controller.deinit()

    def test_mock_pin_simulation(self) -> None:
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

    def test_button_controller_with_simulated_input(self) -> None:
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
