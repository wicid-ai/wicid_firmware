"""
WICID Boot Support Module

This module contains all boot logic that runs before code.py:
1. Storage configuration (disable USB, remount filesystem)
2. Checking for and installing pending firmware updates
3. Full reset update strategy (all-or-nothing replacement)

This module is compiled to bytecode (.mpy) for efficiency.
"""

import json
import os

# Import compatibility checking utilities
import sys
import time
import traceback

import microcontroller  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
import storage  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

sys.path.insert(0, "/")

from .app_typing import Any

IMPORT_ERROR = None

# CRITICAL imports - these MUST succeed or boot should fail
# If these fail, it indicates file corruption or incomplete deployment
try:
    from core.logging_helper import logger  # noqa: F401 - Used by code later in module
    from utils.utils import check_release_compatibility, mark_incompatible_release, suppress
except ImportError as e:
    # CRITICAL: Cannot continue without these fundamental utilities
    print("=" * 50)
    print(f"FATAL BOOT ERROR: Critical import failed - {e}")
    print("This indicates file corruption or incomplete firmware deployment!")
    print("Device cannot boot safely. Please:")
    print("  1. Enter Safe Mode (hold BOOT button during power-on)")
    print("  2. Run installer.py with HARD update mode")
    print("=" * 50)
    # Re-raise to halt boot - this is NOT recoverable
    raise

# OPTIONAL imports - graceful degradation if these fail
# Update/Recovery functionality will be disabled but device can still operate
try:
    from controllers.pixel_controller import PixelController
    from managers.recovery_manager import RecoveryManager
    from managers.update_manager import UpdateManager
except ImportError as e:
    IMPORT_ERROR = str(e)
    print("=" * 50)
    print(f"WARNING: Optional import failed - {e}")
    print("Update and Recovery functionality DISABLED")
    print("Device will operate in degraded mode")
    print("=" * 50)
    PixelController = None  # type: ignore
    UpdateManager = None  # type: ignore
    RecoveryManager = None  # type: ignore

# Check for pending firmware update
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"
BOOT_LOG_FILE = "/boot_log.txt"
_LOGGED_BOOT_ERROR = False


class UpdateInstaller:
    """
    Manages the focused update installation process with LED feedback.

    Centralizes LED control to avoid parameter threading through
    multiple helper functions. Uses PixelController singleton for LED access.
    """

    def __init__(self) -> None:
        self.pixel_controller: Any = None
        """Initialize the installer with LED feedback from singleton."""
        # Access singleton for LED feedback (optional, gracefully handles if unavailable)
        if PixelController is not None:
            try:
                self.pixel_controller = PixelController()
                # Start installation indicator (blue/green flashing)
                self.pixel_controller.indicate_installing()
            except Exception as e:
                print(f"Could not initialize LED: {e}")
                self.pixel_controller = None
        else:
            self.pixel_controller = None

    def update_led(self) -> None:
        """Update LED animation."""
        if self.pixel_controller:
            try:
                self.pixel_controller.manual_tick()
            except Exception as e:
                print(f"LED manual tick error: {e}")

    def turn_off_led(self) -> None:
        """Turn off LED (used on error conditions)."""
        if self.pixel_controller:
            self.pixel_controller.clear()


def log_boot_message(message: str) -> None:
    """
    Write a message to the boot log file and console.
    Always prints to console for serial debugging.
    """
    # Always print to console first (critical for debugging)
    print(message)

    global _LOGGED_BOOT_ERROR
    # Try to write to file, but don't let failures block boot
    try:
        with open(BOOT_LOG_FILE, "a") as f:
            f.write(message + "\n")
    except OSError as e:
        # Only print filesystem errors once to avoid spam
        if not _LOGGED_BOOT_ERROR:
            print(f"! Boot log write failed (OSError): {e}")
            _LOGGED_BOOT_ERROR = True
    except Exception as e:
        if not _LOGGED_BOOT_ERROR:
            print(f"! Boot log write failed: {e}")
            _LOGGED_BOOT_ERROR = True


