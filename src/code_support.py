"""
WICID Main Entry Point
Orchestrates system initialization and mode execution using manager classes.
"""

import os
import time
import board
import digitalio
import microcontroller
from pixel_controller import PixelController
from configuration_manager import ConfigurationManager
from mode_manager import ModeManager
from modes import WeatherMode, TempDemoMode, PrecipDemoMode
from logging_helper import configure_logging, get_logger
from utils import trigger_safe_mode
import test_mode

# Configure logging from settings
log_level = os.getenv("LOG_LEVEL", "INFO")
configure_logging(log_level)
logger = get_logger('wicid')

# Initialize hardware
button = digitalio.DigitalInOut(board.BUTTON)
button.switch_to_input(pull=digitalio.Pull.UP)

# Display boot log if it exists
print("\n" + "=" * 60)
print("BOOT LOG")
print("=" * 60)
try:
    with open("/boot_log.txt", "r") as f:
        print(f.read())
    os.remove("/boot_log.txt")
except OSError:
    print("(no boot log available)")
print("=" * 60 + "\n")


def main():
    """Main entry point. Catches fatal errors and reboots."""
    try:
        # Check for test mode before normal initialization
        if test_mode.is_enabled():
            pixel = PixelController()
            next_mode = test_mode.run_tests_and_await_action(button, pixel)

            # Handle user's mode selection after tests
            if next_mode == 'safe':
                # Trigger safe mode and reboot
                trigger_safe_mode()
                # trigger_safe_mode() calls microcontroller.reset(), so we never reach here

            elif next_mode == 'setup':
                # Run setup portal
                logger.info("Entering setup mode (user requested after tests)")
                config_mgr = ConfigurationManager.get_instance(button)
                setup_success = config_mgr.run_portal()

                if setup_success:
                    logger.info("Setup complete - continuing to normal mode")
                else:
                    logger.info("Setup cancelled - continuing to normal mode")
                # Fall through to normal mode initialization

            # For 'normal' mode, fall through to normal initialization
            logger.info("Continuing to normal mode after test run")

        # Initialize configuration and ensure WiFi ready
        # Blocks until complete. Restarts internally on user cancel/timeout.
        # Raises exception only on unrecoverable errors.
        logger.info("Initializing configuration...")
        config_mgr = ConfigurationManager.get_instance(button)
        config_mgr.initialize()

        logger.info("Configuration complete - starting mode loop")

        # At this point: WiFiManager guaranteed connected (or available)
        # Modes handle their own service initialization

        # Run mode loop (never returns normally)
        mode_mgr = ModeManager(button)
        mode_mgr.register_modes([WeatherMode, TempDemoMode, PrecipDemoMode])
        mode_mgr.run()  # Handles setup re-entry, safe mode, mode switching

    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        pixel = PixelController()
        pixel.blink_error()
        time.sleep(2)
        microcontroller.reset()  # Reboot on unrecoverable error


if __name__ == "__main__":
    main()
