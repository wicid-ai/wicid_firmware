"""Unit tests for recovery utilities."""

import unittest
from unittest.mock import MagicMock, patch


class TestValidateFiles(unittest.TestCase):
    """Test unified validate_files function."""

    def test_validates_critical_files_in_root_by_default(self) -> None:
        """validate_files uses CRITICAL_FILES by default when files=None."""
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import CRITICAL_FILES, validate_files

            all_present, missing = validate_files("")
            self.assertTrue(all_present)
            self.assertEqual(missing, [])
            # Verify it checked all CRITICAL_FILES
            self.assertEqual(mock_stat.call_count, len(CRITICAL_FILES))

    def test_validates_custom_files_when_provided(self) -> None:
        """validate_files validates custom file set when provided."""
        custom_files = {"/boot.py", "/code.py", "/custom.py"}

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import validate_files

            all_present, missing = validate_files("", custom_files)
            self.assertTrue(all_present)
            self.assertEqual(missing, [])
            # Verify it checked only custom files
            self.assertEqual(mock_stat.call_count, len(custom_files))

    def test_validates_files_in_subdirectory(self) -> None:
        """validate_files validates files in specified base directory."""
        test_files = {"/boot.py", "/code.py"}

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import validate_files

            all_present, missing = validate_files("/tmp/update", test_files)
            self.assertTrue(all_present)
            self.assertEqual(missing, [])
            # Verify it checked the correct paths
            mock_stat.assert_any_call("/tmp/update/boot.py")
            mock_stat.assert_any_call("/tmp/update/code.py")

    def test_detects_missing_files(self) -> None:
        """validate_files detects missing files correctly."""
        test_files = {"/boot.py", "/code.py", "/missing.py"}

        def stat_side_effect(path: str) -> MagicMock:
            if "missing.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from utils.recovery import validate_files

            all_present, missing = validate_files("/tmp", test_files)
            self.assertFalse(all_present)
            self.assertIn("/missing.py", missing)
            self.assertNotIn("/boot.py", missing)
            self.assertNotIn("/code.py", missing)

    def test_validates_recovery_directory(self) -> None:
        """validate_files can validate recovery backup directory."""
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import RECOVERY_DIR, validate_files

            all_present, missing = validate_files(RECOVERY_DIR)
            self.assertTrue(all_present)
            # Verify it checked recovery paths
            mock_stat.assert_any_call(f"{RECOVERY_DIR}/boot.py")

    def test_empty_base_dir_handles_root_paths(self) -> None:
        """validate_files with empty base_dir correctly handles root paths."""
        test_files = {"/boot.py", "/code.py"}

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import validate_files

            all_present, missing = validate_files("", test_files)
            self.assertTrue(all_present)
            # Verify it checked root paths directly
            mock_stat.assert_any_call("/boot.py")
            mock_stat.assert_any_call("/code.py")


class TestRecoveryExists(unittest.TestCase):
    """Test _recovery_exists private function."""

    def test_recovery_exists_with_files(self) -> None:
        with patch("os.listdir", return_value=["boot.py", "code.py"]):
            from utils.recovery import _recovery_exists

            self.assertTrue(_recovery_exists())

    def test_recovery_exists_empty_directory(self) -> None:
        with patch("os.listdir", return_value=[]):
            from utils.recovery import _recovery_exists

            self.assertFalse(_recovery_exists())

    def test_recovery_exists_directory_not_found(self) -> None:
        with patch("os.listdir", side_effect=OSError("Directory not found")):
            from utils.recovery import _recovery_exists

            self.assertFalse(_recovery_exists())