def remove_directory_recursive(path: str, installer: Any = None) -> None:
    """
    Recursively remove a directory and all its contents.
    CircuitPython-compatible (no os.walk).

    Args:
        path: Directory path to remove
        installer: Optional UpdateInstaller instance for LED feedback
    """
    try:
        items = os.listdir(path)
    except OSError:
        # Path doesn't exist or isn't a directory
        return

    for item in items:
        item_path = f"{path}/{item}" if not path.endswith("/") else f"{path}{item}"

        # Update LED during file operations
        if installer:
            installer.update_led()

        # Try to remove as file first
        try:
            os.remove(item_path)
            continue
        except OSError:
            pass

        # Must be a directory, recurse into it
        remove_directory_recursive(item_path, installer)

        # Remove the now-empty directory
        with suppress(OSError):
            os.rmdir(item_path)

    # Remove the directory itself
    with suppress(OSError):
        os.rmdir(path)


def cleanup_pending_update(installer: Any = None) -> None:
    """
    Remove pending update directory and all its contents.
    Logs errors but continues to attempt cleanup.

    Args:
        installer: Optional UpdateInstaller instance for LED feedback
    """
    log_boot_message("Cleaning up pending update...")

    try:
        remove_directory_recursive(PENDING_UPDATE_DIR, installer)
        log_boot_message("✓ Cleanup complete")
    except Exception as e:
        log_boot_message(f"Warning: Cleanup error: {e}")


def delete_all_except(preserve_paths: list[str], installer: Any = None) -> None:
    """
    Delete all files and directories in root except specified paths.
    Forces recursive deletion but logs errors and continues.

    Args:
        preserve_paths: List of paths to preserve (e.g., ['/secrets.json', '/pending_update'])
        installer: Optional UpdateInstaller instance for LED feedback
    """
    log_boot_message("Performing full reset (deleting all existing files)...")

    # Normalize preserve paths (case-insensitive for FAT32 filesystem)
    preserve_set = {path.rstrip("/").lower() for path in preserve_paths}

    # Get list of all items in root
    root_items = os.listdir("/")

    for item in root_items:
        item_path = f"/{item}"

        # Update LED during file operations
        if installer:
            installer.update_led()

        # Skip preserved paths (case-insensitive comparison for FAT32)
        if item_path.lower() in preserve_set:
            log_boot_message(f"  Preserved: {item_path}")
            continue

        # Skip system files/directories
        if item in [".Trashes", ".metadata_never_index", ".fseventsd", "System Volume Information"]:
            continue

        try:
            # Try to remove as file first
            try:
                os.remove(item_path)
                continue
            except OSError:
                pass

            # If not a file, try as directory - force recursive deletion
            remove_directory_recursive(item_path, installer)

        except Exception as e:
            log_boot_message(f"  Error processing {item_path}: {e}")

    log_boot_message("✓ Full reset complete")


def move_directory_contents(src_dir: str, dest_dir: str, installer: Any = None) -> None:
    """
    Move all files and directories from src to dest.
    Logs errors but continues to attempt moving remaining files.

    CRITICAL: Never overwrites preserved files (secrets.json, etc.)

    Args:
        src_dir: Source directory path
        dest_dir: Destination directory path
        installer: Optional UpdateInstaller instance for LED feedback
    """
    log_boot_message(f"Moving files from {src_dir} to {dest_dir}...")

    # Define preserved files that should NEVER be overwritten
    # These must match the preservation list used during deletion
    PRESERVED_FILES = ["secrets.json", "incompatible_releases.json", "DEVELOPMENT"]

    items = os.listdir(src_dir)

    for item in items:
        src_path = f"{src_dir}/{item}"
        dest_path = f"{dest_dir}/{item}"

        # Update LED during file operations
        if installer:
            installer.update_led()

        # Skip preserved files - never overwrite them during OTA updates
        # Use case-insensitive comparison for FAT32 filesystem compatibility
        if dest_dir == "/" and item.lower() in [f.lower() for f in PRESERVED_FILES]:
            log_boot_message(f"  Skipping preserved file: {item}")
            # Remove from pending_update to avoid confusion
            with suppress(OSError):
                os.remove(src_path)
            continue

        try:
            # Check if it's a directory
            is_dir = False
            with suppress(OSError):
                os.listdir(src_path)
                is_dir = True

            if is_dir:
                # Create destination directory if it doesn't exist
                with suppress(OSError):
                    os.mkdir(dest_path)  # Directory might already exist

                # Recursively move contents
                move_directory_contents(src_path, dest_path, installer)

                # Remove source directory
                try:
                    os.rmdir(src_path)
                except OSError as e:
                    log_boot_message(f"  Could not remove {src_path}: {e}")
            else:
                # Move file
                try:
                    # Additional safety check: never overwrite preserved files
                    # Extract filename from dest_path for checking
                    dest_filename = dest_path.split("/")[-1]
                    if dest_filename.lower() in [f.lower() for f in PRESERVED_FILES]:
                        log_boot_message(f"ERROR: Attempted to overwrite preserved file: {dest_filename}")
                        log_boot_message(f"  Source: {src_path}")
                        log_boot_message(f"  Destination: {dest_path}")
                        raise Exception(f"BUG: Move would overwrite preserved file {dest_filename}")

                    # Read from source
                    with open(src_path, "rb") as src_file:
                        content = src_file.read()

                    # Write to destination
                    with open(dest_path, "wb") as dest_file:
                        dest_file.write(content)

                    # Remove source
                    os.remove(src_path)
                except Exception as e:
                    log_boot_message(f"  Could not move {src_path}: {e}")

        except Exception as e:
            log_boot_message(f"  Error processing {item}: {e}")

    log_boot_message("✓ File move complete")


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

        log_boot_message("=" * 50)
        log_boot_message("PRODUCTION MODE")
        log_boot_message("Filesystem writable from code")
        log_boot_message("USB mass storage disabled")
        log_boot_message("USB serial console ENABLED for debugging")
        log_boot_message("To enable USB for development: Hold button for 10 seconds to enter Safe Mode")
        log_boot_message("=" * 50)
    except Exception as e:
        log_boot_message("=" * 50)
        log_boot_message(f"ERROR: Storage configuration failed: {e}")
        log_boot_message("Device may be in inconsistent state")
        log_boot_message("Continuing boot to allow recovery...")
        log_boot_message("=" * 50)


