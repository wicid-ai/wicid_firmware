"""
Unit tests for update installation utilities.

Tests the public API of utils.update_install module (process_pending_update).
Private helpers are tested indirectly through the public API.
"""

import contextlib
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from tests.unit import TestCase
from utils.update_install import PRESERVED_FILES


class TestPreservedFiles(TestCase):
    """Test PRESERVED_FILES constant."""

    def test_preserved_files_includes_secrets(self) -> None:
        """secrets.json must always be preserved."""
        self.assertIn("secrets.json", PRESERVED_FILES)

    def test_preserved_files_includes_incompatible_releases(self) -> None:
        """incompatible_releases.json should be preserved."""
        self.assertIn("incompatible_releases.json", PRESERVED_FILES)

    def test_preserved_files_includes_development(self) -> None:
        """DEVELOPMENT flag should be preserved."""
        self.assertIn("DEVELOPMENT", PRESERVED_FILES)

    def test_preserved_files_is_minimal(self) -> None:
        """Only user-provided data should be preserved."""
        # Should have exactly 4 files
        self.assertEqual(len(PRESERVED_FILES), 4)


class TestProcessPendingUpdate(TestCase):
    """Tests for process_pending_update function (public API)."""

    def setUp(self) -> None:
        """Set up mocks for process_pending_update tests."""
        # Mock logger
        self._log_mock = MagicMock()
        self._log_patcher = patch("utils.update_install._boot_file_logger", return_value=self._log_mock)
        self._log_patcher.start()

        # Mock LED updates
        self._led_patcher = patch("utils.update_install._update_led")
        self._led_patcher.start()

        # Mock microcontroller.reset
        self._reset_patcher = patch("microcontroller.reset")
        self._reset_mock = self._reset_patcher.start()

        # Mock file operations
        self._delete_all_except_patcher = patch("utils.update_install._delete_all_except")
        self._delete_all_except_mock = self._delete_all_except_patcher.start()

        self._move_contents_patcher = patch("utils.update_install._move_directory_contents")
        self._move_contents_mock = self._move_contents_patcher.start()

        self._cleanup_patcher = patch("utils.update_install._cleanup_pending_update")
        self._cleanup_mock = self._cleanup_patcher.start()

        self._validate_files_patcher = patch("utils.update_install.validate_files")
        self._validate_files_mock = self._validate_files_patcher.start()

        self._create_backup_patcher = patch("utils.update_install.create_recovery_backup")
        self._create_backup_mock = self._create_backup_patcher.start()

        self._check_compat_patcher = patch("utils.update_install.check_release_compatibility")
        self._check_compat_mock = self._check_compat_patcher.start()

        self._mark_incompat_patcher = patch("utils.update_install.mark_incompatible_release")
        self._mark_incompat_mock = self._mark_incompat_patcher.start()

        # Mock os operations
        self._os_patcher = patch("utils.update_install.os")
        self._os_mock = self._os_patcher.start()
        self._os_mock.listdir.return_value = ["manifest.json"]
        self._os_mock.getenv.return_value = "0.5.0"
        self._os_mock.sync.return_value = None

        # Mock file open for manifest.json
        self._open_patcher = patch("builtins.open", create=True)
        self._open_mock = self._open_patcher.start()

        # Mock _validate_ready_marker
        self._validate_ready_patcher = patch("utils.update_install._validate_ready_marker", return_value=True)
        self._validate_ready_mock = self._validate_ready_patcher.start()

        # Mock _cleanup_incomplete_staging
        self._cleanup_staging_patcher = patch("utils.update_install._cleanup_incomplete_staging")
        self._cleanup_staging_mock = self._cleanup_staging_patcher.start()

        # Mock _get_script_path
        self._get_script_path_patcher = patch("utils.update_install._get_script_path")
        self._get_script_path_mock = self._get_script_path_patcher.start()
        self._get_script_path_mock.return_value = (
            "/pending_update/root/firmware_install_scripts/pre_install_v0.6.0-s3.py"
        )

        # Mock settings.toml updater to avoid touching filesystem and to assert calls
        self._update_settings_patcher = patch("utils.update_install._update_settings_toml")
        self._update_settings_mock = self._update_settings_patcher.start()

        # Mock _execute_install_script
        self._execute_script_patcher = patch("utils.update_install._execute_install_script")
        self._execute_script_mock = self._execute_script_patcher.start()
        self._execute_script_mock.return_value = (True, "Script completed successfully")

    def tearDown(self) -> None:
        """Stop all patchers."""
        self._log_patcher.stop()
        self._led_patcher.stop()
        self._reset_patcher.stop()
        self._delete_all_except_patcher.stop()
        self._move_contents_patcher.stop()
        self._cleanup_patcher.stop()
        self._validate_files_patcher.stop()
        self._create_backup_patcher.stop()
        self._check_compat_patcher.stop()
        self._mark_incompat_patcher.stop()
        self._os_patcher.stop()
        self._open_patcher.stop()
        self._validate_ready_patcher.stop()
        self._cleanup_staging_patcher.stop()
        self._get_script_path_patcher.stop()
        self._execute_script_patcher.stop()
        self._update_settings_patcher.stop()

    def _setup_manifest_file(self, manifest_data: dict, include_secrets: bool = False) -> None:
        """Set up mock for reading manifest.json and optionally secrets.json."""
        import json
        from io import StringIO

        manifest_json = json.dumps(manifest_data)
        manifest_file_mock = MagicMock()
        manifest_file_mock.__enter__.return_value = StringIO(manifest_json)
        manifest_file_mock.__exit__.return_value = None

        # Make open return the file mock for manifest.json, but raise OSError for other files
        def open_side_effect(path: str, mode: str = "r") -> MagicMock:
            if path == "/pending_update/root/manifest.json":
                return manifest_file_mock
            elif path == "/secrets.json" and include_secrets:
                secrets_file_mock = MagicMock()
                secrets_file_mock.__enter__.return_value = StringIO('{"test": "data"}')
                secrets_file_mock.__exit__.return_value = None
                return secrets_file_mock
            raise OSError(f"File not found: {path}")

        self._open_mock.side_effect = open_side_effect

    def test_script_only_release_skips_delete_all_except(self) -> None:
        """Script-only releases should NOT call delete_all_except()."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        # This should raise SystemExit or similar when microcontroller.reset() is called
        # We'll catch it to verify the behavior
        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify delete_all_except was NOT called
        self._delete_all_except_mock.assert_not_called()

    def test_script_only_release_skips_move_directory_contents(self) -> None:
        """Script-only releases should NOT call move_directory_contents()."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify move_directory_contents was NOT called
        self._move_contents_mock.assert_not_called()

    def test_script_only_release_skips_post_install_validation(self) -> None:
        """Script-only releases should NOT call validate_files() after initial check."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify validate_files was NOT called with empty string (post-install validation)
        # It might be called once for the initial check, but not for post-install validation
        calls = self._validate_files_mock.call_args_list
        post_install_calls = [call for call in calls if call[0][0] == ""]
        self.assertEqual(
            len(post_install_calls),
            0,
            "validate_files should not be called for post-install validation in script-only releases",
        )

    def test_script_only_release_skips_recovery_backup(self) -> None:
        """Script-only releases should NOT call create_recovery_backup()."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify create_recovery_backup was NOT called
        self._create_backup_mock.assert_not_called()

    def test_script_only_release_calls_cleanup(self) -> None:
        """Script-only releases SHOULD call cleanup_pending_update()."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest, include_secrets=True)
        self._check_compat_mock.return_value = (True, None)
        # Mock validate_files to return success for post-install check
        self._validate_files_mock.return_value = (True, [])

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify cleanup_pending_update WAS called
        self._cleanup_mock.assert_called_once()

    def test_script_only_release_calls_reset(self) -> None:
        """Script-only releases SHOULD call microcontroller.reset() to reboot."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest, include_secrets=True)
        self._check_compat_mock.return_value = (True, None)
        # Mock validate_files to return success for post-install check
        self._validate_files_mock.return_value = (True, [])

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify microcontroller.reset WAS called
        self._reset_mock.assert_called_once()

    def test_script_only_release_updates_settings_version(self) -> None:
        """Script-only releases should update settings.toml version via helper."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest, include_secrets=True)
        self._check_compat_mock.return_value = (True, None)
        self._validate_files_mock.return_value = (True, [])

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        self._update_settings_mock.assert_called_once_with("0.5.0", "0.6.0-s3")

    def test_script_only_release_executes_pre_install_script(self) -> None:
        """Script-only releases SHOULD execute pre-install script."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify _execute_install_script was called for pre-install
        self._execute_script_mock.assert_called()
        call_args = self._execute_script_mock.call_args
        self.assertEqual(call_args[1]["script_type"], "pre_install")

    def test_script_only_release_skips_post_install_script(self) -> None:
        """Script-only releases should NOT execute post-install script even if indicated."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0-s3",
            "script_only_release": True,
            "has_pre_install_script": True,
            "has_post_install_script": True,  # Even if True, should not execute
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify _execute_install_script was NOT called with post_install type
        post_install_calls = [
            call for call in self._execute_script_mock.call_args_list if call[1].get("script_type") == "post_install"
        ]
        self.assertEqual(
            len(post_install_calls), 0, "Post-install script should not be executed for script-only releases"
        )

    def test_full_release_calls_delete_all_except(self) -> None:
        """Full releases (non-script-only) SHOULD call delete_all_except()."""
        from utils.update_install import process_pending_update

        manifest = {
            "version": "0.6.0",
            "script_only_release": False,  # Full release
            "has_pre_install_script": False,
            "has_post_install_script": False,
        }
        self._setup_manifest_file(manifest)
        self._check_compat_mock.return_value = (True, None)
        self._validate_files_mock.return_value = (True, [])

        # Mock secrets.json read
        import json
        from io import StringIO

        def open_side_effect(path: str, mode: str = "r") -> MagicMock:
            if path == "/pending_update/root/manifest.json":
                file_mock = MagicMock()
                file_mock.__enter__.return_value = StringIO(json.dumps(manifest))
                file_mock.__exit__.return_value = None
                return file_mock
            elif path == "/secrets.json":
                file_mock = MagicMock()
                file_mock.__enter__.return_value = StringIO('{"test": "data"}')
                file_mock.__exit__.return_value = None
                return file_mock
            raise OSError(f"File not found: {path}")

        self._open_mock.side_effect = open_side_effect

        with contextlib.suppress(SystemExit, Exception):
            process_pending_update()

        # Verify _delete_all_except WAS called for full release
        self._delete_all_except_mock.assert_called()

    def test_no_pending_update_exits_early(self) -> None:
        """When no pending update exists, process_pending_update exits early."""
        from utils.update_install import process_pending_update

        # Mock os.listdir to raise OSError (no directory)
        self._os_mock.listdir.side_effect = OSError("No such directory")

        process_pending_update()

        # Should not call any update operations
        self._delete_all_except_mock.assert_not_called()
        self._move_contents_mock.assert_not_called()
        self._reset_mock.assert_not_called()

    def test_empty_pending_update_cleans_up(self) -> None:
        """Empty pending update directory triggers cleanup."""
        from utils.update_install import process_pending_update

        # Empty directory
        self._os_mock.listdir.return_value = []

        process_pending_update()

        # Should call cleanup
        self._cleanup_mock.assert_called()
        # Should not proceed with update
        self._reset_mock.assert_not_called()

    def test_missing_ready_marker_aborts_update(self) -> None:
        """Missing .ready marker prevents update installation."""
        from utils.update_install import process_pending_update

        self._os_mock.listdir.return_value = ["manifest.json"]
        self._validate_ready_mock.return_value = False

        process_pending_update()

        # Should cleanup but not proceed
        self._cleanup_mock.assert_called()
        self._reset_mock.assert_not_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
