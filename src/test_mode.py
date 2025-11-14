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
import time
import sys
from logging_helper import get_logger, configure_logging
from utils import check_button_hold_duration, is_button_pressed

logger = get_logger('wicid.test_mode')


def is_enabled():
    """
    Check if test mode is enabled via flag file.

    Returns:
        bool: True if /TESTMODE file exists, False otherwise
    """
    try:
        with open("/TESTMODE", "r"):
            return True
    except OSError:
        return False


def run_tests_and_await_action(button, pixel):
    """
    Run all tests with LED feedback, then wait for user action.

    This function:
    1. Displays test mode banner
    2. Starts green pulsing LED
    3. Runs all tests from tests/run_tests.py
    4. Shows solid green (pass) or solid red (fail)
    5. Waits for button press to select next mode

    Args:
        button: digitalio.DigitalInOut button instance
        pixel: PixelController instance

    Returns:
        str: Next mode to enter - 'normal', 'setup', or 'safe'
    """
    logger.info("Test mode enabled - running tests")

    # Save original log level from environment
    original_log_level = os.getenv("LOG_LEVEL", "INFO")

    # Configure TESTING log level to suppress verbose output during tests
    configure_logging("TESTING")

    # Display banner
    logger.testing("\n" + "=" * 70)
    logger.testing("TEST MODE AUTO-RUN")
    logger.testing("=" * 70)
    logger.testing("Waiting 3 seconds for REPL connection...")
    logger.testing("=" * 70 + "\n")

    # Start pulsing green LED and wait for REPL connection
    pixel._start_pulsing(
        color=(0, 255, 0),  # Green
        min_b=0.2,
        max_b=0.8,
        step=0.05,
        interval=0.05,
        start_brightness=0.5,
    )
    time.sleep(3)

    # Show instructions after wait
    logger.testing("After completion, press button to select mode:")
    logger.testing("  - Single press: Normal mode")
    logger.testing("  - Hold 3s: Setup mode")
    logger.testing("  - Hold 10s: Safe mode")
    logger.testing("=" * 70 + "\n")

    # Run tests and capture result
    test_passed = False
    try:
        # Add tests directory to path
        if '/tests' not in sys.path:
            sys.path.insert(0, '/tests')

        # Import and run test runner
        from run_tests import run_all_tests

        # Run tests with pixel tick callback to keep LED pulsing
        result = run_all_tests(verbosity=2, tick_callback=pixel.tick)

        # Check if all tests passed
        test_passed = result.wasSuccessful()

    except ImportError as e:
        logger.error(f"Failed to import test runner: {e}", exc_info=True)
        logger.testing(f"\n!!! IMPORT ERROR: {e}")
        test_passed = False
    except Exception as e:
        logger.error(f"Test execution failed: {e}", exc_info=True)
        logger.testing(f"\n!!! TEST RUNNER ERROR: {e}")
        test_passed = False

    # Flash LED based on test result
    if test_passed:
        logger.info("All tests passed")
        logger.testing("\n" + "=" * 70)
        logger.testing("ALL TESTS PASSED")
        logger.testing("=" * 70 + "\n")
        # Blink green to indicate success
        pixel.blink_success(times=5, on_time=0.3, off_time=0.2)
        # Set solid green while waiting for button
        pixel.set_color((0, 255, 0))
    else:
        logger.warning("Some tests failed")
        logger.testing("\n" + "=" * 70)
        logger.testing("SOME TESTS FAILED")
        logger.testing("=" * 70 + "\n")
        # Blink red to indicate failure
        pixel.blink_error(times=5, on_time=0.3, off_time=0.2)
        # Set solid red while waiting for button
        pixel.set_color((255, 0, 0))

    # Wait for button press to determine next mode
    logger.testing("Press button to select mode...")
    logger.testing("  - Single press: Normal mode")
    logger.testing("  - Hold 3s: Setup mode")
    logger.testing("  - Hold 10s: Safe mode\n")

    # Wait for button press
    while not is_button_pressed(button):
        time.sleep(0.1)

    # Button is pressed - measure hold duration until release
    logger.info("Button pressed - measuring hold duration")

    # Restore original log level before exiting
    configure_logging(original_log_level)

    # Measure hold duration from press to release
    # This function monitors the button until release and returns the action
    hold_result = check_button_hold_duration(button, pixel_controller=pixel)

    # Map the result to the expected return values
    if hold_result == 'safe_mode':
        logger.info("10s+ button hold detected - entering Safe Mode")
        return 'safe'
    elif hold_result == 'setup':
        logger.info("3s+ button hold detected - entering Setup Mode")
        return 'setup'
    else:  # 'short'
        logger.info("Short button press detected - entering Normal Mode")
        return 'normal'
