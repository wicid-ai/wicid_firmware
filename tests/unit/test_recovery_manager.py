"""Unit tests for recovery utilities."""

import json
import unittest
from unittest.mock import MagicMock, patch


class TestRecoveryValidateCriticalFiles(unittest.TestCase):
    """Test validate_critical_files function."""

    def test_all_files_present_returns_true(self) -> None:
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()  # File exists
            from utils.recovery import validate_critical_files

            all_present, missing = validate_critical_files()
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_missing_files_returns_false_with_list(self) -> None:
        def stat_side_effect(path: str) -> MagicMock:
            if path == "/boot.py":
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from utils.recovery import validate_critical_files

            all_present, missing = validate_critical_files()
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)

    def test_multiple_missing_files(self) -> None:
        missing_paths = {"/boot.py", "/code.py", "/settings.toml"}

        def stat_side_effect(path: str) -> MagicMock:
            if path in missing_paths:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from utils.recovery import validate_critical_files

            all_present, missing = validate_critical_files()
            self.assertFalse(all_present)
            for path in missing_paths:
                self.assertIn(path, missing)


class TestRecoveryExists(unittest.TestCase):
    """Test recovery_exists function."""

    def test_recovery_exists_with_files(self) -> None:
        with patch("os.listdir", return_value=["boot.py", "code.py"]):
            from utils.recovery import recovery_exists

            self.assertTrue(recovery_exists())

    def test_recovery_exists_empty_directory(self) -> None:
        with patch("os.listdir", return_value=[]):
            from utils.recovery import recovery_exists

            self.assertFalse(recovery_exists())

    def test_recovery_exists_directory_not_found(self) -> None:
        with patch("os.listdir", side_effect=OSError("Directory not found")):
            from utils.recovery import recovery_exists

            self.assertFalse(recovery_exists())


class TestRecoveryValidateFilesInDirectory(unittest.TestCase):
    """Test _validate_files_in_directory helper function."""

    def test_validates_files_in_root_directory(self) -> None:
        """Test validation with empty base_dir (root filesystem)."""
        test_files = {"/boot.py", "/code.py"}

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import _validate_files_in_directory

            all_present, missing = _validate_files_in_directory("", test_files)
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_validates_files_in_subdirectory(self) -> None:
        """Test validation with base_dir prefix."""
        test_files = {"/boot.py", "/code.py"}

        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import _validate_files_in_directory

            all_present, missing = _validate_files_in_directory("/tmp/update", test_files)
            self.assertTrue(all_present)
            self.assertEqual(missing, [])
            # Verify it checked the correct paths
            mock_stat.assert_any_call("/tmp/update/boot.py")
            mock_stat.assert_any_call("/tmp/update/code.py")

    def test_detects_missing_files(self) -> None:
        """Test detection of missing files."""
        test_files = {"/boot.py", "/code.py", "/missing.py"}

        def stat_side_effect(path: str) -> MagicMock:
            if "missing.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from utils.recovery import _validate_files_in_directory

            all_present, missing = _validate_files_in_directory("/tmp", test_files)
            self.assertFalse(all_present)
            self.assertIn("/missing.py", missing)
            self.assertNotIn("/boot.py", missing)


