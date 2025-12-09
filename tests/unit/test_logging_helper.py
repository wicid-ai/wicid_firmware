"""
Unit tests for logging_helper module.

Tests verify:
- Logger creation and naming
- Log level filtering
- Level configuration
- File logging functionality
"""

import os
import tempfile
from unittest.mock import patch

# Store original log level to restore after tests
import core.logging_helper as logging_module
from core.logging_helper import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    TESTING,
    WARNING,
    WicidLogger,
    configure_logging,
    logger,
)
from tests.unit import TestCase


class TestWicidLogger(TestCase):
    """Test WicidLogger class functionality."""

    def setUp(self) -> None:
        """Store original log level."""
        self._original_level = logging_module._log_level

    def tearDown(self) -> None:
        """Restore original log level."""
        logging_module._log_level = self._original_level

    def test_logger_name_parsing_hierarchical(self) -> None:
        """Logger extracts readable module name from hierarchical name."""
        log = WicidLogger("wicid.wifi")
        self.assertEqual(log.module, "Wifi")

        log = WicidLogger("wicid.config")
        self.assertEqual(log.module, "Config")

        log = WicidLogger("wicid.weather.service")
        self.assertEqual(log.module, "Service")

    def test_logger_name_parsing_simple(self) -> None:
        """Logger handles simple non-hierarchical names."""
        log = WicidLogger("wicid")
        self.assertEqual(log.module, "Main")

        log = WicidLogger("custom")
        self.assertEqual(log.module, "Custom")

    def test_logger_name_parsing_empty(self) -> None:
        """Logger handles empty name gracefully."""
        log = WicidLogger("")
        self.assertEqual(log.name, "main")

    def test_log_level_filtering(self) -> None:
        """Messages below current log level are filtered."""
        logging_module._log_level = WARNING

        log = WicidLogger("test")

        # Capture stdout
        with patch("builtins.print") as mock_print:
            log.debug("debug message")
            log.info("info message")
            self.assertFalse(mock_print.called, "DEBUG/INFO should be filtered at WARNING level")

            log.warning("warning message")
            self.assertTrue(mock_print.called, "WARNING should be logged at WARNING level")

    def test_all_log_methods_exist(self) -> None:
        """All log level methods are available."""
        log = WicidLogger("test")

        # Suppress output
        logging_module._log_level = CRITICAL + 10

        # These should not raise
        log.debug("test")
        log.info("test")
        log.warning("test")
        log.error("test")
        log.critical("test")
        log.testing("test")


class TestLoggerFactory(TestCase):
    """Test logger() factory function."""

    def test_logger_returns_wicid_logger(self) -> None:
        """logger() returns WicidLogger instance."""
        log = logger("wicid.test")
        self.assertIsInstance(log, WicidLogger)

    def test_logger_default_name(self) -> None:
        """logger() uses 'wicid' as default name."""
        log = logger()
        self.assertEqual(log.name, "wicid")


class TestConfigureLogging(TestCase):
    """Test configure_logging() function."""

    def setUp(self) -> None:
        """Store original log level."""
        self._original_level = logging_module._log_level

    def tearDown(self) -> None:
        """Restore original log level."""
        logging_module._log_level = self._original_level

    def test_configure_sets_level(self) -> None:
        """configure_logging() sets global log level."""
        configure_logging("DEBUG")
        self.assertEqual(logging_module._log_level, DEBUG)

        configure_logging("ERROR")
        self.assertEqual(logging_module._log_level, ERROR)

    def test_configure_case_insensitive(self) -> None:
        """configure_logging() accepts case-insensitive level names."""
        configure_logging("debug")
        self.assertEqual(logging_module._log_level, DEBUG)

        configure_logging("WARNING")
        self.assertEqual(logging_module._log_level, WARNING)

    def test_configure_invalid_defaults_to_info(self) -> None:
        """configure_logging() defaults to INFO for invalid level."""
        configure_logging("INVALID")
        self.assertEqual(logging_module._log_level, INFO)

    def test_configure_completes_successfully(self) -> None:
        """configure_logging() completes without error."""
        configure_logging("INFO")
        # Verify it set the level correctly
        self.assertEqual(logging_module._log_level, INFO)


class TestLogLevelConstants(TestCase):
    """Test log level constants are properly defined."""

    def test_level_ordering(self) -> None:
        """Log levels are in correct order."""
        self.assertTrue(DEBUG < INFO < WARNING < ERROR < CRITICAL < TESTING)

    def test_level_values(self) -> None:
        """Log levels have expected values."""
        self.assertEqual(DEBUG, 10)
        self.assertEqual(INFO, 20)
        self.assertEqual(WARNING, 30)
        self.assertEqual(ERROR, 40)
        self.assertEqual(CRITICAL, 50)
        self.assertEqual(TESTING, 60)


class TestFileLogging(TestCase):
    """Test file logging functionality."""

    def setUp(self) -> None:
        """Store original log level."""
        self._original_level = logging_module._log_level
        logging_module._log_level = INFO

    def tearDown(self) -> None:
        """Restore original log level."""
        logging_module._log_level = self._original_level

    def test_logger_with_file_writes_to_file(self) -> None:
        """Logger with log_file parameter writes to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            log = logger("wicid.test", log_file=log_path)

            with patch("builtins.print"):
                log.info("Test message")

            # Verify message was written to file
            with open(log_path) as f:
                content = f.read()
            self.assertIn("[INFO: Test] Test message", content)
        finally:
            os.unlink(log_path)

    def test_logger_with_file_writes_to_stdout_and_file(self) -> None:
        """Logger with log_file writes to both stdout and file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            log = logger("wicid.test", log_file=log_path)

            with patch("builtins.print") as mock_print:
                log.info("Test message")

            # Verify it printed to stdout
            mock_print.assert_called_once()
            # Verify it also wrote to file
            with open(log_path) as f:
                content = f.read()
            self.assertIn("Test message", content)
        finally:
            os.unlink(log_path)

    def test_logger_with_file_appends_to_file(self) -> None:
        """Logger with log_file appends to existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name
            log_file.write("Existing content\n")

        try:
            log = logger("wicid.test", log_file=log_path)

            with patch("builtins.print"):
                log.info("New message")

            # Verify file contains both old and new content
            with open(log_path) as f:
                content = f.read()
            self.assertIn("Existing content", content)
            self.assertIn("New message", content)
        finally:
            os.unlink(log_path)

    def test_logger_with_file_handles_write_failure_gracefully(self) -> None:
        """Logger continues to work even if file write fails."""
        log = logger("wicid.test", log_file="/nonexistent/directory/log.txt")

        with patch("builtins.print") as mock_print, patch("builtins.open", side_effect=OSError("Write failed")):
            # Should not raise
            log.info("Test message")
            # Should still print to stdout (log message) and error message
            self.assertGreaterEqual(mock_print.call_count, 1)
            # First call should be the log message
            self.assertIn("Test message", str(mock_print.call_args_list[0]))

    def test_logger_without_file_only_writes_to_stdout(self) -> None:
        """Logger without log_file only writes to stdout."""
        log = logger("wicid.test")

        with patch("builtins.print") as mock_print:
            log.info("Test message")

            # Verify it printed to stdout
            mock_print.assert_called_once()
            # Verify no file operations occurred
            self.assertIsNone(getattr(log, "_log_file", None))

    def test_logger_function_accepts_log_file_parameter(self) -> None:
        """logger() function accepts optional log_file parameter."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
            log_path = log_file.name

        try:
            log = logger("wicid.test", log_file=log_path)
            self.assertEqual(log._log_file, log_path)
        finally:
            os.unlink(log_path)
