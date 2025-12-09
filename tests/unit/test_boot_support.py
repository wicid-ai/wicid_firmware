"""
Unit tests for boot support module.

Tests boot_support.py behavior including boot orchestration,
storage configuration, and recovery integration.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from tests.unit import TestCase


class TestCheckAndRestoreFromRecovery(TestCase):
    """Test check_and_restore_from_recovery behavior."""

    def test_returns_false_when_all_files_present(self) -> None:
        """check_and_restore_from_recovery returns False when no recovery needed."""
        with (
            patch("utils.recovery.validate_files", return_value=(True, [])),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)

    def test_returns_false_when_no_recovery_backup(self) -> None:
        """check_and_restore_from_recovery returns False when no backup available."""
        with (
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery._recovery_exists", return_value=False),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)

    def test_returns_true_when_recovery_succeeds(self) -> None:
        """check_and_restore_from_recovery returns True when recovery restoration succeeds."""
        with (
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery._recovery_exists", return_value=True),
            patch("utils.recovery._restore_from_recovery", return_value=(True, "Restored 20 files")),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            # Key behavior: function returns True when recovery succeeds
            self.assertTrue(result)

    def test_returns_false_when_recovery_fails(self) -> None:
        """check_and_restore_from_recovery returns False when recovery restoration fails."""
        with (
            patch("utils.recovery.validate_files", return_value=(False, ["/boot.py"])),
            patch("utils.recovery._recovery_exists", return_value=True),
            patch("utils.recovery._restore_from_recovery", return_value=(False, "Recovery failed")),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from utils.recovery import check_and_restore_from_recovery

            result = check_and_restore_from_recovery()
            self.assertFalse(result)


class TestBootLogging(TestCase):
    """Test boot logging behavior using logger pattern."""

    def setUp(self) -> None:
        """Set up test isolation."""
        import core.logging_helper as logging_module

        self._original_level = logging_module._log_level
        logging_module._log_level = 20  # INFO

    def tearDown(self) -> None:
        """Restore original log level."""
        import core.logging_helper as logging_module

        logging_module._log_level = self._original_level

    def test_logger_writes_to_boot_log_file(self) -> None:
        """Logger with BOOT_LOG_FILE writes messages to boot log file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            with patch("core.boot_support.BOOT_LOG_FILE", log_path):
                from core.logging_helper import logger

                log = logger("wicid.boot", log_file=log_path)
                with patch("builtins.print"):
                    log.info("Test message")

                # Verify message was written
                with open(log_path) as f:
                    content = f.read()
                self.assertIn("[INFO: Boot] Test message", content)
        finally:
            os.unlink(log_path)

    def test_logger_prints_to_console(self) -> None:
        """Logger prints messages to console even with log_file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            from core.logging_helper import logger

            log = logger("wicid.boot", log_file=log_path)
            with patch("builtins.print") as mock_print:
                log.info("Console test")
                mock_print.assert_called()
                self.assertIn("Console test", str(mock_print.call_args))
        finally:
            os.unlink(log_path)

    def test_logger_handles_file_write_failure_gracefully(self) -> None:
        """Logger continues even if file write fails."""
        from core.logging_helper import logger

        log = logger("wicid.boot", log_file="/nonexistent/directory/log.txt")
        with patch("builtins.print"), patch("builtins.open", side_effect=OSError("Write failed")):
            # Should not raise
            log.info("Test message")


class TestConfigureStorage(TestCase):
    """Test configure_storage behavior."""

    def test_disables_usb_drive(self) -> None:
        """configure_storage disables USB mass storage."""
        with (
            patch("storage.disable_usb_drive") as mock_disable,
            patch("storage.remount", return_value=True),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from core.boot_support import configure_storage

            configure_storage()
            mock_disable.assert_called_once()

    def test_remounts_filesystem(self) -> None:
        """configure_storage remounts filesystem as writable."""
        with (
            patch("storage.disable_usb_drive"),
            patch("storage.remount", return_value=True) as mock_remount,
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from core.boot_support import configure_storage

            configure_storage()
            mock_remount.assert_called_once_with("/", readonly=False)

    def test_handles_storage_errors_gracefully(self) -> None:
        """configure_storage handles storage errors without crashing."""
        with (
            patch("storage.disable_usb_drive", side_effect=OSError("Storage error")),
            patch("core.logging_helper.logger") as mock_logger,
        ):
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            from core.boot_support import configure_storage

            # Should not raise
            configure_storage()


if __name__ == "__main__":
    unittest.main()