class TestCopyCriticalFiles(unittest.TestCase):
    """Test _copy_critical_files helper function."""

    def test_copies_all_critical_files(self) -> None:
        """_copy_critical_files copies all files from src to dst."""
        mock_content = b"file content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_file = MagicMock()
            if "rb" in mode:
                mock_file.read.return_value = mock_content
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        with (
            patch("os.listdir", side_effect=OSError),  # Not a directory
            patch("os.stat", return_value=MagicMock()),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("utils.recovery.CRITICAL_FILES", {"/boot.py", "/code.py"}),
        ):
            from utils.recovery import _copy_critical_files

            count, failures = _copy_critical_files("", "/recovery")
            self.assertEqual(count, 2)
            self.assertEqual(len(failures), 0)

    def test_skips_directories(self) -> None:
        """_copy_critical_files skips directory entries."""
        mock_content = b"file content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_file = MagicMock()
            if "rb" in mode:
                mock_file.read.return_value = mock_content
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        def mock_listdir(path: str) -> list[str]:
            if path == "/lib":
                return ["file1.mpy"]  # Directory exists
            raise OSError("Not a directory")

        with (
            patch("os.listdir", side_effect=mock_listdir),
            patch("os.stat", return_value=MagicMock()),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("utils.recovery.CRITICAL_FILES", {"/boot.py", "/lib"}),
        ):
            from utils.recovery import _copy_critical_files

            count, failures = _copy_critical_files("", "/recovery")
            # Should skip /lib (directory) and copy /boot.py
            self.assertEqual(count, 1)
            self.assertEqual(len(failures), 0)

    def test_creates_parent_directories(self) -> None:
        """_copy_critical_files creates parent directories as needed."""
        mock_content = b"file content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_file = MagicMock()
            if "rb" in mode:
                mock_file.read.return_value = mock_content
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        with (
            patch("os.listdir", side_effect=OSError),
            patch("os.stat", return_value=MagicMock()),
            patch("os.mkdir") as mock_mkdir,
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("utils.recovery.CRITICAL_FILES", {"/core/boot_support.mpy"}),
        ):
            from utils.recovery import _copy_critical_files

            count, failures = _copy_critical_files("", "/recovery")
            # Should create /recovery/core directory
            mock_mkdir.assert_any_call("/recovery/core")
            self.assertEqual(count, 1)
            self.assertEqual(len(failures), 0)

    def test_handles_read_errors(self) -> None:
        """_copy_critical_files handles file read errors gracefully."""

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            if "rb" in mode and "boot.py" in path:
                raise OSError("Cannot read file")
            mock_file = MagicMock()
            if "rb" in mode:
                mock_file.read.return_value = b"content"
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        with (
            patch("os.listdir", side_effect=OSError),
            patch("os.stat", return_value=MagicMock()),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("utils.recovery.CRITICAL_FILES", {"/boot.py", "/code.py"}),
        ):
            from utils.recovery import _copy_critical_files

            count, failures = _copy_critical_files("", "/recovery")
            # Should copy code.py successfully, fail on boot.py
            self.assertEqual(count, 1)
            self.assertEqual(len(failures), 1)
            self.assertIn("/boot.py", failures[0])


class TestRestoreFromRecovery(unittest.TestCase):
    """Test _restore_from_recovery private function."""

    def test_restore_success(self) -> None:
        """_restore_from_recovery successfully restores files."""
        from utils import recovery

        mock_file = MagicMock()
        mock_file.read.return_value = b"content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        def mock_stat(path: str) -> MagicMock:
            return MagicMock()  # File exists

        def mock_listdir(path: str) -> list[str]:
            if path == "/recovery":
                return ["boot.py"]  # Recovery exists
            raise OSError("Not a directory")

        with (
            patch("os.stat", side_effect=mock_stat),
            patch("os.listdir", side_effect=mock_listdir),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch.object(recovery, "_recovery_exists", return_value=True),
            patch.object(
                recovery, "validate_files", return_value=(False, ["/boot.py", "/code.py"])
            ),  # Files missing initially
            patch.object(recovery, "_copy_critical_files", return_value=(2, [])),  # All files restored successfully
            patch.object(recovery, "CRITICAL_FILES", {"/boot.py", "/code.py"}),
        ):
            mock_log = MagicMock()
            success, message = recovery._restore_from_recovery(mock_log)
            self.assertTrue(success)
            self.assertIn("complete", message.lower())
            # Should log critical messages
            self.assertTrue(mock_log.critical.called)

    def test_restore_logs_error_when_no_recovery_backup(self) -> None:
        """_restore_from_recovery logs ERROR when no recovery backup exists."""
        from utils import recovery

        with patch("os.listdir", side_effect=OSError("Directory not found")):
            mock_log = MagicMock()
            success, message = recovery._restore_from_recovery(mock_log)
            self.assertFalse(success)
            self.assertIn("No recovery backup", message)
            # Should log at ERROR level
            mock_log.error.assert_called()

    def test_restore_logs_critical_when_files_missing(self) -> None:
        """_restore_from_recovery logs CRITICAL when critical files are missing."""
        from utils import recovery

        with (
            patch.object(recovery, "validate_files", return_value=(False, ["/boot.py"])),
            patch.object(recovery, "_recovery_exists", return_value=True),
            patch.object(recovery, "_copy_critical_files", return_value=(0, ["/boot.py: File not found"])),
            patch("os.sync"),
        ):
            mock_log = MagicMock()
            success, message = recovery._restore_from_recovery(mock_log)
            self.assertFalse(success)
            # Should log missing files at CRITICAL level
            mock_log.critical.assert_called()

    def test_restore_handles_missing_recovery_files(self) -> None:
        """_restore_from_recovery skips files not in recovery."""
        from utils import recovery

        mock_file = MagicMock()
        mock_file.read.return_value = b"content"

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        def mock_stat(path: str) -> MagicMock:
            if "/recovery/code.py" in path:
                raise OSError("File not in recovery")
            return MagicMock()

        def mock_listdir(path: str) -> list[str]:
            if path == "/recovery":
                return ["boot.py"]  # Recovery exists
            raise OSError("Not a directory")

        with (
            patch("os.stat", side_effect=mock_stat),
            patch("os.listdir", side_effect=mock_listdir),
            patch("os.mkdir"),
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch.object(recovery, "_recovery_exists", return_value=True),
            patch.object(
                recovery, "validate_files", return_value=(False, ["/boot.py", "/code.py"])
            ),  # Files missing initially
            patch.object(
                recovery, "_copy_critical_files", return_value=(1, [])
            ),  # Only boot.py restored (code.py skipped)
            patch.object(recovery, "CRITICAL_FILES", {"/boot.py", "/code.py"}),
        ):
            mock_log = MagicMock()
            success, message = recovery._restore_from_recovery(mock_log)
            # Should restore boot.py, skip code.py (code.py not in recovery)
            self.assertTrue(success)
            self.assertIn("complete", message.lower())

    def test_restore_returns_early_when_all_files_present(self) -> None:
        """_restore_from_recovery returns early when all critical files are present."""
        from utils import recovery

        with (
            patch.object(recovery, "_recovery_exists", return_value=True),
            patch.object(recovery, "validate_files", return_value=(True, [])),
        ):
            mock_log = MagicMock()
            success, message = recovery._restore_from_recovery(mock_log)
            self.assertTrue(success)
            self.assertEqual("All critical files present in root directory. No recovery needed.", message)
            # Should log at DEBUG level, not CRITICAL
            mock_log.debug.assert_any_call("All critical files present in root directory. No recovery needed.")
            # Should NOT call critical since no recovery was needed
            mock_log.critical.assert_not_called()


