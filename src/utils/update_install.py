"""
Update installation utilities for WICID firmware.

Handles the installation of pending firmware updates during boot.
This module is separate from UpdateManager (which handles download/staging)
and recovery.py (which handles backup/restore).

Usage:
    from utils.update_install import process_pending_update
    process_pending_update()
"""

import json
import os
import sys
import time
import traceback

import microcontroller  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

from core.app_typing import Any
from core.logging_helper import logger
from utils.recovery import RECOVERY_DIR, create_recovery_backup, validate_critical_files, validate_extracted_update
from utils.utils import check_release_compatibility, mark_incompatible_release, remove_directory_recursive, suppress

# Import BOOT_LOG_FILE from boot_support (must be lazy to avoid circular dependency)
# boot_support imports process_pending_update from this module, so we import
# BOOT_LOG_FILE inside _boot_file_logger() function

# Path constants for pending update directory structure
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"
PENDING_STAGING_DIR = "/pending_update/.staging"
READY_MARKER_FILE = "/pending_update/.ready"
INSTALL_LOG_FILE = "/install.log"
INSTALL_SCRIPTS_DIR = "firmware_install_scripts"

# Files that should NEVER be overwritten during OTA updates
# Only user-provided data that cannot be regenerated
PRESERVED_FILES = {
    "secrets.json",  # WiFi credentials and API keys (user-provided)
    "incompatible_releases.json",  # Failed update tracking (user data)
    "DEVELOPMENT",  # Development mode flag (user-set)
}

# Boot logger instance - initialized lazily to avoid circular dependencies
_boot_file_logger_instance: Any = None


def cleanup_pending_update() -> None:
    """
    Remove pending update directory and all its contents.
    Logs errors but continues to attempt cleanup.
    """
    log = _boot_file_logger()
    log.info("Cleaning up pending update...")

    try:
        remove_directory_recursive(PENDING_UPDATE_DIR)
        log.info("✓ Cleanup complete")
    except Exception as e:
        log.info(f"Warning: Cleanup error: {e}")


def delete_all_except(preserve_paths: list[str]) -> None:
    """
    Delete all files and directories in root except specified paths.
    Forces recursive deletion but logs errors and continues.

    Args:
        preserve_paths: List of paths to preserve (e.g., ['/secrets.json', '/pending_update'])
    """
    log = _boot_file_logger()
    log.info("Performing full reset (deleting all existing files)...")

    # Normalize preserve paths (case-insensitive for FAT32 filesystem)
    preserve_set = {path.rstrip("/").lower() for path in preserve_paths}

    # Get list of all items in root
    root_items = os.listdir("/")

    for item in root_items:
        item_path = f"/{item}"

        # Update LED during file operations
        update_led()

        # Skip preserved paths (case-insensitive comparison for FAT32)
        if item_path.lower() in preserve_set:
            log.info(f"  Preserved: {item_path}")
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
            remove_directory_recursive(item_path)

        except Exception as e:
            log.info(f"  Error processing {item_path}: {e}")

    log.info("✓ Full reset complete")


