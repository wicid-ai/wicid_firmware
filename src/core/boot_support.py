"""
WICID Boot Support Module

This module contains all boot logic that runs before code.py:
1. Storage configuration (disable USB, remount filesystem)
2. Recovery from missing critical files (via recovery utilities)
3. Processing pending firmware updates (full reset strategy)

Boot Flow:
    boot.py → _emergency_recovery() → boot_support.main()
                                            ↓
                                      configure_storage()
                                            ↓
                                 check_and_restore_from_recovery()
                                            ↓
                                    process_pending_update()

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
import traceback

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
    from core.app_typing import Any
    from core.logging_helper import logger  # noqa: F401 - Used later in module
    from utils.recovery import (
        RECOVERY_DIR,
        create_recovery_backup,
        recovery_exists,
        restore_from_recovery,
        validate_critical_files,
        validate_extracted_update,
    )
    from utils.utils import check_release_compatibility, mark_incompatible_release, suppress
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

# -----------------------------------------------------------------------------
# OPTIONAL imports - graceful degradation if these fail
# These provide UX enhancements but are not required for recovery.
# -----------------------------------------------------------------------------
try:
    from controllers.pixel_controller import PixelController
    from managers.update_manager import UpdateManager
except ImportError as e:
    print("=" * 50)
    print(f"WARNING: Optional import failed - {e}")
    print("LED feedback and update staging DISABLED")
    print("Recovery functionality remains available")
    print("=" * 50)
    PixelController = None  # type: ignore
    UpdateManager = None  # type: ignore

# Check for pending firmware update
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"
PENDING_STAGING_DIR = "/pending_update/.staging"
READY_MARKER_FILE = "/pending_update/.ready"
BOOT_LOG_FILE = "/boot_log.txt"
INSTALL_LOG_FILE = "/install.log"
INSTALL_SCRIPTS_DIR = "firmware_install_scripts"
_LOGGED_BOOT_ERROR = False


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


def _reset_version_for_ota() -> bool:
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
        log_boot_message(f"ERROR: Failed to reset VERSION for OTA: {e}")
        return False


def execute_install_script(
    script_path: str,
    script_type: str,
    version: str,
    installer: Any = None,
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
        installer: Optional UpdateInstaller instance for LED feedback
        pending_root_dir: Path to extracted update files
        pending_update_dir: Path to pending update directory

    Returns:
        tuple: (success, message)
    """
    log_boot_message(f"Executing {script_type} script: {script_path}")
    _write_install_log(f"\n{'=' * 50}")
    _write_install_log(f"{script_type.upper()} SCRIPT EXECUTION")
    _write_install_log(f"Script: {script_path}")
    _write_install_log(f"Version: {version}")
    _write_install_log(f"{'=' * 50}")

    # Update LED
    if installer:
        installer.update_led()

    try:
        # Check if script exists
        try:
            os.stat(script_path)
        except OSError:
            msg = f"Script not found: {script_path}"
            log_boot_message(msg)
            _write_install_log(msg)
            return (False, msg)

        # Read script content
        with open(script_path) as f:
            script_content = f.read()

        # Create log function for script to use
        def script_log(message: str) -> None:
            log_boot_message(f"  [{script_type}] {message}")
            _write_install_log(f"  {message}")
            if installer:
                installer.update_led()

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
            log_boot_message(f"ERROR: {msg}")
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
            log_boot_message(f"✓ {msg}")
            _write_install_log(f"SUCCESS: {msg}")
            return (True, msg)
        else:
            msg = f"{script_type} script returned failure"
            log_boot_message(f"✗ {msg}")
            _write_install_log(f"FAILURE: {msg}")
            return (False, msg)

    except Exception as e:
        msg = f"{script_type} script error: {e}"
        log_boot_message(f"ERROR: {msg}")
        _write_install_log(f"ERROR: {msg}")
        # Traceback logging - protect against traceback module issues in CircuitPython
        try:
            tb_str = traceback.format_exc()
            log_boot_message(f"Traceback: {tb_str}")
            _write_install_log(f"Traceback:\n{tb_str}")
        except Exception:
            pass  # Best effort traceback logging
        return (False, msg)


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

    Uses multiple passes to handle FAT filesystem quirks and hidden files.

    Args:
        path: Directory path to remove
        installer: Optional UpdateInstaller instance for LED feedback
    """
    try:
        items = os.listdir(path)
    except OSError:
        # Path doesn't exist or isn't a directory
        return

    # First pass: Remove all files (including hidden files like ._*)
    for item in items:
        item_path = f"{path}/{item}" if not path.endswith("/") else f"{path}{item}"

        # Update LED during file operations
        if installer:
            installer.update_led()

        # Try to remove as file
        with suppress(OSError):
            os.remove(item_path)

    # Second pass: Recurse into directories and remove them
    # Re-list to handle any changes from first pass
    try:
        items = os.listdir(path)
    except OSError:
        return

    for item in items:
        item_path = f"{path}/{item}" if not path.endswith("/") else f"{path}{item}"

        # Update LED
        if installer:
            installer.update_led()

        # Recurse into subdirectories
        remove_directory_recursive(item_path, installer)

        # Try to remove the directory
        with suppress(OSError):
            os.rmdir(item_path)

    # Final pass: Remove the directory itself (with retry)
    for _ in range(3):
        try:
            os.rmdir(path)
            break  # Success
        except OSError:
            # Sync filesystem and retry
            os.sync()
            time.sleep(0.1)


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


def _cleanup_incomplete_staging() -> None:
    """
    Clean up incomplete staging directory if present.

    Called when .staging exists but .ready marker is missing,
    indicating an interrupted download/extraction.
    """
    try:
        items = os.listdir(PENDING_STAGING_DIR)
        if items:
            log_boot_message("Found incomplete staging directory - cleaning up")
            remove_directory_recursive(PENDING_STAGING_DIR)
    except OSError:
        pass  # No staging directory


def process_pending_update() -> None:
    """
    Check for and process pending firmware updates.
    """
    log_boot_message("\n=== BOOT: Checking for pending firmware updates ===")
    log_boot_message(f"Looking for: {PENDING_ROOT_DIR}")

    # Clean up any incomplete staging first
    _cleanup_incomplete_staging()

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

        # Verify the .ready marker exists (atomic staging verification)
        if not _validate_ready_marker():
            log_boot_message("WARNING: Pending update missing .ready marker")
            log_boot_message("Update staging was incomplete - cleaning up")
            cleanup_pending_update()
            return

        log_boot_message("✓ Ready marker validated")
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
            log_boot_message("Pre-install script indicated in manifest")

            script_success, script_msg = execute_install_script(
                script_path=pre_script_path,
                script_type="pre_install",
                version=update_version,
                installer=installer,
                pending_root_dir=PENDING_ROOT_DIR,
                pending_update_dir=PENDING_UPDATE_DIR,
            )

            if not script_success:
                log_boot_message(f"ERROR: Pre-install script failed: {script_msg}")

                # Turn off LED on error
                if installer:
                    installer.turn_off_led()

                # Mark as incompatible
                mark_incompatible_release(update_version, f"Pre-install script failed: {script_msg}")

                cleanup_pending_update()
                log_boot_message("=" * 50)
                log_boot_message("Update aborted due to pre-install script failure")
                log_boot_message("=" * 50)
                return

            # Update LED after script
            if installer:
                installer.update_led()

        # Step 3: Verify compatibility
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
            mark_incompatible_release(manifest.get("version", "unknown"), error_msg or "Unknown error")

            cleanup_pending_update()
            log_boot_message("=" * 50)
            log_boot_message("Update aborted due to incompatibility")
            log_boot_message("=" * 50)
            return

        log_boot_message("✓ Compatibility verified")

        # Update LED
        if installer:
            installer.update_led()

        # Step 3.5: Validate extracted update contains all critical files
        # This is a second check before destructive operations begin
        log_boot_message("Validating update package integrity...")
        all_present, missing_files = validate_extracted_update(PENDING_ROOT_DIR)

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
            mark_incompatible_release(
                manifest.get("version", "unknown"),
                f"Incomplete package - missing {len(missing_files)} critical files",
            )

            cleanup_pending_update()
            return

        log_boot_message("✓ All critical files present in update package")

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
        all_present, missing_files = validate_critical_files()

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
        try:
            success, backup_msg = create_recovery_backup()
            if success:
                log_boot_message(f"✓ {backup_msg}")
            else:
                log_boot_message(f"⚠ {backup_msg}")
        except Exception as e:
            log_boot_message(f"⚠ Recovery backup failed: {e}")

        # Update LED after backup
        if installer:
            installer.update_led()

        # Step 8.5: Execute post-install script if present
        # Post-install runs AFTER recovery backup is created
        # This ensures device can recover if script fails
        if manifest.get("has_post_install_script", False):
            post_script_path = _get_script_path("post_install", update_version, "")
            log_boot_message("Post-install script indicated in manifest")

            script_success, script_msg = execute_install_script(
                script_path=post_script_path,
                script_type="post_install",
                version=update_version,
                installer=installer,
                pending_root_dir=PENDING_ROOT_DIR,
                pending_update_dir=PENDING_UPDATE_DIR,
            )

            if not script_success:
                # Post-install failures are non-fatal - log and continue
                log_boot_message(f"WARNING: Post-install script failed: {script_msg}")
                log_boot_message("Continuing with update (recovery backup already created)")
                _write_install_log("WARNING: Post-install script failed but update continues")
            else:
                log_boot_message("✓ Post-install script completed")

            # Update LED after script
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

    except OSError as e:
        # No pending_update directory - normal boot
        log_boot_message(f"OSError during update check: {e}")
    except Exception as e:
        log_boot_message(f"Error checking for updates: {e}")
        log_boot_message(f"Traceback: {traceback.format_exc()}")


def check_and_restore_from_recovery() -> bool:
    """
    Check for missing critical files and restore from recovery if needed.

    This runs early in boot to catch catastrophic failures from interrupted
    updates or corrupted filesystems. Recovery utilities are guaranteed to be
    available since they're CRITICAL imports (boot.py ensures it via emergency recovery).

    Returns:
        bool: True if recovery was needed and performed, False otherwise
    """
    # Check if all critical files are present
    all_present, missing_files = validate_critical_files()

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

    if not recovery_exists():
        log_boot_message("\n✗ No recovery backup available")
        log_boot_message("Device may not boot correctly")
        log_boot_message("Manual intervention required")
        return False

    # Attempt recovery
    log_boot_message("\n→ Attempting recovery from backup...")
    success, message = restore_from_recovery()

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

        # Reset VERSION to 0.0.0 to force OTA update pickup
        # This ensures the device will accept any available update after recovery
        if _reset_version_for_ota():
            log_boot_message("Reset VERSION to 0.0.0 for OTA pickup")
        else:
            log_boot_message("WARNING: Could not reset VERSION for OTA")

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
