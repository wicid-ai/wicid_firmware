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

import microcontroller

from core.app_typing import Any, List
from core.logging_helper import WicidLogger, logger
from utils.recovery import CRITICAL_FILES, create_recovery_backup, validate_files
from utils.utils import (
    check_release_compatibility,
    mark_incompatible_release,
    remove_directory_recursive,
    suppress,
)

# Path constants for pending update directory structure
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"
PENDING_STAGING_DIR = "/pending_update/.staging"
READY_MARKER_FILE = "/pending_update/.ready"
INSTALL_SCRIPTS_DIR = "firmware_install_scripts"

# Files/directories that should NEVER be deleted during OTA updates
# Only user-provided data that cannot be regenerated
PRESERVED_FILES = {
    "boot_log.txt",  # Boot log file
    "secrets.json",  # WiFi credentials and API keys (user-provided)
    "incompatible_releases.json",  # Failed update tracking (user data)
    "DEVELOPMENT",  # Development mode flag (user-set)
}

# Directories that must be preserved during full firmware replacement
PRESERVED_DIRS = {
    "recovery",  # Recovery backup for rollback
}


def process_pending_update() -> None:
    """
    Check for and process pending firmware updates.

    This is the main entry point for update installation during boot.
    Called from boot_support.py after recovery checks complete.
    """
    _boot_file_logger().info(f"\n=== BOOT: Checking for pending firmware updates ===\nLooking for: {PENDING_ROOT_DIR}")

    _cleanup_incomplete_staging()

    try:
        if not _pending_update_exists():
            _boot_file_logger().info("No pending update found - proceeding with normal boot")
            return

        # Signal update detected
        _update_led()

        # Load manifest and version info
        manifest, update_version = _load_pending_manifest()
        if manifest is None:
            return

        current_version = _get_current_version()
        _boot_file_logger().info(
            f"WICID Firmware Update: {current_version} → {update_version} (timestamp: {time.monotonic()})"
        )

        # Execute pre-install script (runs before validation)
        if not _run_install_script_step(manifest, "pre_install", update_version, is_fatal=True):
            return

        if _handle_script_only_release(manifest, current_version, update_version):
            return

        # Verify compatibility (full releases only)
        if not _verify_compatibility(manifest, current_version):
            return

        # Validate package integrity (full releases only)
        if not _validate_package_integrity(manifest):
            return

        # Delete old firmware and install new files
        _delete_all_except(_get_preserved_paths())
        os.sync()
        _update_led()

        _move_directory_contents(PENDING_ROOT_DIR, "/")
        os.sync()

        # Create recovery backup
        _create_recovery_backup()

        # Execute post-install script (non-fatal)
        _run_install_script_step(manifest, "post_install", update_version, is_fatal=False)

        # Complete update
        _cleanup_and_reboot_system(current_version, update_version, is_script_only=False)

    except OSError as e:
        _boot_file_logger().debug(f"OSError during update check: {e}")
    except Exception as e:
        _boot_file_logger().error(f"Error checking for updates: {e}\nTraceback: {traceback.format_exc()}")


def _boot_file_logger() -> WicidLogger:
    """Get boot logger instance with file output."""
    global _boot_file_logger_instance
    if _boot_file_logger_instance is None:
        # Lazy import to avoid circular dependency with boot_support
        from core.boot_support import BOOT_LOG_FILE

        _boot_file_logger_instance = logger("wicid.update_install", log_file=BOOT_LOG_FILE)
    return _boot_file_logger_instance


def _cleanup_and_reboot_system(current_version: str, update_version: str, is_script_only: bool = False) -> None:
    """Final cleanup, logging, and system reboot."""
    _cleanup_pending_update()
    os.sync()
    _update_led()

    update_type = "Script-only update" if is_script_only else "Update"
    _boot_file_logger().info(
        f"{'=' * 50}\n{update_type} complete: {current_version} → {update_version}\nRebooting...\n{'=' * 50}"
    )

    os.sync()
    microcontroller.reset()


