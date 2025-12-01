"""Unit tests for RecoveryManager."""

import unittest
from unittest.mock import MagicMock, patch


class TestRecoveryManagerValidateCriticalFiles(unittest.TestCase):
    """Test validate_critical_files static method."""

    def test_all_files_present_returns_true(self) -> None:
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()  # File exists
            from managers.recovery_manager import RecoveryManager

            all_present, missing = RecoveryManager.validate_critical_files()
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_missing_files_returns_false_with_list(self) -> None:
        def stat_side_effect(path: str) -> MagicMock:
            if path == "/boot.py":
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from managers.recovery_manager import RecoveryManager

            all_present, missing = RecoveryManager.validate_critical_files()
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)

    def test_multiple_missing_files(self) -> None:
        missing_paths = {"/boot.py", "/code.py", "/settings.toml"}

        def stat_side_effect(path: str) -> MagicMock:
            if path in missing_paths:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from managers.recovery_manager import RecoveryManager

            all_present, missing = RecoveryManager.validate_critical_files()
            self.assertFalse(all_present)
            for path in missing_paths:
                self.assertIn(path, missing)


class TestRecoveryManagerRecoveryExists(unittest.TestCase):
    """Test recovery_exists static method."""

    def test_recovery_exists_with_files(self) -> None:
        with patch("os.listdir", return_value=["boot.py", "code.py"]):
            from managers.recovery_manager import RecoveryManager

            self.assertTrue(RecoveryManager.recovery_exists())

    def test_recovery_exists_empty_directory(self) -> None:
        with patch("os.listdir", return_value=[]):
            from managers.recovery_manager import RecoveryManager

            self.assertFalse(RecoveryManager.recovery_exists())

    def test_recovery_exists_directory_not_found(self) -> None:
        with patch("os.listdir", side_effect=OSError("Directory not found")):
            from managers.recovery_manager import RecoveryManager

            self.assertFalse(RecoveryManager.recovery_exists())


class TestRecoveryManagerValidateExtractedUpdate(unittest.TestCase):
    """Test validate_extracted_update static method."""

    def test_all_files_present_in_extracted_dir(self) -> None:
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from managers.recovery_manager import RecoveryManager

            all_present, missing = RecoveryManager.validate_extracted_update("/tmp/update")
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_missing_files_in_extracted_dir(self) -> None:
        def stat_side_effect(path: str) -> MagicMock:
            if "/tmp/update/boot.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from managers.recovery_manager import RecoveryManager

            all_present, missing = RecoveryManager.validate_extracted_update("/tmp/update")
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)


class TestRecoveryManagerCreateBackup(unittest.TestCase):
    """Test create_recovery_backup static method."""

    def test_creates_recovery_directory(self) -> None:
        mock_file_content = b"test content"
        mock_open_obj = MagicMock()
        mock_open_obj.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_file_content)))
        mock_open_obj.__exit__ = MagicMock(return_value=False)

        with (
            patch("os.mkdir") as mock_mkdir,
            patch("os.listdir", side_effect=OSError),  # Not a directory
            patch("os.sync"),
            patch("builtins.open", return_value=mock_open_obj),
            patch("core.logging_helper.logger"),
        ):
            from managers.recovery_manager import RecoveryManager

            success, message = RecoveryManager.create_recovery_backup()
            # Should attempt to create recovery directory
            mock_mkdir.assert_called()

    def test_backup_success_message(self) -> None:
        mock_file = MagicMock()
        mock_file.read.return_value = b"content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        with (
            patch("os.mkdir"),
            patch("os.listdir", side_effect=OSError),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("core.logging_helper.logger"),
        ):
            from managers.recovery_manager import RecoveryManager

            success, message = RecoveryManager.create_recovery_backup()
            self.assertTrue(success)
            self.assertIn("complete", message.lower())

    def test_backup_handles_read_errors(self) -> None:
        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            raise OSError("Cannot read file")

        with (
            patch("os.mkdir"),
            patch("os.listdir", side_effect=OSError),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("core.logging_helper.logger"),
        ):
            from managers.recovery_manager import RecoveryManager

            success, message = RecoveryManager.create_recovery_backup()
            # Should return partial success with failures
            self.assertFalse(success)
            self.assertIn("Partial", message)


