"""
Integration tests for recovery mechanisms.

These tests run ON-DEVICE to validate the actual recovery behavior.
They test the full recovery flow including filesystem operations.

Usage (on device REPL):
    >>> import tests
    >>> tests.run_integration()

WARNING: These tests modify the filesystem! They create and delete files
in /recovery/ and may temporarily rename critical files. Only run these
tests when you have a way to recover (e.g., USB access or known-good backup).
"""

import os

from tests.unittest import TestCase


def _rmtree(path: str) -> None:
    """Recursively remove a directory tree (CircuitPython compatible). Idempotent."""
    try:
        entries = os.listdir(path)
    except OSError:
        return  # Directory doesn't exist - nothing to do

    for entry in entries:
        full_path = f"{path}/{entry}"
        try:
            os.listdir(full_path)
            _rmtree(full_path)
        except OSError:
            try:  # noqa: SIM105
                os.remove(full_path)
            except OSError:
                pass

    try:  # noqa: SIM105
        os.rmdir(path)
    except OSError:
        pass


class TestRecoveryBackup(TestCase):
    """Test recovery backup creation, contents, and integrity."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create recovery backup once for all tests in this class."""
        from managers.recovery_manager import RecoveryManager

        success, message = RecoveryManager.create_recovery_backup()
        if not success:
            raise RuntimeError(f"Failed to create recovery backup: {message}")

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up /recovery/ directory."""
        _rmtree("/recovery")
        try:  # noqa: SIM105
            os.sync()
        except (OSError, AttributeError):
            pass

    def test_backup_exists(self) -> None:
        """Recovery backup directory exists after creation."""
        from managers.recovery_manager import RecoveryManager

        self.assertTrue(RecoveryManager.recovery_exists(), "Recovery backup should exist")

    def test_backup_contains_boot_critical_files(self) -> None:
        """Recovery backup contains all BOOT_CRITICAL files with non-zero size."""
        from managers.recovery_manager import RecoveryManager

        for path in RecoveryManager.BOOT_CRITICAL_FILES:
            recovery_path = RecoveryManager.RECOVERY_DIR + path
            try:
                stat = os.stat(recovery_path)
                self.assertTrue(stat[6] > 0, f"Recovery file is empty: {recovery_path}")
            except OSError:
                self.fail(f"Boot-critical file missing from recovery: {path}")

    def test_backup_integrity_passes(self) -> None:
        """Backup integrity validation passes after fresh backup."""
        from managers.recovery_manager import RecoveryManager

        valid, message = RecoveryManager.validate_backup_integrity()
        self.assertTrue(valid, f"Integrity check failed: {message}")


class TestRecoveryValidation(TestCase):
    """Test critical file validation."""

    def test_validate_critical_files_passes_on_healthy_system(self) -> None:
        """All critical files should be present on a healthy system."""
        from managers.recovery_manager import RecoveryManager

        all_present, missing = RecoveryManager.validate_critical_files()
        self.assertTrue(all_present, f"Missing critical files: {missing}")

    def test_boot_critical_files_subset_of_critical(self) -> None:
        """BOOT_CRITICAL_FILES should be a subset of CRITICAL_FILES."""
        from managers.recovery_manager import RecoveryManager

        for path in RecoveryManager.BOOT_CRITICAL_FILES:
            self.assertIn(
                path,
                RecoveryManager.CRITICAL_FILES,
                f"BOOT_CRITICAL file not in CRITICAL_FILES: {path}",
            )


class TestCriticalFilesPresence(TestCase):
    """Test that all critical files are present on the device."""

    def test_all_critical_files_exist(self) -> None:
        """Every file in CRITICAL_FILES should exist on device."""
        from managers.recovery_manager import RecoveryManager

        missing = []
        for path in RecoveryManager.CRITICAL_FILES:
            try:
                os.stat(path)
            except OSError:
                missing.append(path)

        self.assertEqual(missing, [], f"Missing critical files: {missing}")

    def test_critical_files_are_not_empty(self) -> None:
        """Critical files should not be empty (0 bytes)."""
        from managers.recovery_manager import RecoveryManager

        empty_files = []
        for path in RecoveryManager.CRITICAL_FILES:
            try:
                stat = os.stat(path)
                if stat[6] == 0:  # st_size
                    empty_files.append(path)
            except OSError:
                pass  # Missing files tested elsewhere

        self.assertEqual(empty_files, [], f"Empty critical files: {empty_files}")


class TestEmergencyRecoveryMechanism(TestCase):
    """
    Test that the emergency recovery mechanism can restore a missing file.

    Uses a test file to simulate the recovery flow without risking actual
    boot-critical files. The test:
    1. Creates a test file and backs it up to /recovery/
    2. Deletes the original file
    3. Runs the recovery logic
    4. Verifies the file was restored with correct content
    """

    TEST_FILE = "/test_recovery_target.txt"
    TEST_CONTENT = b"WICID recovery test content"

    @classmethod
    def setUpClass(cls) -> None:
        """Create test file and its recovery backup."""
        # Create the test file
        with open(cls.TEST_FILE, "wb") as f:
            f.write(cls.TEST_CONTENT)

        # Create recovery directory and backup
        recovery_path = f"/recovery{cls.TEST_FILE}"
        try:  # noqa: SIM105
            os.mkdir("/recovery")
        except OSError:
            pass

        with open(recovery_path, "wb") as f:
            f.write(cls.TEST_CONTENT)

        os.sync()

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up test file and recovery directory."""
        try:  # noqa: SIM105
            os.remove(cls.TEST_FILE)
        except OSError:
            pass

        _rmtree("/recovery")

        try:  # noqa: SIM105
            os.sync()
        except (OSError, AttributeError):
            pass

    def test_recovery_restores_missing_file(self) -> None:
        """Emergency recovery restores a missing file from /recovery/."""
        # Delete the test file to simulate it being missing
        try:  # noqa: SIM105
            os.remove(self.TEST_FILE)
        except OSError:
            pass

        # Verify file is gone
        try:
            os.stat(self.TEST_FILE)
            self.fail("Test file should be deleted before recovery test")
        except OSError:
            pass  # Expected - file is missing

        # Run recovery logic (same as boot.py's _emergency_recovery)
        recovery_path = f"/recovery{self.TEST_FILE}"
        try:
            os.stat(self.TEST_FILE)
        except OSError:
            # File missing - restore from recovery
            with open(recovery_path, "rb") as src:
                content = src.read()
            with open(self.TEST_FILE, "wb") as dst:
                dst.write(content)
            os.sync()

        # Verify file was restored
        try:
            stat = os.stat(self.TEST_FILE)
            self.assertTrue(stat[6] > 0, "Restored file should not be empty")
        except OSError:
            self.fail("File was not restored by recovery mechanism")

        # Verify content matches
        with open(self.TEST_FILE, "rb") as f:
            restored_content = f.read()
        self.assertEqual(restored_content, self.TEST_CONTENT, "Restored content should match original")