class TestCheckAndRestoreFromRecovery(unittest.TestCase):
    """Test check_and_restore_from_recovery orchestrator function."""

    def test_returns_false_when_all_files_present(self) -> None:
        """check_and_restore_from_recovery returns False when no recovery needed."""
        with (
            patch("utils.recovery.validate_files", return_value=(True, [])),
            patch("utils.recovery.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)
            # Should return early without calling restore
            mock_log.info.assert_not_called()
            mock_log.error.assert_not_called()
            mock_log.critical.assert_not_called()

    def test_delegates_to_restore_when_files_missing(self) -> None:
        """check_and_restore_from_recovery delegates to _restore_from_recovery when files missing."""
        with (
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery._restore_from_recovery", return_value=(True, "Restored 20 files")) as mock_restore,
            patch("utils.recovery.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertTrue(result)
            # Should delegate to _restore_from_recovery
            mock_restore.assert_called_once()

    def test_returns_false_when_restore_fails(self) -> None:
        """check_and_restore_from_recovery returns False when restore fails."""
        with (
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery._restore_from_recovery", return_value=(False, "Recovery failed")),
            patch("utils.recovery.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)


class TestCreateRecoveryBackup(unittest.TestCase):
    """Test create_recovery_backup function."""

    def test_clears_directory_before_backup(self) -> None:
        """Recovery directory should be cleared before creating fresh backup."""
        mock_file_content = b"test content"
        mock_open_obj = MagicMock()
        mock_open_obj.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_file_content)))
        mock_open_obj.__exit__ = MagicMock(return_value=False)

        with (
            patch("os.mkdir"),
            patch("os.listdir", side_effect=OSError),  # Not a directory
            patch("os.sync"),
            patch("builtins.open", return_value=mock_open_obj),
            patch("utils.recovery.logger"),
            patch("utils.recovery._clear_recovery_directory") as mock_clear,
        ):
            from utils.recovery import create_recovery_backup

            create_recovery_backup()
            mock_clear.assert_called_once()

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
            patch("utils.recovery.logger"),
        ):
            from utils.recovery import create_recovery_backup

            success, message = create_recovery_backup()
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
            patch("utils.recovery.logger"),
        ):
            from utils.recovery import create_recovery_backup

            success, message = create_recovery_backup()
            self.assertTrue(success)
            self.assertIn("complete", message.lower())

    def test_backup_handles_read_errors(self) -> None:
        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            if "rb" in mode:
                raise OSError("Cannot read file")
            # Return mock for write operations
            mock_file = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_file)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        with (
            patch("os.mkdir"),
            patch("os.listdir", side_effect=OSError),  # Not a directory
            patch("os.stat", return_value=MagicMock()),  # File exists
            patch("os.sync"),
            patch("builtins.open", side_effect=mock_open_func),
            patch("utils.recovery.logger"),
            patch("utils.recovery.CRITICAL_FILES", {"/boot.py", "/code.py"}),
        ):
            from utils.recovery import create_recovery_backup

            success, message = create_recovery_backup()
            # Should return partial success with failures
            self.assertFalse(success)
            self.assertIn("Partial", message)