class TestRecoveryManagerRestoreFromRecovery(unittest.TestCase):
    """Test restore_from_recovery static method."""

    def test_restore_no_backup_found(self) -> None:
        with (
            patch("os.listdir", side_effect=OSError),
            patch("core.logging_helper.logger"),
        ):
            from managers.recovery_manager import RecoveryManager

            success, message = RecoveryManager.restore_from_recovery()
            self.assertFalse(success)
            self.assertIn("No recovery backup found", message)

    def test_restore_success(self) -> None:
        mock_file = MagicMock()
        mock_file.read.return_value = b"content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        def mock_stat(path: str) -> MagicMock:
            return MagicMock()  # File exists

        with (
            patch("os.listdir", return_value=["boot.py"]),  # Recovery exists
            patch("os.stat", side_effect=mock_stat),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("core.logging_helper.logger"),
        ):
            from managers.recovery_manager import RecoveryManager

            success, message = RecoveryManager.restore_from_recovery()
            self.assertTrue(success)
            self.assertIn("complete", message.lower())


class TestRecoveryManagerCriticalFiles(unittest.TestCase):
    """Test CRITICAL_FILES constant."""

    def test_critical_files_includes_boot_files(self) -> None:
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/boot.py", RecoveryManager.CRITICAL_FILES)
        self.assertIn("/code.py", RecoveryManager.CRITICAL_FILES)

    def test_critical_files_includes_settings(self) -> None:
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/settings.toml", RecoveryManager.CRITICAL_FILES)

    def test_critical_files_includes_manifest(self) -> None:
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/manifest.json", RecoveryManager.CRITICAL_FILES)


class TestRecoveryManagerMinimalSet(unittest.TestCase):
    """Test that CRITICAL_FILES contains the minimal set for boot + OTA recovery."""

    def test_critical_files_count(self) -> None:
        """Critical files should be exactly 20 files (minimal OTA recovery set)."""
        from managers.recovery_manager import RecoveryManager

        # The minimal set for boot + OTA capability is exactly 20 files
        self.assertEqual(len(RecoveryManager.CRITICAL_FILES), 20)

    def test_boot_chain_is_complete(self) -> None:
        """Boot chain files must all be present for device to start."""
        from managers.recovery_manager import RecoveryManager

        boot_chain = [
            "/boot.py",
            "/core/boot_support.mpy",
            "/core/app_typing.mpy",
            "/core/logging_helper.mpy",
            "/utils/utils.mpy",
            "/code.py",
            "/core/code_support.mpy",
            "/core/scheduler.mpy",
        ]
        for path in boot_chain:
            self.assertIn(path, RecoveryManager.CRITICAL_FILES, f"Missing boot chain file: {path}")

    def test_ota_chain_is_complete(self) -> None:
        """OTA update chain files must all be present for self-healing."""
        from managers.recovery_manager import RecoveryManager

        ota_chain = [
            "/managers/manager_base.mpy",
            "/managers/system_manager.mpy",
            "/managers/update_manager.mpy",
            "/managers/recovery_manager.mpy",
            "/managers/connection_manager.mpy",
            "/controllers/wifi_radio_controller.mpy",
            "/utils/zipfile_lite.mpy",
        ]
        for path in ota_chain:
            self.assertIn(path, RecoveryManager.CRITICAL_FILES, f"Missing OTA chain file: {path}")

    def test_library_dependencies_are_complete(self) -> None:
        """Library dependencies required by OTA chain must be present."""
        from managers.recovery_manager import RecoveryManager

        lib_deps = [
            "/lib/adafruit_requests.mpy",
            "/lib/adafruit_connection_manager.mpy",
            "/lib/adafruit_hashlib/__init__.mpy",
        ]
        for path in lib_deps:
            self.assertIn(path, RecoveryManager.CRITICAL_FILES, f"Missing library: {path}")

    def test_config_files_are_present(self) -> None:
        """Configuration files required for boot and updates must be present."""
        from managers.recovery_manager import RecoveryManager

        config_files = ["/settings.toml", "/manifest.json"]
        for path in config_files:
            self.assertIn(path, RecoveryManager.CRITICAL_FILES, f"Missing config file: {path}")

    def test_unnecessary_files_are_not_included(self) -> None:
        """Files not required for OTA recovery should NOT be in CRITICAL_FILES."""
        from managers.recovery_manager import RecoveryManager

        # These are nice-to-have but not required for boot + OTA
        unnecessary = [
            "/controllers/pixel_controller.mpy",  # LED feedback, not critical
            "/lib/neopixel.mpy",  # Only needed for pixel_controller
        ]
        for path in unnecessary:
            self.assertNotIn(path, RecoveryManager.CRITICAL_FILES, f"Unnecessary file included: {path}")