def execute_install_script(
    script_path: str,
    script_type: str,
    version: str,
    pending_root_dir: str = PENDING_ROOT_DIR,
    pending_update_dir: str = PENDING_UPDATE_DIR,
) -> tuple[bool, str]:
    """
    Execute a pre-install or post-install script.

    The script must define a main() function that accepts appropriate arguments:
    - Pre-install: main(log_message, pending_root_dir, pending_update_dir)
    - Post-install: main(log_message, version)

    Args:
        script_path: Full path to the script file
        script_type: "pre_install" or "post_install" for logging
        version: Version string of the update
        pending_root_dir: Path to extracted update files
        pending_update_dir: Path to pending update directory

    Returns:
        tuple: (success, message)
    """
    log = _boot_file_logger()
    log.info(f"Executing {script_type} script: {script_path}")
    _write_install_log(f"\n{'=' * 50}")
    _write_install_log(f"{script_type.upper()} SCRIPT EXECUTION")
    _write_install_log(f"Script: {script_path}")
    _write_install_log(f"Version: {version}")
    _write_install_log(f"{'=' * 50}")

    # Update LED
    update_led()

    try:
        # Check if script exists
        try:
            os.stat(script_path)
        except OSError:
            msg = f"Script not found: {script_path}"
            log.info(msg)
            _write_install_log(msg)
            return (False, msg)

        # Read script content
        with open(script_path) as f:
            script_content = f.read()

        # Create log function for script to use
        def script_log(message: str) -> None:
            log.info(f"  [{script_type}] {message}")
            _write_install_log(f"  {message}")
            update_led()

        # Prepare execution environment with useful modules
        # Import builtins module directly - works in both CPython and CircuitPython
        import builtins

        script_globals: dict[str, Any] = {
            "__name__": "__main__",
            "__builtins__": builtins.__dict__,
            "os": os,
            "json": json,
            "sys": sys,
            "time": time,
            "traceback": traceback,
            "microcontroller": microcontroller,
        }

        # Execute the script to define main()
        exec(script_content, script_globals)

        # Check if main() is defined
        if "main" not in script_globals:
            msg = f"Script missing main() function: {script_path}"
            log.info(f"ERROR: {msg}")
            _write_install_log(f"ERROR: {msg}")
            return (False, msg)

        # Call main() with appropriate arguments
        if script_type == "pre_install":
            result = script_globals["main"](script_log, pending_root_dir, pending_update_dir)
        else:  # post_install
            result = script_globals["main"](script_log, version)

        # Interpret result
        if result is True or result is None:
            msg = f"{script_type} script completed successfully"
            log.info(f"✓ {msg}")
            _write_install_log(f"SUCCESS: {msg}")
            return (True, msg)
        else:
            msg = f"{script_type} script returned failure"
            log.info(f"✗ {msg}")
            _write_install_log(f"FAILURE: {msg}")
            return (False, msg)

    except Exception as e:
        msg = f"{script_type} script error: {e}"
        log.info(f"ERROR: {msg}")
        _write_install_log(f"ERROR: {msg}")
        # Traceback logging - protect against traceback module issues in CircuitPython
        try:
            tb_str = traceback.format_exc()
            log.info(f"Traceback: {tb_str}")
            _write_install_log(f"Traceback:\n{tb_str}")
        except Exception:
            pass  # Best effort traceback logging
        return (False, msg)


# Memoized PixelController singleton for LED feedback
_pixel_controller: Any = None


def move_directory_contents(src_dir: str, dest_dir: str) -> None:
    """
    Move all files and directories from src to dest.
    Logs errors but continues to attempt moving remaining files.

    CRITICAL: Never overwrites preserved files (secrets.json, etc.)

    Args:
        src_dir: Source directory path
        dest_dir: Destination directory path
    """
    log = _boot_file_logger()
    log.info(f"Moving files from {src_dir} to {dest_dir}...")

    items = os.listdir(src_dir)

    for item in items:
        src_path = f"{src_dir}/{item}"
        dest_path = f"{dest_dir}/{item}"

        # Update LED during file operations
        update_led()

        # Skip preserved files - never overwrite them during OTA updates
        # Use case-insensitive comparison for FAT32 filesystem compatibility
        if dest_dir == "/" and item.lower() in [f.lower() for f in PRESERVED_FILES]:
            log.info(f"  Skipping preserved file: {item}")
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
                move_directory_contents(src_path, dest_path)

                # Remove source directory
                try:
                    os.rmdir(src_path)
                except OSError as e:
                    log.info(f"  Could not remove {src_path}: {e}")
            else:
                # Move file
                try:
                    # Additional safety check: never overwrite preserved files
                    # Extract filename from dest_path for checking
                    dest_filename = dest_path.split("/")[-1]
                    if dest_filename.lower() in [f.lower() for f in PRESERVED_FILES]:
                        log.info(f"ERROR: Attempted to overwrite preserved file: {dest_filename}")
                        log.info(f"  Source: {src_path}")
                        log.info(f"  Destination: {dest_path}")
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
                    log.info(f"  Could not move {src_path}: {e}")

        except Exception as e:
            log.info(f"  Error processing {item}: {e}")

    log.info("✓ File move complete")


