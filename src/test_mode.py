"""
Test Mode - Auto-run test harness for on-device testing.

When /TESTMODE flag file exists, the device boots into test mode instead of
normal operation. Tests are run automatically with visual LED feedback.

LED Feedback:
- Green pulsing: Tests running
- Solid green: All tests passed
- Solid red: Some tests failed

After tests complete, user can select next mode:
- Single press: Normal mode
- 3s hold: Setup mode
- 10s hold: Safe mode
"""

import os
import sys
import traceback

from input_manager import ButtonEvent, InputManager
from logging_helper import configure_logging, logger
from scheduler import Scheduler

TEST_LOG = logger("wicid.test_mode")


def is_enabled():
    """
    Check if test mode is enabled via flag file.

    Returns:
        bool: True if /TESTMODE file exists, False otherwise
    """
    try:
        with open("/TESTMODE"):
            return True
    except OSError:
        return False


async def run_tests_and_await_action(pixel):
    """
    Run all tests with LED feedback, then wait for user action.

    This function:
    1. Displays test mode banner
    2. Starts green pulsing LED
    3. Runs all tests from tests/run_tests.py
    4. Shows solid green (pass) or solid red (fail)
    5. Waits for button press to select next mode

    Args:
        pixel: PixelController instance

    Returns:
        str: Next mode to enter - 'normal', 'setup', or 'safe'
    """
    input_mgr = InputManager.instance()
    TEST_LOG.info("Test mode enabled - running tests")

    # Save original log level from environment
    original_log_level = os.getenv("LOG_LEVEL", "INFO")

    # Configure TESTING log level to suppress verbose output during tests
    configure_logging("TESTING")

    # Display banner
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("TEST MODE AUTO-RUN")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("Waiting 8 seconds for REPL connection...")
    TEST_LOG.testing("=" * 70 + "\n")

    # Start pulsing green LED and wait for REPL connection
    pixel._start_pulsing(
        color=(0, 255, 0),  # Green
        min_b=0.2,
        max_b=0.8,
        start_brightness=0.5,
    )
    # Extended delay in Test Mode to allow time for terminal connection
    await Scheduler.sleep(8)

    # Show test mode message
    TEST_LOG.testing("TEST MODE: Starting test suite...")
    TEST_LOG.testing("=" * 70 + "\n")

    # Run tests and capture result
    test_passed = False
    try:
        # Add tests directory to path
        if "/tests" not in sys.path:
            sys.path.insert(0, "/tests")

        # Import and run test runner
        from run_tests import run_all_tests

        # Run tests (scheduler automatically handles LED animation at 25Hz)
        result = run_all_tests(verbosity=2, tick_callback=None)

        # Check if all tests passed
        test_passed = result.wasSuccessful()

    except ImportError as e:
        TEST_LOG.error(f"Failed to import test runner: {e}", exc_info=True)
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("!!! IMPORT ERROR")
        TEST_LOG.testing("=" * 70)
        TEST_LOG.testing(f"Error: {e}")
        TEST_LOG.testing("\nTraceback:")
        traceback_lines = []
        try:
            traceback_lines = traceback.format_exception(type(e), e, e.__traceback__)
        except Exception:
            # Fallback for CircuitPython which might not have __traceback__
            try:
                traceback_lines = traceback.format_exception(type(e), e, sys.exc_info()[2])
            except Exception:
                traceback_lines = [str(e)]
        for line in traceback_lines:
            TEST_LOG.testing(line.rstrip())
        TEST_LOG.testing("=" * 70 + "\n")
        test_passed = False
    except Exception as e:
        TEST_LOG.error(f"Test execution failed: {e}", exc_info=True)
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("!!! TEST RUNNER ERROR")
        TEST_LOG.testing("=" * 70)
        TEST_LOG.testing(f"Error: {e}")
        TEST_LOG.testing("\nTraceback:")
        traceback_lines = []
        try:
            traceback_lines = traceback.format_exception(type(e), e, e.__traceback__)
        except Exception:
            # Fallback for CircuitPython which might not have __traceback__
            try:
                traceback_lines = traceback.format_exception(type(e), e, sys.exc_info()[2])
            except Exception:
                traceback_lines = [str(e)]
        for line in traceback_lines:
            TEST_LOG.testing(line.rstrip())
        TEST_LOG.testing("=" * 70 + "\n")
        test_passed = False

    # Flash LED based on test result
    if test_passed:
        TEST_LOG.info("All tests passed")
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("ALL TESTS PASSED")
        TEST_LOG.testing("=" * 70 + "\n")
        # Blink green to indicate success
        await pixel.blink_success(times=5, on_time=0.3, off_time=0.2, restore_previous_state=False)
        # Set solid green while waiting for button
        pixel.set_color((0, 255, 0))
    else:
        TEST_LOG.warning("Some tests failed")
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("SOME TESTS FAILED")
        TEST_LOG.testing("=" * 70 + "\n")
        # Blink red to indicate failure
        await pixel.blink_error(times=5, on_time=0.3, off_time=0.2, restore_previous_state=False)
        # Set solid red while waiting for button
        pixel.set_color((255, 0, 0))

    # Wait for button press to determine next mode
    TEST_LOG.testing("Press button to select mode...")
    TEST_LOG.testing("  - Single press: Normal mode")
    TEST_LOG.testing("  - Hold 3s: Setup mode")
    TEST_LOG.testing("  - Hold 10s: Safe mode\n")

    # Reinitialize InputManager in case tests shut it down
    # This ensures button is responsive after test completion
    input_mgr = InputManager.instance()

    # Restore original log level before exiting
    configure_logging(original_log_level)

    decision = _ButtonDecision(input_mgr)
    try:
        choice = await decision.wait()
    finally:
        decision.cleanup()

    if choice == "safe":
        TEST_LOG.info("10s+ button hold detected - entering Safe Mode")
        return "safe"
    if choice == "setup":
        TEST_LOG.info("3s+ button hold detected - entering Setup Mode")
        return "setup"

    TEST_LOG.info("Short button press detected - entering Normal Mode")
    return "normal"


class _ButtonDecision:
    """Helper that maps InputManager callbacks to mode decisions."""

    def __init__(self, input_mgr):
        self._input_mgr = input_mgr
        self._choice = None
        self._callbacks = [
            (ButtonEvent.SINGLE_CLICK, self._on_normal),
            (ButtonEvent.SETUP_MODE, self._on_setup),
            (ButtonEvent.SAFE_MODE, self._on_safe),
        ]
        for event, callback in self._callbacks:
            self._input_mgr.register_callback(event, callback)

    def cleanup(self):
        for event, callback in self._callbacks:
            self._input_mgr.unregister_callback(event, callback)

    def _set_choice(self, choice):
        if self._choice is None:
            self._choice = choice

    def _on_normal(self, event):
        self._set_choice("normal")

    def _on_setup(self, event):
        self._set_choice("setup")

    def _on_safe(self, event):
        self._set_choice("safe")

    async def wait(self):
        while self._choice is None:
            await Scheduler.sleep(0.05)
        return self._choice
