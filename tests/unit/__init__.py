"""
Unit Tests (Desktop-Only)

Tests for individual components in isolation using full mocking.
Unit tests run only on desktop Python, not on CircuitPython devices.

Run via command line:
    python tests/run_tests.py

Or run specific test module:
    python -m unittest tests.unit.test_<module_name>
"""

import os
import sys

IS_CIRCUITPYTHON = hasattr(sys, "implementation") and sys.implementation.name == "circuitpython"

if IS_CIRCUITPYTHON:
    # Unit tests should not run on CircuitPython
    raise ImportError("Unit tests are desktop-only. Use integration tests on device.")


# Mock CircuitPython modules BEFORE any other imports
# This is critical for VS Code test discovery, which imports test modules directly
def _mock_circuitpython_modules() -> None:
    """Mock CircuitPython modules for desktop testing."""
    # Temporarily remove tests directory from path to import standard unittest.mock
    # because tests/unittest.py shadows the standard unittest package
    _tests_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _paths_removed = []
    while _tests_dir in sys.path:
        sys.path.remove(_tests_dir)
        _paths_removed.append(_tests_dir)

    try:
        from unittest.mock import MagicMock
    finally:
        # Restore paths (in reverse order to maintain roughly same order)
        for _p in reversed(_paths_removed):
            sys.path.insert(0, _p)

        # Remove cached standard library unittest so our custom one is used
        # (importing unittest.mock caches the standard library unittest)
        if "unittest" in sys.modules:
            del sys.modules["unittest"]

    # List of modules to mock - these must be mocked BEFORE other imports
    modules = [
        "adafruit_hashlib",
        "adafruit_httpserver",
        "adafruit_ntp",
        "adafruit_requests",
        "board",
        "digitalio",
        "microcontroller",
        "neopixel",
        "rtc",
        "socketpool",
        "ssl",
        "storage",
        "supervisor",
        "usb_cdc",
        "wifi",
    ]

    for mod_name in modules:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()


# Ensure src directory is in Python path for imports
# This is critical for VS Code test discovery
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_src_dir = os.path.join(_project_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Mock modules immediately when this package is imported
# This must happen after path setup but before any other imports
_mock_circuitpython_modules()

# Desktop: Use standard library unittest (not the CircuitPython shim)
# We need to ensure we get the real unittest, not tests/unittest.py
_tests_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_paths_removed = []
while _tests_dir in sys.path:
    sys.path.remove(_tests_dir)
    _paths_removed.append(_tests_dir)

# Import standard library unittest
import unittest  # noqa: E402

# Restore paths
for _p in reversed(_paths_removed):
    sys.path.insert(0, _p)

# Re-export TestCase for convenience - tests can use: from tests.unit import TestCase
TestCase = unittest.TestCase

__all__ = ["TestCase"]
