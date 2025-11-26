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

    # Critical files that MUST exist for device to boot and function
    # Missing any of these will brick the device or prevent updates
    CRITICAL_FILES = {
        # Boot-critical: Required for boot.py to succeed
        "/boot.py",  # CircuitPython requires source .py file
        "/core/boot_support.mpy",  # Imported by boot.py
        # Runtime-critical: Required for code.py to succeed
        "/code.py",  # CircuitPython requires source .py file
        "/core/code_support.mpy",  # Imported by code.py
        # System-critical: Required for device configuration and updates
        "/settings.toml",  # System configuration, loaded at boot
        "/manifest.json",  # Update metadata, validated during installation
        "/utils/utils.mpy",  # Compatibility checks, device identification
        "/controllers/pixel_controller.mpy",  # LED feedback during boot and updates
        "/managers/system_manager.mpy",  # Periodic system checks (update checks, reboots)
        # Network-critical: Required to download updates
        "/managers/connection_manager.mpy",  # WiFi connection for OTA downloads
        "/controllers/wifi_radio_controller.mpy",  # Hardware abstraction required by connection_manager
        # Update-critical: Required for OTA updates to function
        "/utils/zipfile_lite.mpy",  # Required to extract update ZIPs
        "/managers/update_manager.mpy",  # Required for update checks and downloads
        "/managers/recovery_manager.mpy",  # Required for backup/restore operations
        # Library dependencies: Required by critical modules
        "/lib/neopixel.mpy",  # Required by pixel_controller.mpy
        "/lib/adafruit_requests.mpy",  # Required by connection_manager.mpy for HTTP
        "/lib/adafruit_connection_manager.mpy",  # Required by adafruit_requests
        "/lib/adafruit_hashlib/__init__.mpy",  # Required by update_manager.mpy for checksum verification
    }

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

            for file_path in RecoveryManager.CRITICAL_FILES:
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

            for file_path in RecoveryManager.CRITICAL_FILES:
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