def process_pending_update() -> None:
    """
    Check for and process pending firmware updates.

    This is the main entry point for update installation during boot.
    Called from boot_support.py after recovery checks complete.
    """
    log = _boot_file_logger()
    log.info("\n=== BOOT: Checking for pending firmware updates ===")
    log.info(f"Looking for: {PENDING_ROOT_DIR}")

    # Clean up any incomplete staging first
    _cleanup_incomplete_staging()

    # Check for pending update installation
    try:
        # Try to list directory - will raise OSError if doesn't exist
        try:
            files = os.listdir(PENDING_ROOT_DIR)
        except OSError:
            # Directory doesn't exist - normal boot
            log.info("No pending update found - proceeding with normal boot")
            return

        # Check if directory has files
        if not files:
            log.info("Pending update directory is empty - cleaning up")
            cleanup_pending_update()
            return

        # Verify the .ready marker exists (atomic staging verification)
        if not _validate_ready_marker():
            log.info("WARNING: Pending update missing .ready marker")
            log.info("Update staging was incomplete - cleaning up")
            cleanup_pending_update()
            return

        log.info("✓ Ready marker validated")
        log.info(f"Found {len(files)} files in pending update")

        log.info("=" * 50)
        log.info("FIRMWARE UPDATE DETECTED")
        log.info("=" * 50)

        # Initialize LED feedback (accesses singleton internally)
        update_led()
        if _pixel_controller:
            log.info("LED indicator: flashing blue/green during update")

        # Step 1: Load manifest from extracted update
        manifest_path = f"{PENDING_ROOT_DIR}/manifest.json"
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            log.info("✓ Manifest loaded")
        except Exception as e:
            log.info(f"ERROR: Could not load manifest: {e}")
            log.info(f"Traceback: {traceback.format_exc()}")
            cleanup_pending_update()
            return

        # Step 2: Get current version
        try:
            current_version = os.getenv("VERSION", "0.0.0")
        except Exception:
            current_version = "0.0.0"

        log.info(f"Current version: {current_version}")
        log.info(f"Update version: {manifest.get('version', 'unknown')}")

        # Initialize install log for this update attempt
        update_version = manifest.get("version", "unknown")
        _write_install_log("WICID Firmware Update", overwrite=True)
        _write_install_log(f"Update version: {update_version}")
        _write_install_log(f"Current version: {current_version}")
        _write_install_log(f"Timestamp: {time.monotonic()}")

        # Step 2.5: Execute pre-install script if present
        # Pre-install runs BEFORE compatibility checks and validation
        # This allows the script to modify files before validation runs
        if manifest.get("has_pre_install_script", False):
            pre_script_path = _get_script_path("pre_install", update_version, PENDING_ROOT_DIR)
            log.info("Pre-install script indicated in manifest")

            script_success, script_msg = execute_install_script(
                script_path=pre_script_path,
                script_type="pre_install",
                version=update_version,
                pending_root_dir=PENDING_ROOT_DIR,
                pending_update_dir=PENDING_UPDATE_DIR,
            )

            if not script_success:
                log.info(f"ERROR: Pre-install script failed: {script_msg}")

                # Indicate error on LED
                update_led(indicate_error=True)

                # Mark as incompatible
                mark_incompatible_release(update_version, f"Pre-install script failed: {script_msg}")

                cleanup_pending_update()
                log.info("=" * 50)
                log.info("Update aborted due to pre-install script failure")
                log.info("=" * 50)
                return

            # Update LED after script
            update_led()

        # Step 3: Verify compatibility
        is_compatible, error_msg = check_release_compatibility(manifest, current_version)

        # Update LED during compatibility check
        update_led()

        if not is_compatible:
            log.info(f"ERROR: {error_msg}")

            # Indicate error on LED
            update_led(indicate_error=True)

            # Mark incompatible with detailed reason
            mark_incompatible_release(manifest.get("version", "unknown"), error_msg or "Unknown error")

            cleanup_pending_update()
            log.info("=" * 50)
            log.info("Update aborted due to incompatibility")
            log.info("=" * 50)
            return

        log.info("✓ Compatibility verified")

        # Update LED
        update_led()

        # Step 3.5: Validate extracted update contains all critical files
        # This is a second check before destructive operations begin
        log.info("Validating update package integrity...")
        all_present, missing_files = validate_extracted_update(PENDING_ROOT_DIR)

        if not all_present:
            log.info("ERROR: Update package is incomplete")
            log.info(f"Missing {len(missing_files)} critical files:")
            for missing in missing_files[:10]:
                log.info(f"  - {missing}")
            if len(missing_files) > 10:
                log.info(f"  ... and {len(missing_files) - 10} more")
            log.info("Installation would brick the device - aborting")

            # Indicate error on LED
            update_led(indicate_error=True)

            # Mark as incompatible
            mark_incompatible_release(
                manifest.get("version", "unknown"),
                f"Incomplete package - missing {len(missing_files)} critical files",
            )

            cleanup_pending_update()
            return

        log.info("✓ All critical files present in update package")

        # Update LED after validation
        update_led()

        # Step 4: Verify preserved files exist before destructive operations
        log.info("Verifying preserved files before update...")
        secrets_exists = False
        try:
            with open("/secrets.json") as f:
                secrets_data = f.read()
                secrets_size = len(secrets_data)
            secrets_exists = True
            log.info(f"✓ secrets.json found ({secrets_size} bytes)")
        except OSError:
            log.info("ℹ No secrets.json (first-time setup)")

        # Step 5: Delete everything except secrets, incompatible list, recovery, and DEVELOPMENT flag
        preserve_paths = [
            "/secrets.json",
            "/incompatible_releases.json",
            "/DEVELOPMENT",
            "/recovery",
            PENDING_UPDATE_DIR,
        ]
        delete_all_except(preserve_paths)
        os.sync()  # Sync after deletion

        # Verify preserved files still exist after deletion
        if secrets_exists:
            try:
                with open("/secrets.json") as f:
                    post_delete_data = f.read()
                if post_delete_data != secrets_data:
                    log.info("ERROR: secrets.json was modified during deletion!")
                    raise Exception("Preservation failed - secrets.json corrupted")
                log.info("✓ secrets.json preserved after deletion")
            except OSError as e:
                log.info("ERROR: secrets.json was deleted during cleanup!")
                raise Exception("Preservation failed - secrets.json deleted") from e

        # Update LED after deletion
        update_led()

        # Step 6: Move files from pending_update/root to root
        move_directory_contents(PENDING_ROOT_DIR, "/")
        os.sync()  # Sync after moving all files

        # Verify preserved files still exist after move
        if secrets_exists:
            try:
                with open("/secrets.json") as f:
                    post_move_data = f.read()
                if post_move_data != secrets_data:
                    log.info("ERROR: secrets.json was modified during file move!")
                    raise Exception("File move corrupted secrets.json")
                log.info("✓ secrets.json preserved after file move")
            except OSError as e:
                log.info("ERROR: secrets.json was deleted during file move!")
                raise Exception("File move deleted secrets.json") from e

        # Step 7: Validate critical files are present after installation
        all_present, missing_files = validate_critical_files()

        if not all_present:
            log.info("ERROR: Critical files missing after installation:")
            for missing_file in missing_files:
                log.info(f"  - {missing_file}")
            log.info("Installation incomplete - aborting to prevent broken system")
            # Indicate error on LED
            update_led(indicate_error=True)
            return  # Abort without rebooting - device will boot with old version

        log.info("✓ All critical files validated")

        # Update LED after validation
        update_led()

        # Step 8: Create or update recovery backup
        log.info("Creating recovery backup...")
        try:
            success, backup_msg = create_recovery_backup()
            if success:
                log.info(f"✓ {backup_msg}")
            else:
                log.info(f"⚠ {backup_msg}")
        except Exception as e:
            log.info(f"⚠ Recovery backup failed: {e}")

        # Update LED after backup
        update_led()

        # Step 8.5: Execute post-install script if present
        # Post-install runs AFTER recovery backup is created
        # This ensures device can recover if script fails
        if manifest.get("has_post_install_script", False):
            post_script_path = _get_script_path("post_install", update_version, "")
            log.info("Post-install script indicated in manifest")

            script_success, script_msg = execute_install_script(
                script_path=post_script_path,
                script_type="post_install",
                version=update_version,
                pending_root_dir=PENDING_ROOT_DIR,
                pending_update_dir=PENDING_UPDATE_DIR,
            )

            if not script_success:
                # Post-install failures are non-fatal - log and continue
                log.info(f"WARNING: Post-install script failed: {script_msg}")
                log.info("Continuing with update (recovery backup already created)")
                _write_install_log("WARNING: Post-install script failed but update continues")
            else:
                log.info("✓ Post-install script completed")

            # Update LED after script
            update_led()

        # Step 9: Cleanup pending update directory
        cleanup_pending_update()
        os.sync()  # Sync after cleanup

        # Update LED after cleanup
        update_led()

        log.info("=" * 50)
        log.info(f"Update complete: {current_version} → {manifest.get('version')}")
        log.info("Recovery backup updated")
        log.info("Rebooting...")
        log.info("=" * 50)

        # Sync filesystem before reboot
        os.sync()

        # Reboot
        microcontroller.reset()

    except OSError as e:
        # No pending_update directory - normal boot
        log.info(f"OSError during update check: {e}")
    except Exception as e:
        log.info(f"Error checking for updates: {e}")
        log.info(f"Traceback: {traceback.format_exc()}")