class TestRecoveryValidateExtractedUpdate(unittest.TestCase):
    """Test validate_extracted_update function."""

    def test_all_files_present_in_extracted_dir(self) -> None:
        with patch("os.stat") as mock_stat:
            mock_stat.return_value = MagicMock()
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_missing_files_in_extracted_dir(self) -> None:
        def stat_side_effect(path: str) -> MagicMock:
            if "/tmp/update/boot.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with patch("os.stat", side_effect=stat_side_effect):
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)

    def test_script_only_release_skips_validation(self) -> None:
        """Script-only releases don't require all critical files."""
        manifest_content = json.dumps({"version": "1.0.0-s1", "script_only_release": True})

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            if "manifest.json" in path:
                mock_file = MagicMock()
                mock_file.read.return_value = manifest_content
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                return mock_file
            raise OSError("File not found")

        with patch("builtins.open", side_effect=mock_open_func):
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertTrue(all_present)
            self.assertEqual(missing, [])

    def test_script_only_release_with_invalid_manifest(self) -> None:
        """Invalid manifest falls back to normal validation."""

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            raise OSError("File not found")

        def stat_side_effect(path: str) -> MagicMock:
            if "/tmp/update/boot.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with (
            patch("builtins.open", side_effect=mock_open_func),
            patch("os.stat", side_effect=stat_side_effect),
        ):
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)

    def test_script_only_release_with_malformed_json(self) -> None:
        """Malformed JSON in manifest falls back to normal validation."""

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            if "manifest.json" in path:
                mock_file = MagicMock()
                mock_file.read.return_value = "{invalid json"
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                return mock_file
            raise OSError("File not found")

        def stat_side_effect(path: str) -> MagicMock:
            if "/tmp/update/boot.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with (
            patch("builtins.open", side_effect=mock_open_func),
            patch("os.stat", side_effect=stat_side_effect),
            patch("json.load", side_effect=ValueError("Invalid JSON")),
        ):
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)

    def test_normal_release_requires_all_files(self) -> None:
        """Normal releases require all critical files even with manifest."""
        manifest_content = json.dumps({"version": "1.0.0", "script_only_release": False})

        def mock_open_func(path: str, mode: str = "r") -> MagicMock:
            if "manifest.json" in path:
                mock_file = MagicMock()
                mock_file.read.return_value = manifest_content
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                return mock_file
            raise OSError("File not found")

        def stat_side_effect(path: str) -> MagicMock:
            if "/tmp/update/boot.py" in path:
                raise OSError("File not found")
            return MagicMock()

        with (
            patch("builtins.open", side_effect=mock_open_func),
            patch("os.stat", side_effect=stat_side_effect),
        ):
            from utils.recovery import validate_extracted_update

            all_present, missing = validate_extracted_update("/tmp/update")
            self.assertFalse(all_present)
            self.assertIn("/boot.py", missing)


class TestRecoveryClearRecoveryDirectory(unittest.TestCase):
    """Test _clear_recovery_directory helper function."""

    def test_clears_existing_files(self) -> None:
        """Existing files in recovery directory should be removed."""
        removed_files: list[str] = []
        # Track which files have been "removed" so subsequent listdir calls return empty
        listdir_calls = {"count": 0}

        def mock_listdir(path: str) -> list[str]:
            listdir_calls["count"] += 1
            # First call returns files, subsequent calls return empty (files removed)
            if listdir_calls["count"] == 1:
                return ["old_file.mpy", "stale.py"]
            return []

        def mock_remove(path: str) -> None:
            removed_files.append(path)

        with (
            patch("os.listdir", side_effect=mock_listdir),
            patch("os.remove", side_effect=mock_remove),
            patch("os.rmdir"),
            patch("os.sync"),
        ):
            from utils.recovery import _clear_recovery_directory

            _clear_recovery_directory()
            self.assertIn("/recovery/old_file.mpy", removed_files)
            self.assertIn("/recovery/stale.py", removed_files)

    def test_handles_nonexistent_directory(self) -> None:
        """Should handle gracefully if recovery directory doesn't exist."""
        with patch("os.listdir", side_effect=OSError("Directory not found")):
            from utils.recovery import _clear_recovery_directory

            # Should not raise
            _clear_recovery_directory()

    def test_clears_subdirectories(self) -> None:
        """Subdirectories in recovery should be recursively cleared."""
        call_count = {"listdir": 0}

        def mock_listdir(path: str) -> list[str]:
            call_count["listdir"] += 1
            # First call to /recovery returns subdir
            if path == "/recovery" and call_count["listdir"] == 1:
                return ["subdir"]
            # First call to /recovery/subdir returns a file
            if path == "/recovery/subdir" and call_count["listdir"] <= 3:
                return ["file.mpy"]
            # Subsequent calls return empty (files removed)
            return []

        with (
            patch("os.listdir", side_effect=mock_listdir),
            patch("os.remove"),
            patch("os.rmdir"),
            patch("os.sync"),
        ):
            from utils.recovery import _clear_recovery_directory

            _clear_recovery_directory()
            # Should have listed both recovery and subdirectory
            self.assertGreater(call_count["listdir"], 1)


