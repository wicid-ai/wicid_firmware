"""
Logging Helper - Simple custom logger for WICID.

Provides a straightforward logging solution optimized for CircuitPython.
Clean, explicit, and easy to extend without fighting library limitations.
"""

import os
import sys
import traceback

# Global log level
_log_level = 20  # INFO

# Log level constants
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50
TESTING = 60  # Suppresses all logs except test output

_LEVEL_NAMES = {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL", 60: "TESTING"}

# File write error suppression (global to prevent spam across all loggers)
_LOGGED_FILE_ERROR = False


class WicidLogger:
    """
    Simple logger for WICID firmware.

    Designed for CircuitPython simplicity - no complex handler propagation,
    just straightforward formatted output.

    Format: [LEVEL: ModuleName] message

    Example:
        log = logger('wicid.wifi')
        logger.info("Connected")  # Output: [INFO: Wifi] Connected
    """

    def __init__(self, name: str, log_file: str | None = None) -> None:
        """
        Initialize logger with a hierarchical name.

        Args:
            name: Logger name (e.g., 'wicid.wifi', 'wicid.config')
            log_file: Optional file path to write logs to (in addition to stdout)
        """
        self.name = name if name else "main"
        self._log_file = log_file

        # Extract readable module name from hierarchical name
        # 'wicid.wifi' -> 'Wifi'
        # 'wicid.config' -> 'Config'
        # 'wicid' -> 'Main'
        parts = self.name.split(".")
        if len(parts) > 1:
            # Manually capitalize (CircuitPython str doesn't have capitalize())
            mod = parts[-1]
            self.module = mod[0].upper() + mod[1:] if mod else "Unknown"
        elif parts[0] == "wicid":
            self.module = "Main"
        else:
            # Manually capitalize
            mod = parts[0]
            self.module = mod[0].upper() + mod[1:] if mod else "Unknown"

    def critical(self, msg: str, exc_info: bool = False) -> None:
        """Log critical message."""
        self._log(CRITICAL, msg, exc_info=exc_info)

    def debug(self, msg: str, exc_info: bool = False) -> None:
        """Log a debug message."""
        self._log(DEBUG, msg, exc_info=exc_info)

    def error(self, msg: str, exc_info: bool = False) -> None:
        """Log error message."""
        self._log(ERROR, msg, exc_info=exc_info)

    def info(self, msg: str, exc_info: bool = False) -> None:
        """Log info message."""
        self._log(INFO, msg, exc_info=exc_info)

    def testing(self, msg: str) -> None:
        """
        Log test message at TESTING level.

        When global log level is set to TESTING, only testing() messages
        will be displayed, suppressing all other log output (INFO, WARNING, etc.).
        """
        self._log(TESTING, msg)

    def warning(self, msg: str, exc_info: bool = False) -> None:
        """Log warning message."""
        self._log(WARNING, msg, exc_info=exc_info)

    def _log(self, level: int, msg: str, exc_info: bool = False) -> None:
        """Internal logging method."""
        global _log_level, _LOGGED_FILE_ERROR
        if level >= _log_level:
            # Format message
            if level == TESTING:
                formatted_msg = msg
            else:
                level_name = _LEVEL_NAMES.get(level, "UNKNOWN")
                formatted_msg = f"[{level_name}: {self.module}] {msg}"

            # Always print to stdout
            print(formatted_msg)

            # Write to file if log_file is set
            if self._log_file is not None:
                try:
                    with open(self._log_file, "a") as f:
                        f.write(formatted_msg + "\n")
                    os.sync()  # Ensure file write is persisted to filesystem
                    _LOGGED_FILE_ERROR = False  # Reset on success
                except OSError as e:
                    # Only print filesystem errors once to avoid spam
                    if not _LOGGED_FILE_ERROR:
                        print(f"! Boot log write failed (OSError): {e}")
                        _LOGGED_FILE_ERROR = True
                except Exception as e:
                    if not _LOGGED_FILE_ERROR:
                        print(f"! Boot log write failed: {e}")
                        _LOGGED_FILE_ERROR = True

            # Only print traceback if the log level would be displayed
            if exc_info:
                try:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    if exc_type is not None:
                        traceback.print_exception(exc_type, exc_value, exc_tb)
                        sys.stdout.flush()
                except Exception:
                    pass


def configure_logging(log_level_str: str = "INFO") -> None:
    """
    Configure global logging level.

    Call this once at application startup to set the log level
    for all loggers created via logger().

    Args:
        log_level_str: Log level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                      Defaults to INFO if invalid.

    Example:
        configure_logging("DEBUG")
        logger('wicid').debug("This will be visible")
    """
    global _log_level

    levels = {
        "DEBUG": DEBUG,
        "INFO": INFO,
        "WARNING": WARNING,
        "ERROR": ERROR,
        "CRITICAL": CRITICAL,
        "TESTING": TESTING,
    }

    _log_level = levels.get(log_level_str.upper(), INFO)


def logger(name: str = "wicid", log_file: str | None = None) -> WicidLogger:
    """
    Get a logger instance for the given name.

    Args:
        name: Hierarchical logger name (e.g., 'wicid.wifi')
        log_file: Optional file path to write logs to (in addition to stdout)

    Returns:
        WicidLogger: Logger instance

    Example:
        logger("wicid.wifi").info("Connected")
        logger("wicid.boot", log_file="/boot_log.txt").info("Boot message")
    """
    return WicidLogger(name, log_file=log_file)