def reset_version_for_ota() -> bool:
    """
    Reset VERSION in settings.toml to 0.0.0 to force OTA update pickup.

    Called after recovery to ensure the device will accept any available update,
    regardless of what version the restored backup was from.

    Reads from recovery/settings.toml (known-good source) rather than root
    settings.toml to avoid filesystem timing issues after restore.

    Uses the same pattern as pre_install scripts: read entire file as string,
    do string replacement, write back.

    Returns:
        bool: True if successful, False otherwise
    """
    log = _boot_file_logger()
    settings_path = "/settings.toml"
    recovery_settings_path = f"{RECOVERY_DIR}/settings.toml"

    try:
        # Read from recovery settings (known-good source after restore)
        # This avoids filesystem timing issues from reading a just-written file
        try:
            with open(recovery_settings_path) as f:
                current_settings_content = f.read()
        except OSError:
            # Fall back to root settings.toml if recovery doesn't have it
            with open(settings_path) as f:
                current_settings_content = f.read()

        # Find and replace VERSION line
        # Try to find existing VERSION line
        try:
            # Extract current version
            current_version = current_settings_content.split('VERSION = "')[1].split('"')[0]
            # Replace it
            updated_settings_content = current_settings_content.replace(
                f'VERSION = "{current_version}"', 'VERSION = "0.0.0"'
            )
        except (IndexError, ValueError):
            # VERSION line not found or malformed, add it at the top
            if "VERSION =" not in current_settings_content:
                updated_settings_content = 'VERSION = "0.0.0"\n' + current_settings_content
            else:
                # Malformed VERSION line, try to replace any VERSION line
                import re

                updated_settings_content = re.sub(
                    r'VERSION\s*=\s*"[^"]*"', 'VERSION = "0.0.0"', current_settings_content
                )

        # Write the updated settings.toml (same pattern as pre_install scripts)
        with open(settings_path, "w") as f:
            f.write(updated_settings_content)

        os.sync()
        return True
    except Exception as e:
        log.info(f"ERROR: Failed to reset VERSION for OTA: {e}")
        return False