class TestRecoveryCreateBackup(unittest.TestCase):
    """Test create_recovery_backup function."""

    def test_clears_directory_before_backup(self) -> None:
        """Recovery directory should be cleared before creating fresh backup."""
        clear_called = {"called": False}

        def track_clear() -> None:
            clear_called["called"] = True

        mock_file_content = b"test content"
        mock_open_obj = MagicMock()
        mock_open_obj.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_file_content)))
        mock_open_obj.__exit__ = MagicMock(return_value=False)

        with (
            patch("os.mkdir"),
            patch("os.listdir", side_effect=OSError),  # Not a directory
            patch("os.sync"),
            patch("builtins.open", return_value=mock_open_obj),
            patch("core.logging_helper.logger"),
            patch("utils.recovery._clear_recovery_directory", side_effect=track_clear) as mock_clear,
        ):
            from utils.recovery import create_recovery_backup

            create_recovery_backup()
            mock_clear.assert_called_once()
            self.assertTrue(clear_called["called"])

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
            patch("core.logging_helper.logger"),
        ):
            from utils.recovery import create_recovery_backup

            success, message = create_recovery_backup()
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
            from utils.recovery import create_recovery_backup

            success, message = create_recovery_backup()
            # Should return partial success with failures
            self.assertFalse(success)
            self.assertIn("Partial", message)


class TestRecoveryRestoreFromRecovery(unittest.TestCase):
    """Test restore_from_recovery function."""

    def test_restore_no_backup_found(self) -> None:
        with (
            patch("os.listdir", side_effect=OSError),
            patch("core.logging_helper.logger"),
        ):
            from utils.recovery import restore_from_recovery

            success, message = restore_from_recovery()
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
            from utils.recovery import restore_from_recovery

            success, message = restore_from_recovery()
            self.assertTrue(success)
            self.assertIn("complete", message.lower())


class TestRecoveryCriticalFiles(unittest.TestCase):
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


class TestRecoveryMinimalSet(unittest.TestCase):
    """Test that CRITICAL_FILES contains the minimal set for boot + OTA recovery."""

    def test_critical_files_count(self) -> None:
        """Critical files should be exactly 20 files (minimal OTA recovery set)."""
        from utils.recovery import CRITICAL_FILES

        # The minimal set for boot + OTA capability is exactly 20 files
        self.assertEqual(len(CRITICAL_FILES), 20)

    def test_boot_chain_is_complete(self) -> None:
        """Boot chain files must all be present for device to start."""
        from utils.recovery import CRITICAL_FILES

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
            self.assertIn(path, CRITICAL_FILES, f"Missing boot chain file: {path}")

    def test_ota_chain_is_complete(self) -> None:
        """OTA update chain files must all be present for self-healing."""
        from utils.recovery import CRITICAL_FILES

        ota_chain = [
            "/managers/manager_base.mpy",
            "/managers/system_manager.mpy",
            "/managers/update_manager.mpy",
            "/utils/recovery.mpy",
            "/managers/connection_manager.mpy",
            "/controllers/wifi_radio_controller.mpy",
            "/utils/zipfile_lite.mpy",
        ]
        for path in ota_chain:
            self.assertIn(path, CRITICAL_FILES, f"Missing OTA chain file: {path}")

    def test_library_dependencies_are_complete(self) -> None:
        """Library dependencies required by OTA chain must be present."""
        from utils.recovery import CRITICAL_FILES

        lib_deps = [
            "/lib/adafruit_requests.mpy",
            "/lib/adafruit_connection_manager.mpy",
            "/lib/adafruit_hashlib/__init__.mpy",
        ]
        for path in lib_deps:
            self.assertIn(path, CRITICAL_FILES, f"Missing library: {path}")

    def test_config_files_are_present(self) -> None:
        """Configuration files required for boot and updates must be present."""
        from utils.recovery import CRITICAL_FILES

        config_files = ["/settings.toml", "/manifest.json"]
        for path in config_files:
            self.assertIn(path, CRITICAL_FILES, f"Missing config file: {path}")

    def test_unnecessary_files_are_not_included(self) -> None:
        """Files not required for OTA recovery should NOT be in CRITICAL_FILES."""
        from utils.recovery import CRITICAL_FILES

        # These are nice-to-have but not required for boot + OTA
        unnecessary = [
            "/controllers/pixel_controller.mpy",  # LED feedback, not critical
            "/lib/neopixel.mpy",  # Only needed for pixel_controller
        ]
        for path in unnecessary:
            self.assertNotIn(path, CRITICAL_FILES, f"Unnecessary file included: {path}")


