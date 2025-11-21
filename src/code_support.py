"""
WICID Main Entry Point
Orchestrates system initialization and mode execution using manager classes.
"""

import os

import microcontroller  # type: ignore[import-untyped]  # CircuitPython-only module

import test_mode
from configuration_manager import ConfigurationManager
from input_manager import InputManager
from logging_helper import configure_logging, logger
from mode_manager import ModeManager
from modes import PrecipDemoMode, SetupPortalMode, TempDemoMode, WeatherMode
from pixel_controller import PixelController
from scheduler import Scheduler
from utils import trigger_safe_mode

# Configure logging from settings
log_level = os.getenv("LOG_LEVEL", "INFO")
configure_logging(log_level)
APP_LOG = logger("wicid")

# Initialize InputManager early (owns board.BUTTON)
# Managers should use InputManager callbacks instead of polling
input_mgr = InputManager.instance()

# Display boot log if it exists
print("\n" + "=" * 60)
print("BOOT LOG")
print("=" * 60)
try:
    with open("/boot_log.txt") as f:
        print(f.read())
    os.remove("/boot_log.txt")
except OSError:
    print("(no boot log available)")
print("=" * 60 + "\n")


async def _startup_sequence():
    """Run main startup logic inside scheduler context."""
    try:
        # Check for test mode before normal initialization
        if test_mode.is_enabled():
            pixel = PixelController()
            next_mode = await test_mode.run_tests_and_await_action(pixel)

            if next_mode == "safe":
                trigger_safe_mode()
            elif next_mode == "setup":
                APP_LOG.info("Entering setup mode (user requested after tests)")
                setup_success = await SetupPortalMode.execute()
                if setup_success:
                    APP_LOG.info("Setup complete - continuing to normal mode")
                else:
                    APP_LOG.info("Setup cancelled - continuing to normal mode")

            APP_LOG.info("Continuing to normal mode after test run")

        APP_LOG.info("Initializing configuration...")
        config_mgr = ConfigurationManager.instance()
        await config_mgr.initialize(portal_runner=SetupPortalMode.execute)

        APP_LOG.info("Configuration complete - starting mode loop")
        mode_mgr = ModeManager.instance()
        mode_mgr.register_modes([WeatherMode, TempDemoMode, PrecipDemoMode])
        await mode_mgr.run()

    except Exception as e:
        APP_LOG.critical(f"Fatal error: {e}", exc_info=True)
        try:
            import traceback

            with open("/crash_log.txt", "w") as crash_file:
                traceback.print_exception(type(e), e, e.__traceback__, file=crash_file)
                crash_file.flush()
        except Exception:
            pass
        pixel = PixelController()
        await pixel.blink_error()
        await Scheduler.sleep(10)
        microcontroller.reset()


def main():
    """Entrypoint that schedules startup sequence and runs scheduler."""
    scheduler = Scheduler.instance()
    scheduler.schedule_now(
        coroutine=_startup_sequence,
        priority=0,
        name="Startup Sequence",
    )
    scheduler.run_forever()


if __name__ == "__main__":
    main()