def update_led(indicate_error: bool = False) -> None:
    """
    Update LED animation during update installation.

    Memoizes PixelController singleton and handles LED feedback.
    On first call, initializes the controller and starts installation indicator.
    Gracefully handles when PixelController is unavailable.

    Args:
        indicate_error: If True, blink error pattern; otherwise update animation
    """
    global _pixel_controller

    # Initialize PixelController singleton on first call
    if _pixel_controller is None:
        try:
            from controllers.pixel_controller import PixelController

            try:
                _pixel_controller = PixelController()
                # Start installation indicator (blue/green flashing)
                _pixel_controller.indicate_installing()
            except Exception:
                _pixel_controller = None
        except ImportError:
            _pixel_controller = None

    # If no controller available, do nothing
    if _pixel_controller is None:
        return

    try:
        if indicate_error:
            # blink_error is async, but we can't await here in sync context
            # Use set_color for synchronous error indication
            _pixel_controller.set_color((255, 0, 0))
        else:
            _pixel_controller.manual_tick()
    except Exception:
        pass  # Best effort LED updates


def _boot_file_logger() -> Any:
    """Get boot logger instance with file output."""
    global _boot_file_logger_instance
    if _boot_file_logger_instance is None:
        # Lazy import to avoid circular dependency with boot_support
        from core.boot_support import BOOT_LOG_FILE

        _boot_file_logger_instance = logger("wicid.boot", log_file=BOOT_LOG_FILE)
    return _boot_file_logger_instance


