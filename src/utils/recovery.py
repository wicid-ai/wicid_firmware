"""
Recovery utilities for WICID firmware.

Handles backup and restoration of critical system files to prevent device bricking
during firmware updates, and self-healing from catastrophic failures.
"""

import os
import traceback

from core.app_typing import List
from core.logging_helper import WicidLogger, logger
from utils.utils import remove_directory_recursive, suppress

RECOVERY_DIR = "/recovery"
RECOVERY_INTEGRITY_FILE = "/recovery/.integrity"

# CRITICAL_FILES: Complete set for boot + OTA self-healing capability.
# Missing any of these prevents the device from downloading/installing updates.
# This is the MINIMAL set required for boot + OTA recovery.
CRITICAL_FILES = {
    # === BOOT CHAIN (device won't start without these) ===
    "/boot.py",  # CircuitPython requires source .py file
    "/core/boot_support.mpy",  # Imported by boot.py
    "/core/app_typing.mpy",  # Required by many modules
    "/core/logging_helper.mpy",  # CRITICAL: boot_support halts without it
    "/utils/utils.mpy",  # CRITICAL: boot_support halts without it
    "/code.py",  # CircuitPython requires source .py file
    "/core/code_support.mpy",  # Imported by code.py
    "/core/scheduler.mpy",  # Required by managers
    # === OTA CHAIN (can't self-heal without these) ===
    "/managers/manager_base.mpy",  # Required by all managers
    "/managers/system_manager.mpy",  # Triggers periodic update checks
    "/managers/update_manager.mpy",  # Downloads and stages updates
    "/utils/recovery.mpy",  # Validates critical files
    "/utils/update_install.mpy",  # Processes pending updates
    "/managers/connection_manager.mpy",  # WiFi + HTTP
    "/controllers/wifi_radio_controller.mpy",  # WiFi hardware
    "/utils/zipfile_lite.mpy",  # Extracts ZIP files
    # === LIBRARIES (OTA dependencies) ===
    "/lib/adafruit_requests.mpy",  # HTTP client
    "/lib/adafruit_connection_manager.mpy",  # Socket pooling (required by adafruit_requests)
    "/lib/adafruit_hashlib/__init__.mpy",  # Checksum verification
    # === CONFIG ===
    "/settings.toml",  # WiFi credentials, API URLs
    "/manifest.json",  # Current version info
}


def check_and_restore_from_recovery(log_file: str | None = None) -> bool:
    """
    Check for missing critical files and restore from recovery if needed.

    This runs early in boot to catch catastrophic failures from interrupted
    updates or corrupted filesystems. Recovery utilities are guaranteed to be
    available since they're CRITICAL imports (boot.py ensures it via emergency recovery).

    Args:
        log_file: Optional file path to write logs to (in addition to stdout)

    Returns:
        bool: True if recovery was needed and performed, False otherwise
    """
    log = logger("wicid.recovery", log_file=log_file)
    log.debug("Checking for missing critical files")
    # Check if all critical files are present
    all_present, _ = validate_files("")

    if all_present:
        return False

    # Delegate to _restore_from_recovery which handles all logging and error reporting
    success, _ = _restore_from_recovery(log)
    return success


def create_recovery_backup() -> tuple[bool, str]:
    """
    Create a fresh recovery backup of critical system files.

    Clears any existing backup first to ensure no stale files remain,
    then backs up only critical files needed for device to boot and perform updates.
    Recovery backup is persistent and only updated on successful installations.

    Returns:
        tuple: (bool, str) - (success, message)
    """
    log = logger("wicid.recovery")
    try:
        # Clear existing recovery directory to remove stale files
        _clear_recovery_directory()
        log.debug("Cleared existing recovery directory")

        # Create fresh recovery directory
        try:
            os.mkdir(RECOVERY_DIR)
            log.debug(f"Created recovery directory: {RECOVERY_DIR}")
        except OSError:
            pass  # Directory already exists (shouldn't happen after clear)

        # Copy critical files to recovery
        backed_up_count, failed_files = _copy_critical_files("", RECOVERY_DIR)

        # Sync filesystem
        os.sync()

        if failed_files:
            message = f"Partial backup: {backed_up_count} files backed up, {len(failed_files)} failed"
            log.error(message)
            for failure in failed_files:
                log.error(f"  - {failure}")
            return (False, message)
        else:
            message = f"Recovery backup complete: {backed_up_count} critical files backed up"
            log.info(message)
            valid, integrity_msg = _validate_backup_integrity()
            if not valid:
                log.warning(f"Integrity check after backup failed: {integrity_msg}")
            else:
                log.debug(f"Integrity check passed: {integrity_msg}")
            return (True, message)

    except Exception as e:
        message = f"Recovery backup failed: {e}"
        log.error(message)
        traceback.print_exception(e)
        return (False, message)


def validate_files(base_dir: str, files: set[str] | None = None) -> tuple[bool, List[str]]:
    """
    Validate that all specified files exist in a directory.

    Args:
        base_dir: Base directory path (empty string for root, "/recovery" for recovery, etc.)
        files: Set of file paths to validate. Defaults to CRITICAL_FILES if None.

    Returns:
        tuple: (all_present, missing_files)
            - all_present: True if all files exist
            - missing_files: List of missing file paths (empty if all present)
    """
    if files is None:
        files = CRITICAL_FILES

    missing_files = []

    for file_path in files:
        full_path = base_dir + file_path if base_dir else file_path
        try:
            os.stat(full_path)
        except OSError:
            missing_files.append(file_path)

    return (len(missing_files) == 0, missing_files)


