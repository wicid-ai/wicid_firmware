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


class TestRecoveryBackupClearsStaleFiles(TestCase):
    """Test that recovery backup clears stale files before creating new backup."""

    STALE_FILE = "/recovery/stale_file_that_should_be_removed.txt"

    @classmethod
    def setUpClass(cls) -> None:
        """Create a stale file in recovery directory before backup."""
        # Ensure recovery directory exists
        try:  # noqa: SIM105
            os.mkdir("/recovery")
        except OSError:
            pass

        # Create a stale file that shouldn't survive backup
        with open(cls.STALE_FILE, "w") as f:
            f.write("This file should be removed during backup")
        os.sync()

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up /recovery/ directory."""
        _rmtree("/recovery")
        try:  # noqa: SIM105
            os.sync()
        except (OSError, AttributeError):
            pass

    def test_backup_removes_stale_files(self) -> None:
        """Stale files should be removed when creating a fresh backup."""
        from utils.recovery import create_recovery_backup

        # Verify stale file exists before backup
        try:
            os.stat(self.STALE_FILE)
        except OSError:
            self.fail("Stale file should exist before backup test")

        # Create recovery backup - this should clear the stale file
        success, message = create_recovery_backup()
        self.assertTrue(success, f"Backup failed: {message}")

        # Verify stale file was removed
        try:
            os.stat(self.STALE_FILE)
            self.fail("Stale file should have been removed during backup")
        except OSError:
            pass  # Expected - file should be gone


class TestRecoveryBackup(TestCase):
    """Test recovery backup creation, contents, and integrity."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create recovery backup once for all tests in this class."""
        from utils.recovery import create_recovery_backup

        success, message = create_recovery_backup()
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
        from utils.recovery import _recovery_exists

        self.assertTrue(_recovery_exists(), "Recovery backup should exist")

    def test_backup_contains_critical_files(self) -> None:
        """Recovery backup contains all CRITICAL_FILES with non-zero size."""
        from utils.recovery import CRITICAL_FILES, RECOVERY_DIR

        for path in CRITICAL_FILES:
            recovery_path = RECOVERY_DIR + path
            try:
                stat = os.stat(recovery_path)
                self.assertTrue(stat[6] > 0, f"Recovery file is empty: {recovery_path}")
            except OSError:
                self.fail(f"Critical file missing from recovery: {path}")

    def test_backup_integrity_passes(self) -> None:
        """Backup integrity validation passes after fresh backup."""
        from utils.recovery import _validate_backup_integrity

        valid, message = _validate_backup_integrity()
        self.assertTrue(valid, f"Integrity check failed: {message}")


class TestRecoveryValidation(TestCase):
    """Test critical file validation."""

    def test_validate_files_passes_on_healthy_system(self) -> None:
        """All critical files should be present on a healthy system."""
        from utils.recovery import validate_files

        all_present, missing = validate_files("")
        self.assertTrue(all_present, f"Missing critical files: {missing}")


class TestCriticalFilesPresence(TestCase):
    """Test that all critical files are present on the device."""

    def test_all_critical_files_exist(self) -> None:
        """Every file in CRITICAL_FILES should exist on device."""
        from utils.recovery import CRITICAL_FILES

        missing = []
        for path in CRITICAL_FILES:
            try:
                os.stat(path)
            except OSError:
                missing.append(path)

        self.assertEqual(missing, [], f"Missing critical files: {missing}")

    def test_critical_files_are_not_empty(self) -> None:
        """Critical files should not be empty (0 bytes)."""
        from utils.recovery import CRITICAL_FILES

        empty_files = []
        for path in CRITICAL_FILES:
            try:
                stat = os.stat(path)
                if stat[6] == 0:  # st_size
                    empty_files.append(path)
            except OSError:
                pass  # Missing files tested elsewhere

        self.assertEqual(empty_files, [], f"Empty critical files: {empty_files}")


class TestValidateFilesIntegration(TestCase):
    """
    Test validate_files function in real CircuitPython environment.

    This integration test verifies the actual CircuitPython behavior that unit tests
    cannot catch, specifically:
    - File operations work as expected in the real environment
    - Path handling works correctly with different base directories
    """

    TEST_DIR = "/test_validate_files"

    @classmethod
    def setUpClass(cls) -> None:
        """Create test directory for validation tests."""
        try:  # noqa: SIM105
            os.mkdir(cls.TEST_DIR)
        except OSError:
            pass
        os.sync()

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up test directory."""
        _rmtree(cls.TEST_DIR)
        try:  # noqa: SIM105
            os.sync()
        except (OSError, AttributeError):
            pass

    def test_validate_files_fails_without_files(self) -> None:
        """validate_files correctly detects missing files in empty directory."""
        from utils.recovery import CRITICAL_FILES, validate_files

        # Validate empty directory - should fail
        all_present, missing = validate_files(self.TEST_DIR, CRITICAL_FILES)
        self.assertFalse(all_present, "Empty directory should fail validation")
        self.assertTrue(len(missing) > 0, "Should report missing critical files")


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