class TestRecoveryManagerIntegrity(unittest.TestCase):
    """Test recovery backup integrity features."""

    def test_backup_includes_integrity_metadata(self) -> None:
        """Recovery backup should track file hashes for corruption detection."""
        from managers.recovery_manager import RecoveryManager

        # Verify the integrity file constant exists
        self.assertTrue(hasattr(RecoveryManager, "RECOVERY_INTEGRITY_FILE"))

    def test_validate_backup_integrity_exists(self) -> None:
        """Method to validate backup integrity should exist."""
        from managers.recovery_manager import RecoveryManager

        self.assertTrue(hasattr(RecoveryManager, "validate_backup_integrity"))

    def test_validate_backup_integrity_returns_tuple(self) -> None:
        """validate_backup_integrity returns (valid, message) tuple."""
        with (
            patch("os.stat") as mock_stat,
            patch("builtins.open", MagicMock()),
            patch("os.listdir", return_value=["boot.py"]),
        ):
            mock_stat.return_value = MagicMock()
            from managers.recovery_manager import RecoveryManager

            result = RecoveryManager.validate_backup_integrity()
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)


class TestPreservedFiles(unittest.TestCase):
    """Test PRESERVED_FILES constant for user data protection."""

    def test_preserved_files_includes_secrets(self) -> None:
        """secrets.json must always be preserved."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("secrets.json", RecoveryManager.PRESERVED_FILES)

    def test_preserved_files_includes_development(self) -> None:
        """DEVELOPMENT flag should be preserved."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("DEVELOPMENT", RecoveryManager.PRESERVED_FILES)

    def test_preserved_files_is_minimal(self) -> None:
        """Only user-provided data should be preserved."""
        from managers.recovery_manager import RecoveryManager

        # Only secrets.json and DEVELOPMENT should be preserved
        self.assertEqual(len(RecoveryManager.PRESERVED_FILES), 2)


class TestBootCriticalFiles(unittest.TestCase):
    """Test BOOT_CRITICAL_FILES constant for emergency recovery in boot.py."""

    def test_boot_critical_files_exists(self) -> None:
        """BOOT_CRITICAL_FILES constant should exist for emergency recovery."""
        from managers.recovery_manager import RecoveryManager

        self.assertTrue(hasattr(RecoveryManager, "BOOT_CRITICAL_FILES"))

    def test_boot_critical_files_is_subset_of_critical(self) -> None:
        """BOOT_CRITICAL_FILES should be a subset of CRITICAL_FILES."""
        from managers.recovery_manager import RecoveryManager

        for path in RecoveryManager.BOOT_CRITICAL_FILES:
            self.assertIn(
                path,
                RecoveryManager.CRITICAL_FILES,
                f"BOOT_CRITICAL file {path} not in CRITICAL_FILES",
            )

    def test_boot_critical_files_minimal_count(self) -> None:
        """BOOT_CRITICAL_FILES should be minimal (4 files for boot chain only)."""
        from managers.recovery_manager import RecoveryManager

        # Only the files needed for boot.py to successfully import boot_support
        self.assertEqual(len(RecoveryManager.BOOT_CRITICAL_FILES), 4)

    def test_boot_critical_includes_boot_support(self) -> None:
        """boot_support.mpy must be in BOOT_CRITICAL for boot.py to work."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/core/boot_support.mpy", RecoveryManager.BOOT_CRITICAL_FILES)

    def test_boot_critical_includes_logging_helper(self) -> None:
        """logging_helper.mpy must be in BOOT_CRITICAL (boot_support imports it)."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/core/logging_helper.mpy", RecoveryManager.BOOT_CRITICAL_FILES)

    def test_boot_critical_includes_app_typing(self) -> None:
        """app_typing.mpy must be in BOOT_CRITICAL (logging_helper imports it)."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/core/app_typing.mpy", RecoveryManager.BOOT_CRITICAL_FILES)

    def test_boot_critical_includes_utils(self) -> None:
        """utils.mpy must be in BOOT_CRITICAL (boot_support imports it)."""
        from managers.recovery_manager import RecoveryManager

        self.assertIn("/utils/utils.mpy", RecoveryManager.BOOT_CRITICAL_FILES)


if __name__ == "__main__":
    unittest.main()