def process_pending_update() -> None:
    """
    Check for and process pending firmware updates.
    """
    log_boot_message("\n=== BOOT: Checking for pending firmware updates ===")
    log_boot_message(f"Looking for: {PENDING_ROOT_DIR}")

    # Check for pending update installation
    try:
        # Try to list directory - will raise OSError if doesn't exist
        try:
            files = os.listdir(PENDING_ROOT_DIR)
        except OSError:
            # Directory doesn't exist - normal boot
            log_boot_message("No pending update found - proceeding with normal boot")
            return

        # Check if directory has files
        if not files:
            log_boot_message("Pending update directory is empty - cleaning up")
            cleanup_pending_update()
            return

        log_boot_message(f"Found {len(files)} files in pending update")

        log_boot_message("=" * 50)
        log_boot_message("FIRMWARE UPDATE DETECTED")
        log_boot_message("=" * 50)

        # Initialize installer with LED feedback (accesses singleton internally)
        installer = UpdateInstaller()
        installer.update_led()
        if installer.pixel_controller:
            log_boot_message("LED indicator: flashing blue/green during update")

        # Step 1: Load manifest from extracted update
        manifest_path = f"{PENDING_ROOT_DIR}/manifest.json"
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            log_boot_message("✓ Manifest loaded")
        except Exception as e:
            log_boot_message(f"ERROR: Could not load manifest: {e}")
            log_boot_message(f"Traceback: {traceback.format_exc()}")
            cleanup_pending_update()
            return

        # Step 2: Get current version
        try:
            current_version = os.getenv("VERSION", "0.0.0")
        except Exception:
            current_version = "0.0.0"

        log_boot_message(f"Current version: {current_version}")
        log_boot_message(f"Update version: {manifest.get('version', 'unknown')}")

        # Step 3: Verify compatibility using DRY check
        if check_release_compatibility is not None:
            is_compatible, error_msg = check_release_compatibility(manifest, current_version)

            # Update LED during compatibility check
            if installer:
                installer.update_led()

            if not is_compatible:
                log_boot_message(f"ERROR: {error_msg}")

                # Turn off LED on error
                if installer:
                    installer.turn_off_led()

                # Mark incompatible with detailed reason
                if mark_incompatible_release is not None:
                    mark_incompatible_release(manifest.get("version", "unknown"), error_msg or "Unknown error")

                cleanup_pending_update()
                log_boot_message("=" * 50)
                log_boot_message("Update aborted due to incompatibility")
                log_boot_message("=" * 50)
                return
            else:
                log_boot_message("✓ Compatibility verified")

                # Update LED
                if installer:
                    installer.update_led()

                # Step 3.5: Validate extracted update contains all critical files
                # This is a second check before destructive operations begin
                log_boot_message("Validating update package integrity...")
                if RecoveryManager is not None:
                    all_present, missing_files = RecoveryManager.validate_extracted_update(PENDING_ROOT_DIR)

                    if not all_present:
                        log_boot_message("ERROR: Update package is incomplete")
                        log_boot_message(f"Missing {len(missing_files)} critical files:")
                        for missing in missing_files[:10]:
                            log_boot_message(f"  - {missing}")
                        if len(missing_files) > 10:
                            log_boot_message(f"  ... and {len(missing_files) - 10} more")
                        log_boot_message("Installation would brick the device - aborting")

                        # Turn off LED on error
                        if installer:
                            installer.turn_off_led()

                        # Mark as incompatible
                        if mark_incompatible_release is not None:
                            mark_incompatible_release(
                                manifest.get("version", "unknown"),
                                f"Incomplete package - missing {len(missing_files)} critical files",
                            )

                        cleanup_pending_update()
                        return

                    log_boot_message("✓ All critical files present in update package")
                else:
                    log_boot_message("⚠ RecoveryManager not available for validation - proceeding anyway")

                # Update LED after validation
                if installer:
                    installer.update_led()

                # Step 4: Verify preserved files exist before destructive operations
                log_boot_message("Verifying preserved files before update...")
                secrets_exists = False
                try:
                    with open("/secrets.json") as f:
                        secrets_data = f.read()
                        secrets_size = len(secrets_data)
                    secrets_exists = True
                    log_boot_message(f"✓ secrets.json found ({secrets_size} bytes)")
                except OSError:
                    log_boot_message("ℹ No secrets.json (first-time setup)")

                # Step 5: Delete everything except secrets, incompatible list, recovery, and DEVELOPMENT flag
                preserve_paths = [
                    "/secrets.json",
                    "/incompatible_releases.json",
                    "/DEVELOPMENT",
                    "/recovery",
                    PENDING_UPDATE_DIR,
                ]
                delete_all_except(preserve_paths, installer)
                os.sync()  # Sync after deletion

                # Verify preserved files still exist after deletion
                if secrets_exists:
                    try:
                        with open("/secrets.json") as f:
                            post_delete_data = f.read()
                        if post_delete_data != secrets_data:
                            log_boot_message("ERROR: secrets.json was modified during deletion!")
                            raise Exception("Preservation failed - secrets.json corrupted")
                        log_boot_message("✓ secrets.json preserved after deletion")
                    except OSError as e:
                        log_boot_message("ERROR: secrets.json was deleted during cleanup!")
                        raise Exception("Preservation failed - secrets.json deleted") from e

                # Update LED after deletion
                if installer:
                    installer.update_led()

                # Step 6: Move files from pending_update/root to root
                move_directory_contents(PENDING_ROOT_DIR, "/", installer)
                os.sync()  # Sync after moving all files

                # Verify preserved files still exist after move
                if secrets_exists:
                    try:
                        with open("/secrets.json") as f:
                            post_move_data = f.read()
                        if post_move_data != secrets_data:
                            log_boot_message("ERROR: secrets.json was modified during file move!")
                            raise Exception("File move corrupted secrets.json")
                        log_boot_message("✓ secrets.json preserved after file move")
                    except OSError as e:
                        log_boot_message("ERROR: secrets.json was deleted during file move!")
                        raise Exception("File move deleted secrets.json") from e

                # Step 7: Validate critical files are present after installation
                # Use centralized validation from RecoveryManager if available
                if RecoveryManager is not None:
                    all_present, missing_files = RecoveryManager.validate_critical_files()
                else:
                    # Fallback if RecoveryManager couldn't be imported
                    # This itself indicates a critical failure
                    log_boot_message("ERROR: RecoveryManager not available for validation")
                    all_present = False
                    missing_files = ["RecoveryManager module (import failed)"]

                if not all_present:
                    log_boot_message("ERROR: Critical files missing after installation:")
                    for missing_file in missing_files:
                        log_boot_message(f"  - {missing_file}")
                    log_boot_message("Installation incomplete - aborting to prevent broken system")
                    # Turn off LED on error
                    if installer:
                        installer.turn_off_led()
                    return  # Abort without rebooting - device will boot with old version

                log_boot_message("✓ All critical files validated")

                # Update LED after validation
                if installer:
                    installer.update_led()

                # Step 8: Create or update recovery backup
                log_boot_message("Creating recovery backup...")
                if RecoveryManager is not None:
                    try:
                        success, backup_msg = RecoveryManager.create_recovery_backup()
                        if success:
                            log_boot_message(f"✓ {backup_msg}")
                        else:
                            log_boot_message(f"⚠ {backup_msg}")
                    except Exception as e:
                        log_boot_message(f"⚠ Recovery backup failed: {e}")
                else:
                    log_boot_message("⚠ RecoveryManager not available for backup")

                # Update LED after backup
                if installer:
                    installer.update_led()

                # Step 9: Cleanup pending update directory
                cleanup_pending_update(installer)
                os.sync()  # Sync after cleanup

                # Update LED after cleanup
                if installer:
                    installer.update_led()

                log_boot_message("=" * 50)
                log_boot_message(f"Update complete: {current_version} → {manifest.get('version')}")
                log_boot_message("Recovery backup updated")
                log_boot_message("Rebooting...")
                log_boot_message("=" * 50)

                # Sync filesystem before reboot
                os.sync()

                # Reboot
                microcontroller.reset()
        else:
            log_boot_message("=" * 50)
            log_boot_message("CRITICAL: Compatibility check not available")
            if IMPORT_ERROR:
                log_boot_message(f"Import error: {IMPORT_ERROR}")
            log_boot_message("Skipping update for safety")
            log_boot_message("=" * 50)
            cleanup_pending_update()

    except OSError as e:
        # No pending_update directory - normal boot
        log_boot_message(f"OSError during update check: {e}")
    except Exception as e:
        log_boot_message(f"Error checking for updates: {e}")
        log_boot_message(f"Traceback: {traceback.format_exc()}")


