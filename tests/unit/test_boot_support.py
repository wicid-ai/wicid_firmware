"""
Unit tests for boot support module.

Tests boot_support.py behavior including boot orchestration,
storage configuration, and recovery integration.
"""

import os
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from tests.test_helpers import create_file_path_redirector
from tests.unit import TestCase


class TestResetVersionForOta(TestCase):
    """Test _reset_version_for_ota behavior."""

    def setUp(self) -> None:
        """Create temporary settings files for testing."""
        self.test_dir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.test_dir, "settings.toml")
        self.recovery_settings_path = os.path.join(self.test_dir, "recovery", "settings.toml")
        os.makedirs(os.path.join(self.test_dir, "recovery"), exist_ok=True)

    def tearDown(self) -> None:
        """Clean up temporary files."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _map_path(self, path: str) -> str:
        """Map device paths to test directory paths."""
        if path == "/settings.toml":
            return self.settings_path
        elif path == "/recovery/settings.toml":
            return self.recovery_settings_path
        return path

    def test_resets_version_to_zero(self) -> None:
        """_reset_version_for_ota resets VERSION to 0.0.0 in settings.toml."""
        # Create settings file with a version
        settings_content = 'VERSION = "1.2.3"\nLOG_LEVEL = "INFO"\n'
        with open(self.settings_path, "w") as f:
            f.write(settings_content)
        with open(self.recovery_settings_path, "w") as f:
            f.write(settings_content)

        path_map = {"/settings.toml": self.settings_path, "/recovery/settings.toml": self.recovery_settings_path}
        mock_open = create_file_path_redirector(path_map)

        with (
            patch("utils.update_install.open", side_effect=mock_open),
            patch("utils.update_install.os.sync"),
        ):
            from core.boot_support import _reset_version_for_ota

            result = _reset_version_for_ota()
            self.assertTrue(result)

        # Verify version was reset
        with open(self.settings_path) as f:
            content = f.read()
        self.assertIn('VERSION = "0.0.0"', content)
        self.assertIn("LOG_LEVEL", content)  # Other settings preserved

    def test_handles_missing_recovery_settings(self) -> None:
        """_reset_version_for_ota falls back to root settings when recovery missing."""
        settings_content = 'VERSION = "2.0.0"\n'
        with open(self.settings_path, "w") as f:
            f.write(settings_content)

        written_content: list[str] = []

        def mock_open(path: str, mode: str = "r") -> Any:
            if path == "/recovery/settings.toml":
                raise OSError("Not found")

            mapped_path = self._map_path(path)
            mock_file = MagicMock()

            if "w" in mode:
                # Capture written content
                def write(content: str) -> None:
                    written_content.append(content)

                mock_file.write.side_effect = write
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
            else:
                # Return file content for read operations
                with open(mapped_path, mode) as f:
                    content = f.read()
                mock_file.read.return_value = content
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)

            return mock_file

        with (
            patch("utils.update_install.open", side_effect=mock_open),
            patch("utils.update_install.os.sync"),
        ):
            from core.boot_support import _reset_version_for_ota

            result = _reset_version_for_ota()
            self.assertTrue(result)

        # Verify version was reset by checking what was written
        written = "".join(written_content)
        self.assertIn('VERSION = "0.0.0"', written)

    def test_returns_false_on_error(self) -> None:
        """_reset_version_for_ota returns False when file operations fail."""
        with patch("utils.update_install.reset_version_for_ota", return_value=False):
            from core.boot_support import _reset_version_for_ota

            result = _reset_version_for_ota()
            self.assertFalse(result)


class TestCheckAndRestoreFromRecovery(TestCase):
    """Test check_and_restore_from_recovery behavior."""

    def setUp(self) -> None:
        """Set up test isolation."""
        # Ensure mark_incompatible_release is available for all tests
        import core.boot_support

        self.original_mark = core.boot_support.mark_incompatible_release
        if self.original_mark is None:
            core.boot_support.mark_incompatible_release = MagicMock()

    def tearDown(self) -> None:
        """Clean up test isolation."""
        import core.boot_support

        core.boot_support.mark_incompatible_release = self.original_mark

    def test_returns_false_when_all_files_present(self) -> None:
        """check_and_restore_from_recovery returns False when no recovery needed."""
        with (
            patch("utils.recovery.validate_critical_files", return_value=(True, [])),
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)

    def test_returns_false_when_no_recovery_backup(self) -> None:
        """check_and_restore_from_recovery returns False when no backup available."""
        with (
            patch("utils.recovery.validate_critical_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery.recovery_exists", return_value=False),
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)

    def test_returns_true_when_recovery_succeeds(self) -> None:
        """check_and_restore_from_recovery returns True when recovery restoration succeeds."""
        # Patch at the source module where functions are imported from
        with (
            patch("utils.recovery.validate_critical_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery.recovery_exists", return_value=True),
            patch("utils.recovery.restore_from_recovery", return_value=(True, "Restored 20 files")),
            patch("core.boot_support.log_boot_message"),
            patch("core.boot_support._reset_version_for_ota", return_value=True),
            patch("core.boot_support.remove_directory_recursive"),
            patch("builtins.open", side_effect=OSError("No manifest")),
        ):
            # Reload module to pick up patched functions
            import importlib

            import core.boot_support

            importlib.reload(core.boot_support)

            result = core.boot_support.check_and_restore_from_recovery()
            # Key behavior: function returns True when recovery succeeds
            self.assertTrue(result)

    def test_returns_false_when_recovery_fails(self) -> None:
        """check_and_restore_from_recovery returns False when recovery restoration fails."""
        with (
            patch("utils.recovery.validate_critical_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery.recovery_exists", return_value=True),
            patch("utils.recovery.restore_from_recovery", return_value=(False, "Recovery failed")),
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)


class TestLogBootMessage(TestCase):
    """Test log_boot_message behavior."""

    def test_writes_to_boot_log_file(self) -> None:
        """log_boot_message writes messages to boot log file."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            with (
                patch("core.boot_support.BOOT_LOG_FILE", log_path),
                patch("builtins.print"),
            ):
                from core.boot_support import log_boot_message

                log_boot_message("Test message")

            # Verify message was written
            with open(log_path) as f:
                content = f.read()
            self.assertIn("Test message", content)
        finally:
            os.unlink(log_path)

    def test_prints_to_console(self) -> None:
        """log_boot_message prints messages to console."""
        with (
            patch("builtins.print") as mock_print,
            patch("core.boot_support.BOOT_LOG_FILE", "/nonexistent/log"),
        ):
            from core.boot_support import log_boot_message

            log_boot_message("Console test")
            mock_print.assert_called_with("Console test")

    def test_handles_file_write_failure_gracefully(self) -> None:
        """log_boot_message continues even if file write fails."""
        with (
            patch("builtins.print"),
            patch("builtins.open", side_effect=OSError("Write failed")),
        ):
            from core.boot_support import log_boot_message

            # Should not raise
            log_boot_message("Test message")


class TestConfigureStorage(TestCase):
    """Test configure_storage behavior."""

    def test_disables_usb_drive(self) -> None:
        """configure_storage disables USB mass storage."""
        with (
            patch("storage.disable_usb_drive") as mock_disable,
            patch("storage.remount", return_value=True),
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import configure_storage

            configure_storage()
            mock_disable.assert_called_once()

    def test_remounts_filesystem(self) -> None:
        """configure_storage remounts filesystem as writable."""
        with (
            patch("storage.disable_usb_drive"),
            patch("storage.remount", return_value=True) as mock_remount,
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import configure_storage

            configure_storage()
            mock_remount.assert_called_once_with("/", readonly=False)

    def test_handles_storage_errors_gracefully(self) -> None:
        """configure_storage handles storage errors without crashing."""
        with (
            patch("storage.disable_usb_drive", side_effect=OSError("Storage error")),
            patch("core.boot_support.log_boot_message"),
        ):
            from core.boot_support import configure_storage

            # Should not raise
            configure_storage()


if __name__ == "__main__":
    unittest.main()