class TestRecoveryIntegrity(unittest.TestCase):
    """Test recovery backup integrity features."""

    def test_backup_includes_integrity_metadata(self) -> None:
        """Recovery backup should track file hashes for corruption detection."""
        from utils.recovery import RECOVERY_INTEGRITY_FILE

        # Verify the integrity file constant exists
        self.assertIsNotNone(RECOVERY_INTEGRITY_FILE)

    def test_validate_backup_integrity_exists(self) -> None:
        """Function to validate backup integrity should exist."""
        from utils.recovery import validate_backup_integrity

        self.assertTrue(callable(validate_backup_integrity))

    def test_validate_backup_integrity_returns_tuple(self) -> None:
        """validate_backup_integrity returns (valid, message) tuple."""
        with (
            patch("os.stat") as mock_stat,
            patch("builtins.open", MagicMock()),
            patch("os.listdir", return_value=["boot.py"]),
        ):
            mock_stat.return_value = MagicMock()
            from utils.recovery import validate_backup_integrity

            result = validate_backup_integrity()
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)


class TestPreservedFiles(unittest.TestCase):
    """Test PRESERVED_FILES constant for user data protection."""

    def test_preserved_files_includes_secrets(self) -> None:
        """secrets.json must always be preserved."""
        from utils.recovery import PRESERVED_FILES

        self.assertIn("secrets.json", PRESERVED_FILES)

    def test_preserved_files_includes_development(self) -> None:
        """DEVELOPMENT flag should be preserved."""
        from utils.recovery import PRESERVED_FILES

        self.assertIn("DEVELOPMENT", PRESERVED_FILES)

    def test_preserved_files_is_minimal(self) -> None:
        """Only user-provided data should be preserved."""
        from utils.recovery import PRESERVED_FILES

        # Only secrets.json and DEVELOPMENT should be preserved
        self.assertEqual(len(PRESERVED_FILES), 2)


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

    def test_boot_critical_includes_recovery(self) -> None:
        """recovery.mpy must be in _BOOT_CRITICAL for recovery to work."""
        boot_critical = self._get_boot_critical_from_source()
        self.assertIn(
            "/utils/recovery.mpy",
            boot_critical,
            "recovery.mpy missing from boot.py _BOOT_CRITICAL",
        )

    def test_boot_critical_includes_boot_support(self) -> None:
        """boot_support.mpy must be in _BOOT_CRITICAL for boot.py to work."""
        boot_critical = self._get_boot_critical_from_source()
        self.assertIn(
            "/core/boot_support.mpy",
            boot_critical,
            "boot_support.mpy missing from boot.py _BOOT_CRITICAL",
        )


if __name__ == "__main__":
    unittest.main()