def _cleanup_incomplete_staging() -> None:
    """
    Clean up incomplete staging directory if present.

    Called when .staging exists but .ready marker is missing,
    indicating an interrupted download/extraction.
    """
    log = _boot_file_logger()
    try:
        items = os.listdir(PENDING_STAGING_DIR)
        if items:
            log.info("Found incomplete staging directory - cleaning up")
            remove_directory_recursive(PENDING_STAGING_DIR)
    except OSError:
        pass  # No staging directory


def _get_script_path(script_type: str, version: str, base_dir: str = "") -> str:
    """
    Get the expected path for a pre/post install script.

    Args:
        script_type: "pre_install" or "post_install"
        version: Version string (e.g., "0.6.0-b2")
        base_dir: Base directory path (e.g., "/pending_update/root" or "")

    Returns:
        str: Full path to the script file
    """
    script_name = f"{script_type}_v{version}.py"
    if base_dir:
        return f"{base_dir}/{INSTALL_SCRIPTS_DIR}/{script_name}"
    return f"/{INSTALL_SCRIPTS_DIR}/{script_name}"


def _validate_ready_marker() -> bool:
    """
    Validate the .ready marker exists and is not empty.

    The .ready marker signals that staging completed successfully.
    If missing or empty, the update was incomplete and should not be installed.

    Returns:
        bool: True if marker is valid, False otherwise
    """
    try:
        with open(READY_MARKER_FILE) as f:
            content = f.read().strip()
        return len(content) > 0
    except OSError:
        return False


def _write_install_log(message: str, overwrite: bool = False) -> None:
    """
    Write a message to the install log file.

    Args:
        message: Message to write
        overwrite: If True, overwrite the file; otherwise append
    """
    mode = "w" if overwrite else "a"
    try:
        with open(INSTALL_LOG_FILE, mode) as f:
            f.write(message + "\n")
    except Exception:
        pass  # Best effort logging