def check_and_restore_from_recovery() -> bool:
    """
    Check for missing critical files and restore from recovery if needed.

    This is the first thing that runs at boot to catch catastrophic failures
    from interrupted updates or corrupted filesystems.

    Returns:
        bool: True if recovery was needed and performed, False otherwise
    """
    if RecoveryManager is None:
        log_boot_message("RecoveryManager not available, skipping recovery check")
        return False

    # Check if all critical files are present
    all_present, missing_files = RecoveryManager.validate_critical_files()

    if all_present:
        # All good, no recovery needed
        return False

    # Critical files missing - check if recovery backup exists
    log_boot_message("=" * 50)
    log_boot_message("CRITICAL: Missing critical files detected")
    log_boot_message("=" * 50)
    log_boot_message(f"Missing {len(missing_files)} critical files:")
    for missing in missing_files[:10]:  # Show first 10
        log_boot_message(f"  - {missing}")
    if len(missing_files) > 10:
        log_boot_message(f"  ... and {len(missing_files) - 10} more")

    if not RecoveryManager.recovery_exists():
        log_boot_message("\n✗ No recovery backup available")
        log_boot_message("Device may not boot correctly")
        log_boot_message("Manual intervention required")
        return False

    # Attempt recovery
    log_boot_message("\n→ Attempting recovery from backup...")
    success, message = RecoveryManager.restore_from_recovery()

    if success:
        log_boot_message(f"✓ {message}")

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
                log_boot_message(f"Marked version {failed_version} as incompatible")
        except Exception:
            pass  # Couldn't determine version, continue anyway

        # Clean up the failed update
        with suppress(Exception):
            remove_directory_recursive("/pending_update")

        log_boot_message("\n→ Device recovered successfully")
        log_boot_message("Continuing with normal boot")
        return True
    else:
        log_boot_message(f"✗ {message}")
        log_boot_message("Manual intervention required")
        return False


def main() -> None:
    """
    Main entry point called from boot.py.
    Configures storage and processes any pending updates.
    Note: USB serial console is configured in boot.py before this runs.
    """
    # Configure storage (this might fail if filesystem is corrupted)
    configure_storage()

    # CRITICAL: Check for and recover from catastrophic failures first
    recovery_performed = check_and_restore_from_recovery()

    if recovery_performed:
        # Recovery was needed - reboot to ensure clean state
        log_boot_message("\n→ Rebooting after recovery...")
        # NOTE: time.sleep() is acceptable here - this runs in boot.py before the scheduler is initialized
        time.sleep(2)
        os.sync()
        microcontroller.reset()

    process_pending_update()
