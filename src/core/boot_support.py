"""
WICID Boot Support Module

This module contains all boot logic that runs before code.py:
1. Storage configuration (disable USB, remount filesystem)
2. Recovery from missing critical files (via recovery utilities)
3. Processing pending firmware updates (delegated to utils.update_install)

Boot Flow:
    boot.py → _emergency_recovery() → boot_support.main()
                                            ↓
                                      configure_storage()
                                            ↓
                                 check_and_restore_from_recovery()
                                            ↓
                                    process_pending_update() (from utils.update_install)

This module is compiled to bytecode (.mpy) for efficiency.
"""

# =============================================================================
# IMPORTS
# =============================================================================

# Built-in modules
import json
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
    from core.logging_helper import logger
    from utils.recovery import (
        recovery_exists,
        restore_from_recovery,
        validate_critical_files,
    )
    from utils.update_install import process_pending_update, reset_version_for_ota
    from utils.utils import mark_incompatible_release, remove_directory_recursive, suppress
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
    log = logger("wicid.boot", log_file=BOOT_LOG_FILE)
    try:
        # Production mode: disable USB mass storage, allow code to write files
        storage.disable_usb_drive()
        storage.remount("/", readonly=False)

        log.info("=" * 50)
        log.info("PRODUCTION MODE")
        log.info("Filesystem writable from code")
        log.info("USB mass storage disabled")
        log.info("USB serial console ENABLED for debugging")
        log.info("To enable USB for development: Hold button for 10 seconds to enter Safe Mode")
        log.info("=" * 50)
    except Exception as e:
        log.info("=" * 50)
        log.info(f"ERROR: Storage configuration failed: {e}")
        log.info("Device may be in inconsistent state")
        log.info("Continuing boot to allow recovery...")
        log.info("=" * 50)


# process_pending_update is now imported from utils.update_install


def check_and_restore_from_recovery() -> bool:
    """
    Check for missing critical files and restore from recovery if needed.

    This runs early in boot to catch catastrophic failures from interrupted
    updates or corrupted filesystems. Recovery utilities are guaranteed to be
    available since they're CRITICAL imports (boot.py ensures it via emergency recovery).

    Returns:
        bool: True if recovery was needed and performed, False otherwise
    """
    log = logger("wicid.boot", log_file=BOOT_LOG_FILE)
    # Check if all critical files are present
    all_present, missing_files = validate_critical_files()

    if all_present:
        # All good, no recovery needed
        return False

    # Critical files missing - check if recovery backup exists
    log.info("=" * 50)
    log.info("CRITICAL: Missing critical files detected")
    log.info("=" * 50)
    log.info(f"Missing {len(missing_files)} critical files:")
    for missing in missing_files[:10]:  # Show first 10
        log.info(f"  - {missing}")
    if len(missing_files) > 10:
        log.info(f"  ... and {len(missing_files) - 10} more")

    if not recovery_exists():
        log.info("\n✗ No recovery backup available")
        log.info("Device may not boot correctly")
        log.info("Manual intervention required")
        return False

    # Attempt recovery
    log.info("\n→ Attempting recovery from backup...")
    success, message = restore_from_recovery()

    if success:
        log.info(f"✓ {message}")

        # Try to determine what version caused the failure
        try:
            with open("/pending_update/root/manifest.json") as f:
                failed_manifest = json.load(f)
                failed_version = failed_manifest.get("version", "unknown")

                # Mark this version as incompatible immediately (one-strike policy)
                if mark_incompatible_release is not None:
                    mark_incompatible_release(
                        failed_version, "Automatic recovery triggered - update left device in unbootable state"
                    )
                log.info(f"Marked version {failed_version} as incompatible")
        except Exception:
            pass  # Couldn't determine version, continue anyway

        # Clean up the failed update
        with suppress(Exception):
            remove_directory_recursive("/pending_update")

        # Reset VERSION to 0.0.0 to force OTA update pickup
        # This ensures the device will accept any available update after recovery
        if reset_version_for_ota():
            log.info("Reset VERSION to 0.0.0 for OTA pickup")
        else:
            log.info("WARNING: Could not reset VERSION for OTA")

        log.info("\n→ Device recovered successfully")
        log.info("Continuing with normal boot")
        return True
    else:
        log.info(f"✗ {message}")
        log.info("Manual intervention required")
        return False


def main() -> None:
    """
    Main entry point called from boot.py.
    Configures storage and processes any pending updates.
    Note: USB serial console is configured in boot.py before this runs.
    """
    log = logger("wicid.boot", log_file=BOOT_LOG_FILE)
    # Configure storage (this might fail if filesystem is corrupted)
    configure_storage()

    # CRITICAL: Check for and recover from catastrophic failures first
    recovery_performed = check_and_restore_from_recovery()

    if recovery_performed:
        # Recovery was needed - reboot to ensure clean state
        log.info("\n→ Rebooting after recovery...")
        # NOTE: time.sleep() is acceptable here - this runs in boot.py before the scheduler is initialized
        time.sleep(2)
        os.sync()
        microcontroller.reset()

    process_pending_update()
