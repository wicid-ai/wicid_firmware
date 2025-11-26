"""
Unit Tests

Tests for individual components in isolation.
Each test should focus on a single unit of functionality.

Run via REPL:
    >>> import tests
    >>> tests.run_unit()

Or run specific test module:
    >>> from tests.unit.test_<module_name> import TestClassName
    >>> import unittest
    >>> unittest.main(module='tests.unit.test_<module_name>', exit=False)
"""

import sys

# Add root to path for imports (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Add tests directory to path for test helpers
if "/tests" not in sys.path:
    sys.path.insert(0, "/tests")

# Import and re-export TestCase for convenience
from unittest import TestCase

# Re-export for convenience - tests can use: from tests.unit import TestCase
__all__ = ["TestCase"]
