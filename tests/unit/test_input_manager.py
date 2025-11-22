"""
Unit tests for the InputManager (button input subsystem).

InputManager is a HIGH-LEVEL component that orchestrates button event handling.
These tests use MOCK hardware to avoid resource conflicts and enable deterministic testing.

Tests verify:
- InputManager singleton pattern
- Callback registration/unregistration
- Event firing
- Button state tracking

Run via REPL:
    >>> import tests
    >>> tests.run_unit()

Or run specific test class:
    >>> from tests.unit.test_input_manager import TestInputManagerBasic
    >>> import unittest
    >>> unittest.main(module='tests.unit.test_input_manager', exit=False)
"""

import sys

# Add root to path for imports (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Add tests directory to path for test helpers
if "/tests" not in sys.path:
    sys.path.insert(0, "/tests")

# Import unittest framework
from unittest import TestCase

from app_typing import Any
from hardware_mocks import MockButtonController
from input_manager import ButtonEvent, InputManager
from test_helpers import create_mock_button_pin
from utils import suppress


class TestInputManagerBasic(TestCase):
    """Basic InputManager functionality tests using mock hardware."""

    test_button_pin: Any
    controller_factory: Any

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class - shutdown any existing InputManager."""
        # Shut down any existing InputManager instance to free resources
        # This is safe because we use the public API (accessing _instance is acceptable
        # for test setup only, as it's part of the singleton pattern interface)
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

        # Use mock pin - no hardware conflicts, deterministic testing
        cls.test_button_pin = create_mock_button_pin(pin_number=99)
        cls.controller_factory = MockButtonController

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up after tests."""
        # Shutdown InputManager to release the pin
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

    def test_input_manager_singleton(self) -> None:
        """Verify InputManager is a singleton."""
        mgr1 = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )
        mgr2 = InputManager.instance()

        self.assertIs(mgr1, mgr2, "InputManager.instance() returns same object")

        # Direct instantiation also returns singleton
        mgr3 = InputManager()
        self.assertIs(mgr1, mgr3, "InputManager() returns singleton instance")

    def test_event_types_exist(self) -> None:
        """Verify all button event types are defined."""
        event_types = [
            ButtonEvent.PRESS,
            ButtonEvent.RELEASE,
            ButtonEvent.SINGLE_CLICK,
            ButtonEvent.DOUBLE_CLICK,
            ButtonEvent.TRIPLE_CLICK,
            ButtonEvent.LONG_PRESS,
            ButtonEvent.SETUP_MODE,
            ButtonEvent.SAFE_MODE,
        ]

        for event in event_types:
            self.assertIsNotNone(event, f"Event type {event} is defined")

    def test_input_manager_initialized(self) -> None:
        """Verify InputManager initializes correctly via public API."""
        mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )

        # Verify we can register callbacks (proves callback system works)
        def test_callback(event: Any) -> None:
            pass

        # Should be able to register callbacks for all event types
        for event_type in [
            ButtonEvent.PRESS,
            ButtonEvent.RELEASE,
            ButtonEvent.SINGLE_CLICK,
            ButtonEvent.DOUBLE_CLICK,
            ButtonEvent.TRIPLE_CLICK,
            ButtonEvent.LONG_PRESS,
            ButtonEvent.SETUP_MODE,
            ButtonEvent.SAFE_MODE,
        ]:
            # Should not raise - proves callback registry is initialized
            mgr.register_callback(event_type, test_callback)
            mgr.unregister_callback(event_type, test_callback)

        # Verify button state methods work
        self.assertIsInstance(mgr.is_pressed(), bool, "is_pressed() returns bool")
        self.assertIsInstance(mgr.get_raw_value(), bool, "get_raw_value() returns bool")