def _clear_recovery_directory() -> None:
    """
    Clear the recovery directory to ensure a fresh backup.

    Removes all existing files and subdirectories in /recovery/ to prevent
    stale files from accumulating when CRITICAL_FILES changes.
    """
    # Use shared utility function
    remove_directory_recursive(RECOVERY_DIR)
    os.sync()


def _copy_critical_files(src_base: str, dst_base: str) -> tuple[int, List[str]]:
    """
    Copy all critical files from src_base to dst_base.

    Handles directory creation, skipping directories, and error handling.
    Used by both create_recovery_backup() and _restore_from_recovery().

    Args:
        src_base: Source base directory (empty string for root, "/recovery" for recovery)
        dst_base: Destination base directory (empty string for root, "/recovery" for recovery)

    Returns:
        tuple: (success_count, list of failure_messages)
    """
    copied_count = 0
    failed_files = []

    for file_path in CRITICAL_FILES:
        src_path = src_base + file_path if src_base else file_path
        dst_path = dst_base + file_path if dst_base else file_path

        try:
            # Check if source file exists
            try:
                os.stat(src_path)
            except OSError:
                # File not in source, skip
                continue

            # Skip directories (try listdir - if it works, it's a directory)
            try:
                os.listdir(src_path)
                continue
            except (OSError, NotImplementedError):
                pass  # Not a directory, continue

            # Read source file
            with open(src_path, "rb") as src:
                content = src.read()

            # Ensure parent directories exist in destination
            file_dir = "/".join(dst_path.split("/")[:-1])
            if file_dir and file_dir != "/":
                parts = file_dir.split("/")
                current_path = ""
                for part in parts:
                    if not part:
                        continue
                    current_path += "/" + part
                    with suppress(OSError):
                        os.mkdir(current_path)

            # Write to destination
            with open(dst_path, "wb") as dst:
                dst.write(content)

            copied_count += 1

        except Exception as e:
            failed_files.append(f"{file_path}: {e}")

    return (copied_count, failed_files)


def _recovery_exists() -> bool:
    """
    Check if recovery backup directory exists and contains files.

    Returns:
        bool: True if recovery backup exists with files
    """
    try:
        files = os.listdir(RECOVERY_DIR)
        return len(files) > 0
    except OSError:
        return False


def _restore_from_recovery(log: WicidLogger) -> tuple[bool, str]:
    """
    Restore critical files from recovery backup to root.

    Handles all logging and error reporting for recovery operations.
    Called by check_and_restore_from_recovery() when files are missing.

    Args:
        log: WicidLogger instance for logging

    Returns:
        tuple: (bool, str) - (success, message)
    """
    log.debug("Restoring from recovery backup")

    # Check if recovery backup exists
    if not _recovery_exists():
        log.error("=" * 50)
        log.error("No recovery backup available")
        log.error("=" * 50)
        log.error("This may occur if there has been no OTA update since the initial installation, ")
        log.error("or if a more significant error has occurred.")
        log.error("Manual intervention may be required.")
        return (False, "No recovery backup found")

    log.debug("Recovery backup exists. Identifying missing critical files in root directory.")
    # Check which files are missing
    all_present, missing_files = validate_files("")

    if not all_present:
        log.critical("=" * 50)
        log.critical("CRITICAL: Missing critical files detected")
        log.critical("=" * 50)
        log.critical(f"Missing {len(missing_files)} critical files:")
        for missing in missing_files[:10]:  # Show first 10
            log.critical(f"  - {missing}")
        if len(missing_files) > 10:
            log.critical(f"  ... and {len(missing_files) - 10} more")

        try:
            log.critical("=" * 50)
            log.critical("CRITICAL: Restoring from recovery backup")
            log.critical("=" * 50)

            # Copy critical files from recovery to root
            restored_count, failed_files = _copy_critical_files(RECOVERY_DIR, "")

            # Sync filesystem
            os.sync()

            log.critical("=" * 50)

            if failed_files:
                message = f"Partial recovery: {restored_count} files restored, {len(failed_files)} failed"
                log.critical(message)
                for failure in failed_files:
                    log.critical(f"  - {failure}")
                log.critical("Manual intervention required")
                return (False, message)
            else:
                message = f"Recovery complete: {restored_count} critical files restored"
                log.critical(f"✓ {message}")
                log.critical("Device recovered successfully")
                log.critical("Continuing with normal boot")
                return (True, message)

        except Exception as e:
            message = f"Recovery restoration failed: {e}"
            log.critical(message)
            log.critical("Manual intervention required")
            traceback.print_exception(e)
            return (False, message)
    else:
        log.debug("All critical files present in root directory. No recovery needed.")
        return (True, "All critical files present in root directory. No recovery needed.")


def _validate_backup_integrity() -> tuple[bool, str]:
    """
    Validate that recovery backup is intact and not corrupted.

    Checks that the recovery directory exists and contains expected files.
    Future enhancement: verify file hashes against stored integrity data.

    Returns:
        tuple: (bool, str) - (valid, message)
    """
    log = logger("wicid.recovery")
    try:
        if not _recovery_exists():
            return (False, "No recovery backup found")

        # Validate using unified validate_files function
        all_present, missing = validate_files(RECOVERY_DIR, CRITICAL_FILES)

        if not all_present:
            return (False, f"Recovery backup incomplete: {len(missing)} files missing")

        # Check integrity file if it exists
        try:
            os.stat(RECOVERY_INTEGRITY_FILE)
            log.debug("Integrity file found")
        except OSError:
            log.debug("No integrity file (legacy backup)")

        return (True, f"Recovery backup valid: {len(CRITICAL_FILES)} files")

    except Exception as e:
        return (False, f"Backup validation failed: {e}")
