"""
Recovery Manager for WICID firmware.

Handles backup and restoration of critical system files to prevent device bricking
during firmware updates. This module is separate from UpdateManager to isolate
recovery concerns and make the recovery logic reusable.

Critical Files:
    - Boot-critical: Required for boot.py to succeed
    - Runtime-critical: Required for code.py to succeed
    - System-critical: Required for device configuration and updates
    - Network-critical: Required to download updates
    - Update-critical: Required for OTA updates to function
    - Library dependencies: Required by critical modules

Usage:
    # Before installing an update, create a backup
    success, message = RecoveryManager.create_recovery_backup()

    # After installation, validate critical files are present
    all_present, missing = RecoveryManager.validate_critical_files()

    # If boot detects missing files, restore from backup
    success, message = RecoveryManager.restore_from_recovery()
"""

import os
import traceback

from core.app_typing import List
from core.logging_helper import logger
from utils.utils import suppress


class RecoveryManager:
    """Static utility class for managing recovery backups of critical system files."""

    RECOVERY_DIR = "/recovery"
    RECOVERY_INTEGRITY_FILE = "/recovery/.integrity"

    # Files that should NEVER be overwritten during OTA updates
    # Only user-provided data that cannot be regenerated
    PRESERVED_FILES = {
        "secrets.json",  # WiFi credentials and API keys (user-provided)
        "DEVELOPMENT",  # Development mode flag (user-set)
    }

    # BOOT_CRITICAL_FILES: Minimal set for boot.py emergency recovery
    # These are the files that boot.py needs to successfully import boot_support.
    # If ANY of these are missing, boot.py halts before recovery can run.
    # boot.py includes inline emergency recovery for these 4 files only.
    BOOT_CRITICAL_FILES = {
        "/core/boot_support.mpy",  # Imported by boot.py
        "/core/logging_helper.mpy",  # Imported by boot_support (CRITICAL - halts if missing)
        "/core/app_typing.mpy",  # Imported by logging_helper
        "/utils/utils.mpy",  # Imported by boot_support (CRITICAL - halts if missing)
    }

    # CRITICAL_FILES: Full set for boot + OTA self-healing capability
    # Missing any of these prevents the device from downloading/installing updates.
    # This is the MINIMAL set required for boot + OTA recovery (21 files total).
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
        "/managers/recovery_manager.mpy",  # Validates critical files
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

    @classmethod
    def _critical_backup_order(cls) -> List[str]:
        """Return boot-critical files first, followed by remaining critical files."""
        ordered: list[str] = []
        seen: set[str] = set()

        for path in cls.BOOT_CRITICAL_FILES:
            if path not in seen:
                ordered.append(path)
                seen.add(path)

        for path in cls.CRITICAL_FILES:
            if path not in seen:
                ordered.append(path)
                seen.add(path)

        return ordered

    @staticmethod
    def validate_critical_files() -> tuple[bool, List[str]]:
        """
        Validate that all critical system files are present after installation.

        This method is called after moving files during update installation to ensure
        the device will boot and function correctly. Missing critical files will brick
        the device or prevent future updates.

        Returns:
            tuple: (bool, list) - (all_present, missing_files)
                - all_present: True if all critical files exist
                - missing_files: List of missing file paths (empty if all present)
        """
        missing_files = []

        for file_path in RecoveryManager.CRITICAL_FILES:
            try:
                os.stat(file_path)
            except OSError:
                missing_files.append(file_path)

        return (len(missing_files) == 0, missing_files)

    @staticmethod
    def recovery_exists() -> bool:
        """
        Check if recovery backup directory exists and contains files.

        Returns:
            bool: True if recovery backup exists with files
        """
        try:
            files = os.listdir(RecoveryManager.RECOVERY_DIR)
            return len(files) > 0
        except OSError:
            return False

    @staticmethod
    def create_recovery_backup() -> tuple[bool, str]:
        """
        Create or update recovery backup of critical system files.

        Backs up only critical files needed for device to boot and perform updates.
        Recovery backup is persistent and only updated on successful installations.

        Returns:
            tuple: (bool, str) - (success, message)
        """
        log = logger("wicid.recovery")
        try:
            # Create recovery directory if it doesn't exist
            try:
                os.mkdir(RecoveryManager.RECOVERY_DIR)
                log.debug(f"Created recovery directory: {RecoveryManager.RECOVERY_DIR}")
            except OSError:
                pass  # Directory already exists

            backed_up_count = 0
            failed_files = []

            for file_path in RecoveryManager._critical_backup_order():
                try:
                    # Determine if it's a file or directory
                    is_dir = False
                    try:
                        os.listdir(file_path)
                        is_dir = True
                    except (OSError, NotImplementedError):
                        pass

                    if is_dir:
                        # Skip directories (we only backup files)
                        continue

                    # Read source file
                    with open(file_path, "rb") as src:
                        content = src.read()

                    # Construct recovery path with directory structure
                    recovery_path = RecoveryManager.RECOVERY_DIR + file_path
                    recovery_dir = "/".join(recovery_path.split("/")[:-1])

                    # Create parent directories in recovery if needed
                    if recovery_dir and recovery_dir != RecoveryManager.RECOVERY_DIR:
                        parts = recovery_dir.split("/")
                        current_path = ""
                        for part in parts:
                            if not part:
                                continue
                            current_path += "/" + part
                            with suppress(OSError):
                                os.mkdir(current_path)  # Directory already exists

                    # Write to recovery location
                    with open(recovery_path, "wb") as dst:
                        dst.write(content)

                    backed_up_count += 1

                except Exception as e:
                    failed_files.append(f"{file_path}: {e}")

            # Sync filesystem
            os.sync()

            if failed_files:
                message = f"Partial backup: {backed_up_count} files backed up, {len(failed_files)} failed"
                log.warning(message)
                for failure in failed_files:
                    log.warning(f"  - {failure}")
                return (False, message)
            else:
                message = f"Recovery backup complete: {backed_up_count} critical files backed up"
                log.info(message)
                valid, integrity_msg = RecoveryManager.validate_backup_integrity()
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

    @staticmethod
    def restore_from_recovery() -> tuple[bool, str]:
        """
        Restore critical files from recovery backup to root.

        Called when boot detects missing critical files. This is a last-resort
        recovery mechanism to prevent device bricking.

        Returns:
            tuple: (bool, str) - (success, message)
        """
        log = logger("wicid.recovery")
        try:
            if not RecoveryManager.recovery_exists():
                return (False, "No recovery backup found")

            log.critical("=" * 50)
            log.critical("CRITICAL: Restoring from recovery backup")
            log.critical("=" * 50)

            restored_count = 0
            failed_files = []

            for file_path in RecoveryManager._critical_backup_order():
                recovery_path = RecoveryManager.RECOVERY_DIR + file_path

                try:
                    # Check if recovery file exists
                    try:
                        os.stat(recovery_path)
                    except OSError:
                        # File not in recovery, skip
                        continue

                    # Check if it's a directory
                    is_dir = False
                    try:
                        os.listdir(recovery_path)
                        is_dir = True
                    except (OSError, NotImplementedError):
                        pass

                    if is_dir:
                        continue

                    # Read recovery file
                    with open(recovery_path, "rb") as src:
                        content = src.read()

                    # Create parent directories if needed
                    file_dir = "/".join(file_path.split("/")[:-1])
                    if file_dir and file_dir != "/":
                        parts = file_dir.split("/")
                        current_path = ""
                        for part in parts:
                            if not part:
                                continue
                            current_path += "/" + part
                            with suppress(OSError):
                                os.mkdir(current_path)

                    # Write to root location
                    with open(file_path, "wb") as dst:
                        dst.write(content)

                    restored_count += 1
                    log.info(f"Restored: {file_path}")

                except Exception as e:
                    failed_files.append(f"{file_path}: {e}")

            # Sync filesystem
            os.sync()

            log.info("=" * 50)

            if failed_files:
                message = f"Partial recovery: {restored_count} files restored, {len(failed_files)} failed"
                log.warning(message)
                for failure in failed_files:
                    log.warning(f"  - {failure}")
                return (False, message)
            else:
                message = f"Recovery complete: {restored_count} critical files restored"
                log.info(message)
                return (True, message)

        except Exception as e:
            message = f"Recovery restoration failed: {e}"
            log.error(message)
            traceback.print_exception(e)
            return (False, message)

    @staticmethod
    def validate_extracted_update(extracted_dir: str) -> tuple[bool, List[str]]:
        """
        Validate that extracted update contains all critical files.

        Called after extraction but before installation to ensure the update
        package is complete and won't brick the device.

        Args:
            extracted_dir: Directory containing extracted update files

        Returns:
            tuple: (bool, list) - (all_present, missing_files)
        """
        missing_files: List[str] = []

        for file_path in RecoveryManager.CRITICAL_FILES:
            # Convert root path to extracted directory path
            extracted_path = extracted_dir + file_path

            try:
                os.stat(extracted_path)
            except OSError:
                missing_files.append(file_path)

        return (len(missing_files) == 0, missing_files)

    @staticmethod
    def validate_backup_integrity() -> tuple[bool, str]:
        """
        Validate that recovery backup is intact and not corrupted.

        Checks that the recovery directory exists and contains expected files.
        Future enhancement: verify file hashes against stored integrity data.

        Returns:
            tuple: (bool, str) - (valid, message)
        """
        log = logger("wicid.recovery")
        try:
            if not RecoveryManager.recovery_exists():
                return (False, "No recovery backup found")

            # Count files in recovery
            file_count = 0
            for file_path in RecoveryManager.CRITICAL_FILES:
                recovery_path = RecoveryManager.RECOVERY_DIR + file_path
                try:
                    os.stat(recovery_path)
                    file_count += 1
                except OSError:
                    pass

            if file_count == 0:
                return (False, "Recovery backup is empty")

            # Check integrity file if it exists
            try:
                os.stat(RecoveryManager.RECOVERY_INTEGRITY_FILE)
                log.debug("Integrity file found")
            except OSError:
                log.debug("No integrity file (legacy backup)")

            return (True, f"Recovery backup valid: {file_count} files")

        except Exception as e:
            return (False, f"Backup validation failed: {e}")