def _cleanup_incomplete_staging() -> None:
    """
    Clean up incomplete staging directory if present.

    Called when .staging exists but .ready marker is missing,
    indicating an interrupted download/extraction.
    """
    try:
        items = os.listdir(PENDING_STAGING_DIR)
        if items:
            _boot_file_logger().info("Found incomplete staging directory - cleaning up")
            remove_directory_recursive(PENDING_STAGING_DIR)
    except OSError:
        pass  # No staging directory


def _cleanup_pending_update() -> None:
    """
    Remove pending update directory and all its contents.
    Logs errors but continues to attempt cleanup.
    """
    _boot_file_logger().info("Cleaning up pending update...")

    try:
        remove_directory_recursive(PENDING_UPDATE_DIR)
        _boot_file_logger().info("✓ Cleanup complete")
    except Exception as e:
        _boot_file_logger().error(f"Cleanup error: {e}")


def _create_recovery_backup() -> None:
    """Create recovery backup with error handling and logging."""
    try:
        success, msg = create_recovery_backup()
        _boot_file_logger().info(f"✓ {msg}" if success else f"Recovery backup failed: {msg}")
    except Exception as e:
        _boot_file_logger().error(f"Recovery backup failed: {e}")
    _update_led()


def _delete_all_except(preserve_paths: list[str]) -> None:
    """
    Delete all files and directories in root except specified paths.
    Forces recursive deletion but logs errors and continues.

    Args:
        preserve_paths: List of paths to preserve (e.g., ['/secrets.json', '/pending_update'])
    """
    _boot_file_logger().info("Performing full reset (deleting all existing files)...")

    # Normalize preserve paths (case-insensitive for FAT32 filesystem)
    preserve_set = {path.rstrip("/").lower() for path in preserve_paths}

    # Get list of all items in root
    root_items = os.listdir("/")

    for item in root_items:
        item_path = f"/{item}"

        # Update LED during file operations
        _update_led()

        # Skip preserved paths (case-insensitive comparison for FAT32)
        if item_path.lower() in preserve_set:
            _boot_file_logger().info(f"  Preserved: {item_path}")
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
            _boot_file_logger().error(f"  Error processing {item_path}: {e}")

    _boot_file_logger().info("✓ Full reset complete")