class TestValidateBackupIntegrity(unittest.TestCase):
    """Test _validate_backup_integrity private function."""

    def test_validates_using_validate_files(self) -> None:
        """_validate_backup_integrity uses validate_files internally."""
        with (
            patch("utils.recovery._recovery_exists", return_value=True),
            patch("utils.recovery.validate_files", return_value=(True, [])) as mock_validate,
            patch("os.stat", return_value=MagicMock()),
            patch("utils.recovery.logger"),
        ):
            from utils.recovery import CRITICAL_FILES, RECOVERY_DIR, _validate_backup_integrity

            valid, message = _validate_backup_integrity()
            self.assertTrue(valid)
            # Should call validate_files with RECOVERY_DIR
            mock_validate.assert_called_once_with(RECOVERY_DIR, CRITICAL_FILES)

    def test_returns_false_when_backup_incomplete(self) -> None:
        """_validate_backup_integrity returns False when files are missing."""
        with (
            patch("utils.recovery._recovery_exists", return_value=True),
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery.logger"),
        ):
            from utils.recovery import _validate_backup_integrity

            valid, message = _validate_backup_integrity()
            self.assertFalse(valid)
            self.assertIn("incomplete", message.lower())

    def test_returns_tuple(self) -> None:
        """_validate_backup_integrity returns (valid, message) tuple."""
        with (
            patch("utils.recovery._recovery_exists", return_value=True),
            patch("utils.recovery.validate_files", return_value=(True, [])),
            patch("os.stat", return_value=MagicMock()),
            patch("utils.recovery.logger"),
        ):
            from utils.recovery import _validate_backup_integrity

            result = _validate_backup_integrity()
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)


class TestCriticalFilesConstant(unittest.TestCase):
    """Test CRITICAL_FILES constant."""

    def test_critical_files_includes_boot_files(self) -> None:
        from utils.recovery import CRITICAL_FILES

        self.assertIn("/boot.py", CRITICAL_FILES)
        self.assertIn("/code.py", CRITICAL_FILES)

    def test_critical_files_includes_settings(self) -> None:
        from utils.recovery import CRITICAL_FILES

        self.assertIn("/settings.toml", CRITICAL_FILES)

    def test_critical_files_includes_manifest(self) -> None:
        from utils.recovery import CRITICAL_FILES

        self.assertIn("/manifest.json", CRITICAL_FILES)

    def test_critical_files_count(self) -> None:
        """Critical files should be exactly 21 files (minimal OTA recovery set)."""
        from utils.recovery import CRITICAL_FILES

        self.assertEqual(len(CRITICAL_FILES), 21)


class TestBootCriticalAlignment(unittest.TestCase):
    """Test that boot.py's _BOOT_CRITICAL aligns with CRITICAL_FILES."""

    def _get_boot_critical_from_source(self) -> list[str]:
        """Parse boot.py to extract the _BOOT_CRITICAL list."""
        import ast
        from pathlib import Path

        boot_py_path = Path(__file__).parent.parent.parent / "src" / "boot.py"
        with open(boot_py_path) as f:
            content = f.read()

        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "_BOOT_CRITICAL"
                        and isinstance(node.value, ast.List)
                    ):
                        return [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
        return []

    def test_boot_critical_is_subset_of_critical_files(self) -> None:
        """boot.py's _BOOT_CRITICAL must be a subset of CRITICAL_FILES."""
        from utils.recovery import CRITICAL_FILES

        boot_critical = self._get_boot_critical_from_source()
        self.assertTrue(len(boot_critical) > 0, "Could not parse _BOOT_CRITICAL from boot.py")

        for path in boot_critical:
            self.assertIn(
                path,
                CRITICAL_FILES,
                f"boot.py _BOOT_CRITICAL file {path} not in CRITICAL_FILES",
            )

    def test_boot_critical_count(self) -> None:
        """boot.py _BOOT_CRITICAL should have exactly 5 files for recovery chain."""
        boot_critical = self._get_boot_critical_from_source()
        # 5 files: boot_support, app_typing, logging_helper, utils, recovery
        self.assertEqual(len(boot_critical), 5, f"Expected 5 files, got {len(boot_critical)}: {boot_critical}")


if __name__ == "__main__":
    unittest.main()
