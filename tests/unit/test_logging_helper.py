"""
Unit tests for logging_helper module.

Tests verify:
- Logger creation and naming
- Log level filtering
- Level configuration
"""

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

    def test_configure_returns_logger(self) -> None:
        """configure_logging() returns a WicidLogger."""
        log = configure_logging("INFO")
        self.assertIsInstance(log, WicidLogger)


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
