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

# Import for serial input and button polling
import select
import sys
import traceback

from core.app_typing import Any
from core.logging_helper import configure_logging, logger
from core.scheduler import Scheduler

TEST_LOG = logger("wicid.test_mode")


def is_enabled() -> bool:
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


def _run_test_suite() -> tuple[bool, int]:
    """Run all tests and return success status and test count.

    Returns:
        tuple[bool, int]: (all_tests_passed, total_test_count)
    """
    test_passed = False
    test_count = 0

    try:
        # Add tests directory to path
        if "/tests" not in sys.path:
            sys.path.insert(0, "/tests")

        # Import and run test runner
        from run_tests import run_all_tests

        # Run tests (scheduler automatically handles LED animation at 25Hz)
        result = run_all_tests(verbosity=2, tick_callback=None)
        test_count = result.testsRun

        # Check if all tests passed
        test_passed = result.wasSuccessful()

    except ImportError as e:
        TEST_LOG.error(f"Failed to import test runner: {e}", exc_info=True)
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("!!! IMPORT ERROR")
        TEST_LOG.testing("=" * 70)
        TEST_LOG.testing(f"Error: {e}")
        TEST_LOG.testing("\nTraceback:")
        _print_exception(e)
        TEST_LOG.testing("=" * 70 + "\n")
    except Exception as e:
        TEST_LOG.error(f"Test execution failed: {e}", exc_info=True)
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("!!! TEST RUNNER ERROR")
        TEST_LOG.testing("=" * 70)
        TEST_LOG.testing(f"Error: {e}")
        TEST_LOG.testing("\nTraceback:")
        _print_exception(e)
        TEST_LOG.testing("=" * 70 + "\n")

    return test_passed, test_count


def _print_exception(e: Exception) -> None:
    """Print exception traceback in CircuitPython-compatible way."""
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


def _show_test_results(pixel: Any, test_passed: bool) -> None:
    """Show visual feedback for test results via LED (synchronous)."""
    if test_passed:
        TEST_LOG.info("All tests passed")
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("ALL TESTS PASSED")
        TEST_LOG.testing("=" * 70 + "\n")
        # Set solid green (no blinking to avoid scheduler interaction)
        pixel.set_color((0, 255, 0))
    else:
        TEST_LOG.warning("Some tests failed")
        TEST_LOG.testing("\n" + "=" * 70)
        TEST_LOG.testing("SOME TESTS FAILED")
        TEST_LOG.testing("=" * 70 + "\n")
        # Set solid red (no blinking to avoid scheduler interaction)
        pixel.set_color((255, 0, 0))


def _get_user_choice() -> str:
    """Get user's action choice via serial input or button press.

    Returns:
        str: User's choice ('1', '2', or '3')
    """
    import time

    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("SELECT NEXT ACTION")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("Options:")
    TEST_LOG.testing("  1 - Reboot to Normal Mode (removes TESTMODE flag) [DEFAULT]")
    TEST_LOG.testing("  2 - Reboot to Safe Mode")
    TEST_LOG.testing("  3 - Rerun Tests (keeps TESTMODE flag)")
    TEST_LOG.testing("")
    TEST_LOG.testing("Enter a number (1-3) OR press button for default (1)")
    TEST_LOG.testing("Timeout: 30 seconds")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("Choice: ")

    choice = "1"  # Default
    start_time = time.monotonic()
    timeout = 30

    # Try to get the button pin for polling (may fail if fully mocked)
    button_pin = None
    try:
        import board
        import digitalio

        button_pin = digitalio.DigitalInOut(board.BUTTON)
        button_pin.direction = digitalio.Direction.INPUT
        button_pin.pull = digitalio.Pull.UP
    except Exception:
        TEST_LOG.testing("(Button unavailable after tests, use serial input)")

    while time.monotonic() - start_time < timeout:
        # Check for serial input - read entire line to avoid leftover newlines
        if select.select([sys.stdin], [], [], 0.1)[0]:
            line = sys.stdin.readline().strip()
            if line in ["1", "2", "3"]:
                choice = line
                break
            if line:  # Only show error for non-empty input
                TEST_LOG.testing(f"Invalid choice '{line}', try again...")
            continue

        # Check button (if available)
        if button_pin and not button_pin.value:  # Button pressed (LOW when pressed)
            TEST_LOG.testing("Button pressed - selecting default (1)")
            choice = "1"
            break

        time.sleep(0.1)

    if time.monotonic() - start_time >= timeout:
        TEST_LOG.testing("\nTimeout - using default (1)")

    return choice


def _remove_directory_recursive(path: str) -> None:
    """Recursively remove a directory and all its contents."""
    from utils.utils import suppress

    try:
        items = os.listdir(path)
    except OSError:
        return

    for item in items:
        item_path = f"{path}/{item}"

        # Try to remove as file first
        with suppress(OSError):
            os.remove(item_path)
            continue

        # Must be a directory, recurse into it
        _remove_directory_recursive(item_path)

        # Remove the now-empty directory
        with suppress(OSError):
            os.rmdir(item_path)

    # Remove the directory itself
    with suppress(OSError):
        os.rmdir(path)


def _handle_user_action(choice: str) -> None:
    """Handle the user's action choice (never returns - always reboots).

    Args:
        choice: User's choice ('1', '2', or '3')
    """
    import time

    import microcontroller

    if choice == "2":
        TEST_LOG.info("User selected: Safe Mode")
        TEST_LOG.testing("\nTriggering Safe Mode...")
        time.sleep(1)
        from utils.utils import trigger_safe_mode

        trigger_safe_mode()
        # Never returns

    elif choice == "3":
        TEST_LOG.info("User selected: Rerun Tests")
        TEST_LOG.testing("\nRebooting to rerun tests (TESTMODE flag kept)...")
        time.sleep(1)
        os.sync()
        microcontroller.reset()
        # Never returns

    else:  # choice == "1" or default
        TEST_LOG.info("User selected: Normal Mode")
        TEST_LOG.testing("\nRemoving TESTMODE flag and tests directory, then rebooting...")
        time.sleep(1)

        # Remove TESTMODE flag
        try:
            os.remove("/TESTMODE")
            TEST_LOG.testing("✓ TESTMODE flag removed")
        except OSError:
            TEST_LOG.testing("(TESTMODE flag already removed)")

        # Remove tests directory recursively
        try:
            _remove_directory_recursive("/tests")
            TEST_LOG.testing("✓ Tests directory removed")
        except Exception as e:
            TEST_LOG.testing(f"Warning: Could not remove tests directory: {e}")

        os.sync()
        microcontroller.reset()
        # Never returns


async def run_tests_and_await_action(pixel: Any) -> str:
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

    # Run tests using helper function
    test_passed, _ = _run_test_suite()

    # Show visual feedback based on results
    _show_test_results(pixel, test_passed)

    # Get user's choice for next action via serial input OR button press
    # NOTE: Cannot use scheduler-based button monitoring because hardware is mocked after tests.
    # The scheduler's button monitoring task would crash when it tries to read the mocked pin.
    # Instead, we use:
    #   - Serial input (user is already connected via REPL to view test output)
    #   - Direct button polling (bypass scheduler, read pin synchronously)
    choice = _get_user_choice()

    # Restore original log level before exiting
    configure_logging(original_log_level)

    # Handle user action (never returns - always reboots)
    _handle_user_action(choice)

    # This line should never be reached
    return "normal"
