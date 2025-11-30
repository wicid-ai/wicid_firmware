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


if __name__ == "__main__":
    unittest.main()
