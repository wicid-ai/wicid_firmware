"""
WICID Boot Support Module

This module orchestrates boot logic that runs before code.py:
1. Storage configuration (disable USB, remount filesystem)
2. Recovery from missing critical files (delegated to utils.recovery)
3. Processing pending firmware updates (delegated to utils.update_install)

Boot Flow:
    boot.py → _emergency_recovery() → boot_support.main()
                                            ↓
                                      configure_storage()
                                            ↓
                                 check_and_restore_from_recovery() (from utils.recovery)
                                            ↓
                                    process_pending_update() (from utils.update_install)

This module focuses on boot orchestration. Recovery logic is implemented in
utils.recovery, and update processing is implemented in utils.update_install.

This module is compiled to bytecode (.mpy) for efficiency.
"""

# =============================================================================
# IMPORTS
# =============================================================================

# Built-in modules
import os
import sys
import time

# CircuitPython hardware modules
import microcontroller  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
import storage  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

# Ensure root is in path for absolute imports
sys.path.insert(0, "/")

# -----------------------------------------------------------------------------
# CRITICAL imports - boot halts if these fail
# boot.py's emergency recovery ensures these files exist before we get here.
# If they still fail, the device is in an unrecoverable state.
# -----------------------------------------------------------------------------
try:
    from core.logging_helper import configure_logging, logger
    from utils.recovery import check_and_restore_from_recovery
    from utils.update_install import process_pending_update
except ImportError as e:
    print("=" * 50)
    print(f"FATAL BOOT ERROR: Critical import failed - {e}")
    print("boot.py emergency recovery should have restored these files.")
    print("This indicates severe filesystem corruption.")
    print("Please:")
    print("  1. Enter Safe Mode (hold BOOT button during power-on)")
    print("  2. Run installer.py with HARD update mode")
    print("=" * 50)
    raise

BOOT_LOG_FILE = "/boot_log.txt"


def configure_storage() -> None:
    """
    Configure storage for production mode.
    Disables USB mass storage and makes filesystem writable from code.
    Wrapped in try/except to allow boot to continue if storage config fails.
    Note: USB serial console is configured in boot.py before this runs.
    """
    try:
        # Production mode: disable USB mass storage, allow code to write files
        storage.disable_usb_drive()
        storage.remount("/", readonly=False)

        # Note: Logging to file is not possible here because the file is not yet created.
        print("=" * 50)
        print("PRODUCTION MODE")
        print("Filesystem writable from code")
        print("USB mass storage disabled")
        print("USB serial console ENABLED for debugging")
        print("To enable USB for development: Hold button for 10 seconds to enter Safe Mode")
        print("=" * 50)
    except Exception as e:
        print("=" * 50)
        print(f"ERROR: Storage configuration failed: {e}")
        print("Device may be in inconsistent state")
        print("Continuing boot to allow recovery...")
        print("=" * 50)


# process_pending_update is now imported from utils.update_install
# check_and_restore_from_recovery is now imported from utils.recovery


def main() -> None:
    """
    Main entry point called from boot.py.
    Configures storage and processes any pending updates.
    Note: USB serial console is configured in boot.py before this runs.
    """
    # Configure storage (this might fail if filesystem is corrupted)
    configure_storage()

    # Configure logging level for boot sequence
    # This will be reset by code_support once it's initialized.
    # This level applies only to boot sequence logging.
    configure_logging("ERROR")

    log = logger("wicid.boot_support", log_file=BOOT_LOG_FILE)

    # CRITICAL: Check for and recover from catastrophic failures first
    recovery_performed = check_and_restore_from_recovery(log_file=BOOT_LOG_FILE)

    if recovery_performed:
        # Recovery was needed - reboot to ensure clean state
        log.info("\n→ Rebooting after recovery...")
        # NOTE: time.sleep() is acceptable here - this runs in boot.py before the scheduler is initialized
        time.sleep(2)
        os.sync()

        microcontroller.reset()

    process_pending_update()