class TestInputManagerCallbacks(TestCase):
    """Tests for callback registration and management using mock hardware."""

    test_button_pin: Any
    controller_factory: Any

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class - shutdown any existing InputManager."""
        # Shut down any existing InputManager instance to free resources
        # This is safe because we use the public API (accessing _instance is acceptable
        # for test setup only, as it's part of the singleton pattern interface)
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

        # Use mock pin - no hardware conflicts, deterministic testing
        cls.test_button_pin = create_mock_button_pin(pin_number=99)
        cls.controller_factory = MockButtonController

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up after tests."""
        # Shutdown InputManager to release the pin
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

    def setUp(self) -> None:
        """Setup test state."""
        self.mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )
        self.callback_invoked = False
        self.callback_event = None

    def tearDown(self) -> None:
        """Clean up any registered callbacks."""
        # Note: In real device testing, callbacks persist across tests
        # Tests should be independent
        pass

    def test_register_callback(self) -> None:
        """Verify callback registration."""

        def my_callback(event: Any) -> None:
            pass

        initial_count = len(self.mgr._callbacks[ButtonEvent.PRESS])

        self.mgr.register_callback(ButtonEvent.PRESS, my_callback)

        # Should have one more callback
        self.assertEqual(len(self.mgr._callbacks[ButtonEvent.PRESS]), initial_count + 1, "Callback added to registry")

        # Clean up
        self.mgr.unregister_callback(ButtonEvent.PRESS, my_callback)

    def test_unregister_callback(self) -> None:
        """Verify callback unregistration."""

        def my_callback(event: Any) -> None:
            pass

        # Register then unregister
        self.mgr.register_callback(ButtonEvent.PRESS, my_callback)
        result = self.mgr.unregister_callback(ButtonEvent.PRESS, my_callback)

        self.assertTrue(result, "Unregister returns True")

        # Unregistering again should fail
        result = self.mgr.unregister_callback(ButtonEvent.PRESS, my_callback)
        self.assertFalse(result, "Second unregister returns False")

    def test_unregister_nonexistent_callback(self) -> None:
        """Verify unregistering non-existent callback fails gracefully."""

        def my_callback(event: Any) -> None:
            pass

        result = self.mgr.unregister_callback(ButtonEvent.PRESS, my_callback)
        self.assertFalse(result, "Unregister of non-existent callback returns False")

    def test_register_unknown_event_type(self) -> None:
        """Verify registering unknown event type fails gracefully."""

        def my_callback(event: Any) -> None:
            pass

        # Try to register with invalid event type (should log warning but not crash)
        class FakeEvent:
            pass

        fake_event = FakeEvent()

        # This should not raise an exception
        try:
            self.mgr.register_callback(fake_event, my_callback)
        except Exception as e:
            self.fail(f"register_callback raised exception for unknown event: {e}")


class TestInputManagerEventFiring(TestCase):
    """Tests for event firing mechanism using mock hardware."""

    test_button_pin: Any
    controller_factory: Any

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class - shutdown any existing InputManager."""
        # Shut down any existing InputManager instance to free resources
        # This is safe because we use the public API (accessing _instance is acceptable
        # for test setup only, as it's part of the singleton pattern interface)
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

        # Use mock pin - no hardware conflicts, deterministic testing
        cls.test_button_pin = create_mock_button_pin(pin_number=99)
        cls.controller_factory = MockButtonController

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up after tests."""
        # Shutdown InputManager to release the pin
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

    def setUp(self) -> None:
        """Setup test state."""
        self.mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )
        self.callback_invoked = False
        self.callback_event = None

    def test_fire_event_invokes_callback(self) -> None:
        """Verify _fire_event invokes registered callbacks."""

        def my_callback(event: Any) -> None:
            self.callback_invoked = True
            self.callback_event = event

        # Register callback
        self.mgr.register_callback(ButtonEvent.PRESS, my_callback)

        # Fire event
        self.mgr._fire_event(ButtonEvent.PRESS)

        # Callback should have been invoked
        self.assertTrue(self.callback_invoked, "Callback was invoked")
        self.assertEqual(self.callback_event, ButtonEvent.PRESS, "Correct event passed")

        # Clean up
        self.mgr.unregister_callback(ButtonEvent.PRESS, my_callback)

    def test_fire_event_multiple_callbacks(self) -> None:
        """Verify _fire_event invokes all registered callbacks."""
        invocation_count = [0]

        def callback1(event: Any) -> None:
            invocation_count[0] += 1

        def callback2(event: Any) -> None:
            invocation_count[0] += 1

        def callback3(event: Any) -> None:
            invocation_count[0] += 1

        # Register multiple callbacks
        self.mgr.register_callback(ButtonEvent.RELEASE, callback1)
        self.mgr.register_callback(ButtonEvent.RELEASE, callback2)
        self.mgr.register_callback(ButtonEvent.RELEASE, callback3)

        # Fire event
        self.mgr._fire_event(ButtonEvent.RELEASE)

        # All callbacks should have been invoked
        self.assertEqual(invocation_count[0], 3, "All 3 callbacks invoked")

        # Clean up
        self.mgr.unregister_callback(ButtonEvent.RELEASE, callback1)
        self.mgr.unregister_callback(ButtonEvent.RELEASE, callback2)
        self.mgr.unregister_callback(ButtonEvent.RELEASE, callback3)

    def test_fire_event_exception_handling(self) -> None:
        """Verify exceptions in callbacks don't break event firing."""
        invocation_count = [0]

        def bad_callback(event: Any) -> None:
            invocation_count[0] += 1
            raise RuntimeError("Callback error")

        def good_callback(event: Any) -> None:
            invocation_count[0] += 1

        # Register callbacks (bad one first)
        self.mgr.register_callback(ButtonEvent.SINGLE_CLICK, bad_callback)
        self.mgr.register_callback(ButtonEvent.SINGLE_CLICK, good_callback)

        # Fire event - should not raise exception
        try:
            self.mgr._fire_event(ButtonEvent.SINGLE_CLICK)
        except Exception as e:
            self.fail(f"_fire_event raised exception despite error handling: {e}")

        # Both callbacks should have been invoked (error logged, not propagated)
        self.assertEqual(invocation_count[0], 2, "Both callbacks invoked despite error")

        # Clean up
        self.mgr.unregister_callback(ButtonEvent.SINGLE_CLICK, bad_callback)
        self.mgr.unregister_callback(ButtonEvent.SINGLE_CLICK, good_callback)