def _execute_install_script(
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
    _boot_file_logger().info(f"Executing {script_type} script v{version}")
    _update_led()

    try:
        # Check if script exists
        try:
            os.stat(script_path)
        except OSError:
            msg = f"Script not found: {script_path}"
            _boot_file_logger().error(msg)
            return (False, msg)

        # Read script content
        with open(script_path) as f:
            script_content = f.read()

        # Create log function for script to use (direct file write)
        from core.boot_support import BOOT_LOG_FILE

        def script_log(message: str) -> None:
            try:
                with open(BOOT_LOG_FILE, "a") as f:
                    f.write(message + "\n")
            except Exception:
                pass  # Best effort logging to boot log

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
            _boot_file_logger().error(msg)
            return (False, msg)

        # Call main() with appropriate arguments
        if script_type == "pre_install":
            result = script_globals["main"](script_log, pending_root_dir, pending_update_dir)
        else:  # post_install
            result = script_globals["main"](script_log, version)

        # Interpret result
        if result is True or result is None:
            msg = f"{script_type} script completed successfully"
            _boot_file_logger().info(f"✓ {msg}")
            return (True, msg)
        else:
            msg = f"{script_type} script returned failure"
            _boot_file_logger().error(msg)
            return (False, msg)

    except Exception as e:
        msg = f"{script_type} script error: {e}"
        _boot_file_logger().error(msg)
        with suppress(Exception):
            _boot_file_logger().error(f"Traceback: {traceback.format_exc()}")
        return (False, msg)


# Memoized PixelController singleton for LED feedback
_pixel_controller: Any = None

# Memoized boot logger instance
_boot_file_logger_instance: WicidLogger | None = None


def _get_current_version() -> str:
    """Get current firmware version from environment."""
    try:
        return os.getenv("VERSION", "0.0.0")
    except Exception:
        return "0.0.0"


def _get_preserved_paths() -> list[str]:
    """
    Get list of absolute paths to preserve during firmware replacement.

    Includes user files, system data, and the pending update itself.
    """
    paths = [f"/{name}" for name in PRESERVED_FILES]
    paths.extend(f"/{name}" for name in PRESERVED_DIRS)
    paths.append(PENDING_UPDATE_DIR)
    return paths


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


def _handle_script_only_release(manifest: dict[str, Any], current_version: str, update_version: str) -> bool:
    """
    Handle script-only releases - skip validation and reboot immediately
    """
    if manifest.get("script_only_release", False):
        _boot_file_logger().info("Script-only release - updating settings.toml version and cleaning up")
        _update_settings_toml(current_version, update_version)
        _cleanup_and_reboot_system(current_version, update_version, is_script_only=True)
        return True
    return False


def _handle_update_error(version: str, error_msg: str) -> None:
    """
    Centralize error handling for update failures.

    Args:
        version: Update version that failed
        error_msg: Detailed error message
    """
    _update_led(indicate_error=True)
    mark_incompatible_release(version, error_msg)
    _cleanup_pending_update()
    _boot_file_logger().error(f"{'=' * 50}\nUpdate aborted: {error_msg}\n{'=' * 50}")


def _load_pending_manifest() -> tuple[dict[str, Any] | None, str]:
    """
    Load and return the manifest from pending update.

    Returns:
        tuple: (manifest_dict, update_version) or (None, "") on error
    """
    try:
        with open(f"{PENDING_ROOT_DIR}/manifest.json") as f:
            manifest = json.load(f)
        update_version = manifest.get("version", "unknown")
        _boot_file_logger().info(f"✓ Manifest loaded (version: {update_version})")
        return manifest, update_version
    except Exception as e:
        _boot_file_logger().error(f"Could not load manifest: {e}\nTraceback: {traceback.format_exc()}")
        _cleanup_pending_update()
        return None, ""


def _move_directory_contents(src_dir: str, dest_dir: str) -> None:
    """
    Move all files and directories from src to dest.
    Logs errors but continues to attempt moving remaining files.

    CRITICAL: Never overwrites preserved files (secrets.json, etc.)

    Args:
        src_dir: Source directory path
        dest_dir: Destination directory path
    """
    _boot_file_logger().info(f"Moving files from {src_dir} to {dest_dir}...")

    items = os.listdir(src_dir)

    for item in items:
        src_path = f"{src_dir}/{item}"
        dest_path = f"{dest_dir}/{item}"

        # Update LED during file operations
        _update_led()

        # Skip preserved files - never overwrite them during OTA updates
        # Use case-insensitive comparison for FAT32 filesystem compatibility
        if dest_dir == "/" and item.lower() in [f.lower() for f in PRESERVED_FILES]:
            _boot_file_logger().info(f"  Skipping preserved file: {item}")
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
                _move_directory_contents(src_path, dest_path)

                # Remove source directory
                try:
                    os.rmdir(src_path)
                except OSError as e:
                    _boot_file_logger().error(f"  Could not remove {src_path}: {e}")
            else:
                # Move file
                try:
                    # Additional safety check: never overwrite preserved files
                    # Extract filename from dest_path for checking
                    dest_filename = dest_path.split("/")[-1]
                    if dest_filename.lower() in [f.lower() for f in PRESERVED_FILES]:
                        _boot_file_logger().critical(f"Attempted to overwrite preserved file: {dest_filename}")
                        _boot_file_logger().critical(f"  Source: {src_path}")
                        _boot_file_logger().critical(f"  Destination: {dest_path}")
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
                    _boot_file_logger().error(f"  Could not move {src_path}: {e}")

        except Exception as e:
            _boot_file_logger().error(f"  Error processing {item}: {e}")

    _boot_file_logger().info("✓ File move complete")


def _pending_update_exists() -> bool:
    """
    Check if pending update directory exists and is ready for installation.

    Returns:
        bool: True if a valid pending update exists, False otherwise
    """
    try:
        files = os.listdir(PENDING_ROOT_DIR)
    except OSError:
        return False

    if not files:
        _boot_file_logger().info("Pending update directory is empty - cleaning up")
        _cleanup_pending_update()
        return False

    if not _validate_ready_marker():
        _boot_file_logger().warning("Pending update missing .ready marker - staging incomplete, cleaning up")
        _cleanup_pending_update()
        return False

    _boot_file_logger().info(
        f"✓ Ready marker validated ({len(files)} files)\n{'=' * 50}\nFIRMWARE UPDATE DETECTED\n{'=' * 50}"
    )
    return True


def _run_install_script_step(
    manifest: dict[str, Any],
    script_type: str,
    update_version: str,
    is_fatal: bool = True,
) -> bool:
    """
    Run install script step if indicated in manifest.

    Wrapper around execute_install_script() that checks manifest and handles errors.

    Args:
        manifest: Update manifest
        script_type: "pre_install" or "post_install"
        update_version: Version being installed
        is_fatal: If True, failure aborts update; if False, logs warning and continues

    Returns:
        bool: True if successful or not needed, False if script failed (and is_fatal=True)
    """
    script_key = f"has_{script_type}_script"
    if not manifest.get(script_key, False):
        return True

    base_dir = PENDING_ROOT_DIR if script_type == "pre_install" else ""
    script_path = _get_script_path(script_type, update_version, base_dir)

    script_success, script_msg = _execute_install_script(
        script_path=script_path,
        script_type=script_type,
        version=update_version,
        pending_root_dir=PENDING_ROOT_DIR,
        pending_update_dir=PENDING_UPDATE_DIR,
    )

    if not script_success:
        if is_fatal:
            _handle_update_error(update_version, f"{script_type} script failed: {script_msg}")
            return False
        else:
            _boot_file_logger().warning(f"{script_type} script failed: {script_msg} (continuing with update)")

    _update_led()
    return script_success


def _update_led(indicate_error: bool = False) -> None:
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


def _update_settings_toml(current_version: str, update_version: str) -> None:
    """
    Update settings.toml version to the new update version, using CircuitPython safe file operations
    """
    with open("settings.toml") as f:
        settings = f.read()
    settings = settings.replace(f'VERSION = "{current_version}"', f'VERSION = "{update_version}"')
    with open("settings.toml", "w") as f:
        f.write(settings)
    os.sync()


def _validate_package_integrity(manifest: dict[str, Any]) -> bool:
    """
    Validate extracted update contains all critical files.

    Script-only releases skip file validation as they don't need firmware files.

    Returns:
        bool: True if valid, False otherwise
    """
    # Script-only releases only need manifest.json
    if manifest.get("script_only_release", False):
        all_present: bool = True
        missing_files: List[str] = []
    else:
        all_present, missing_files = validate_files(PENDING_ROOT_DIR, CRITICAL_FILES)

    if not all_present:
        files_summary = ", ".join(missing_files[:5])
        if len(missing_files) > 5:
            files_summary += f" ...and {len(missing_files) - 5} more"
        _boot_file_logger().critical(
            f"Update package incomplete - missing {len(missing_files)} critical files: {files_summary}"
        )

        _handle_update_error(
            manifest.get("version", "unknown"), f"Incomplete package - missing {len(missing_files)} critical files"
        )
        return False

    _boot_file_logger().info("✓ Package integrity validated")
    _update_led()
    return True


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


def _verify_compatibility(manifest: dict[str, Any], current_version: str) -> bool:
    """
    Verify update is compatible with current system.

    Returns:
        bool: True if compatible, False otherwise
    """
    is_compatible, error_msg = check_release_compatibility(manifest, current_version)

    if not is_compatible:
        _handle_update_error(manifest.get("version", "unknown"), error_msg or "Unknown compatibility error")
        return False

    _boot_file_logger().info("✓ Compatibility verified")
    _update_led()
    return True
