"""
Smoke tests to verify test infrastructure works on CircuitPython.

These minimal tests ensure the test runner, unittest framework, and LED
feedback are functioning correctly on the device.
"""

import sys

# Add root to path for imports (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Import unittest framework
from unittest import TestCase


class TestSmoke(TestCase):
    """Basic smoke tests to verify test infrastructure."""

    def test_basic_assertion(self) -> None:
        """Verify basic assertions work."""
        self.assertTrue(True)
        self.assertFalse(False)
        self.assertEqual(1, 1)
        self.assertNotEqual(1, 2)

    def test_arithmetic(self) -> None:
        """Verify basic Python arithmetic."""
        self.assertEqual(2 + 2, 4)
        self.assertEqual(10 - 3, 7)
        self.assertEqual(3 * 4, 12)
        self.assertEqual(10 / 2, 5)

    def test_strings(self) -> None:
        """Verify string operations."""
        self.assertEqual("hello" + " " + "world", "hello world")
        self.assertTrue("test" in "this is a test")
        self.assertEqual(len("hello"), 5)

    def test_lists(self) -> None:
        """Verify list operations."""
        test_list = [1, 2, 3]
        self.assertEqual(len(test_list), 3)
        self.assertEqual(test_list[0], 1)
        test_list.append(4)
        self.assertEqual(len(test_list), 4)