class TestInputManagerState(TestCase):
    """Tests for button state tracking using mock hardware."""

    test_button_pin: Any
    controller_factory: Any

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test class - shutdown any existing InputManager."""
        # Shut down any existing InputManager instance to free resources
        # This is safe because we use the public API (accessing _instance is acceptable
        # for test setup only, as it's part of the singleton pattern interface)
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

        # Use mock pin - no hardware conflicts, deterministic testing
        cls.test_button_pin = create_mock_button_pin(pin_number=99)
        cls.controller_factory = MockButtonController

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up after tests."""
        # Shutdown InputManager to release the pin
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

    def test_is_pressed_returns_bool(self) -> None:
        """Verify is_pressed returns boolean."""
        mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )

        result = mgr.is_pressed()
        self.assertIsInstance(result, bool, "is_pressed returns bool")

    def test_get_raw_value_returns_bool(self) -> None:
        """Verify get_raw_value returns boolean."""
        mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )

        result = mgr.get_raw_value()
        self.assertIsInstance(result, bool, "get_raw_value returns bool")

    def test_initial_state_not_pressed(self) -> None:
        """Verify button starts in not-pressed state."""
        mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )

        # Button should not be pressed at test start
        # Note: This assumes button is not being held during test
        is_pressed = mgr.is_pressed()
        raw_value = mgr.get_raw_value()

        # Both methods should return False when button is not pressed
        self.assertFalse(is_pressed, "Button not pressed initially")
        self.assertFalse(raw_value, "get_raw_value returns False (not pressed)")


class TestInputManagerHoldDetection(TestCase):
    """Tests for setup/safe hold signaling."""

    test_button_pin: Any
    controller_factory: Any

    @classmethod
    def setUpClass(cls) -> None:
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            with suppress(Exception):
                InputManager._instance.shutdown()

        cls.test_button_pin = create_mock_button_pin(pin_number=101)
        cls.controller_factory = MockButtonController

    def setUp(self) -> None:
        self.mgr = InputManager.instance(
            button_pin=self.test_button_pin,
            controller_factory=self.controller_factory,
        )
        self.controller: Any = self.mgr._controller

    def tearDown(self) -> None:
        with suppress(Exception):
            self.mgr.shutdown()
        InputManager._instance = None

    def _run_monitor_with_time(self, timestamp: float) -> None:
        self.mgr._monitor_button_tick(now=timestamp)

    def test_setup_hold_fires_before_release(self) -> None:
        """Setup event fires during press and not on release."""
        events = []
        pressed_states = []

        def on_setup(event: Any) -> None:
            events.append(event)
            pressed_states.append(self.mgr.is_pressed())

        self.mgr.register_callback(ButtonEvent.SETUP_MODE, on_setup)

        self.controller.simulate_press()
        self._run_monitor_with_time(0.0)
        self._run_monitor_with_time(3.2)

        self.assertEqual(events, [ButtonEvent.SETUP_MODE])
        self.assertTrue(pressed_states[0], "Hold event should fire while button pressed")

        self.controller.simulate_release()
        self._run_monitor_with_time(3.4)
        self.assertEqual(len(events), 1, "Release should not fire a second setup event")

        self.mgr.unregister_callback(ButtonEvent.SETUP_MODE, on_setup)

    def test_safe_hold_overrides_setup(self) -> None:
        """Safe hold upgrades setup hold and does not duplicate on release."""
        events = []

        def on_setup(event: Any) -> None:
            events.append("setup")

        def on_safe(event: Any) -> None:
            events.append("safe")

        self.mgr.register_callback(ButtonEvent.SETUP_MODE, on_setup)
        self.mgr.register_callback(ButtonEvent.SAFE_MODE, on_safe)

        self.controller.simulate_press()
        self._run_monitor_with_time(0.0)
        self._run_monitor_with_time(3.5)
        self._run_monitor_with_time(10.5)

        self.assertEqual(events, ["setup", "safe"], "Safe should override setup once per hold")

        self.controller.simulate_release()
        self._run_monitor_with_time(11.0)
        self.assertEqual(len(events), 2, "Release should not emit additional hold events")

        self.mgr.unregister_callback(ButtonEvent.SETUP_MODE, on_setup)
        self.mgr.unregister_callback(ButtonEvent.SAFE_MODE, on_safe)


# Entry point for running tests
if __name__ == "__main__":
    import unittest

    unittest.main()
