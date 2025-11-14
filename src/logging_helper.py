"""
Logging Helper - Simple custom logger for WICID.

Provides a straightforward logging solution optimized for CircuitPython.
Clean, explicit, and easy to extend without fighting library limitations.
"""


# Global log level
_log_level = 20  # INFO

# Log level constants
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50
TESTING = 60  # Suppresses all logs except test output

_LEVEL_NAMES = {
    10: "DEBUG",
    20: "INFO",
    30: "WARNING",
    40: "ERROR",
    50: "CRITICAL",
    60: "TESTING"
}


class WicidLogger:
    """
    Simple logger for WICID firmware.
    
    Designed for CircuitPython simplicity - no complex handler propagation,
    just straightforward formatted output.
    
    Format: [LEVEL: ModuleName] message
    
    Example:
        logger = get_logger('wicid.wifi')
        logger.info("Connected")  # Output: [INFO: Wifi] Connected
    """
    
    def __init__(self, name):
        """
        Initialize logger with a hierarchical name.
        
        Args:
            name: Logger name (e.g., 'wicid.wifi', 'wicid.config')
        """
        self.name = name if name else 'main'
        
        # Extract readable module name from hierarchical name
        # 'wicid.wifi' -> 'Wifi'
        # 'wicid.config' -> 'Config'
        # 'wicid' -> 'Main'
        parts = self.name.split('.')
        if len(parts) > 1:
            # Manually capitalize (CircuitPython str doesn't have capitalize())
            mod = parts[-1]
            self.module = mod[0].upper() + mod[1:] if mod else 'Unknown'
        elif parts[0] == 'wicid':
            self.module = 'Main'
        else:
            # Manually capitalize
            mod = parts[0]
            self.module = mod[0].upper() + mod[1:] if mod else 'Unknown'
    
    def _log(self, level, msg):
        """Internal logging method."""
        global _log_level
        if level >= _log_level:
            # TESTING level outputs raw (no prefix) for clean test output
            if level == TESTING:
                print(msg)
            else:
                level_name = _LEVEL_NAMES.get(level, "UNKNOWN")
                print("[%s: %s] %s" % (level_name, self.module, msg))
    
    def debug(self, msg, exc_info=False):
        """Log debug message."""
        self._log(DEBUG, msg)
    
    def info(self, msg, exc_info=False):
        """Log info message."""
        self._log(INFO, msg)
    
    def warning(self, msg, exc_info=False):
        """Log warning message."""
        self._log(WARNING, msg)
    
    def error(self, msg, exc_info=False):
        """Log error message."""
        self._log(ERROR, msg)
        if exc_info:
            try:
                import sys
                import traceback
                exc_type, exc_value, exc_tb = sys.exc_info()
                if exc_type is not None:
                    traceback.print_exception(exc_type, exc_value, exc_tb)
            except:
                pass
    
    def critical(self, msg, exc_info=False):
        """Log critical message."""
        self._log(CRITICAL, msg)
        if exc_info:
            try:
                import sys
                import traceback
                exc_type, exc_value, exc_tb = sys.exc_info()
                if exc_type is not None:
                    traceback.print_exception(exc_type, exc_value, exc_tb)
            except:
                pass

    def testing(self, msg):
        """
        Log test message at TESTING level.

        When global log level is set to TESTING, only testing() messages
        will be displayed, suppressing all other log output (INFO, WARNING, etc.).
        """
        self._log(TESTING, msg)


def get_logger(name='wicid'):
    """
    Get a logger instance for the given name.
    
    Args:
        name: Hierarchical logger name (e.g., 'wicid.wifi')
    
    Returns:
        WicidLogger: Logger instance
        
    Example:
        logger = get_logger('wicid.wifi')
        logger.info("Connected")
    """
    return WicidLogger(name)


def configure_logging(log_level_str="INFO"):
    """
    Configure global logging level.
    
    Call this once at application startup to set the log level
    for all loggers created via get_logger().
    
    Args:
        log_level_str: Log level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                      Defaults to INFO if invalid.
    
    Returns:
        WicidLogger: Root logger instance (for compatibility)
        
    Example:
        configure_logging("DEBUG")
        logger = get_logger('wicid')
        logger.debug("This will be visible")
    """
    global _log_level
    
    levels = {
        "DEBUG": DEBUG,
        "INFO": INFO,
        "WARNING": WARNING,
        "ERROR": ERROR,
        "CRITICAL": CRITICAL,
        "TESTING": TESTING
    }

    _log_level = levels.get(log_level_str.upper(), INFO)
    return get_logger('wicid')
