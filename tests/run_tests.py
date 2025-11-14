"""
CircuitPython Test Runner

Unified test runner for executing all WICID firmware tests.

Usage from command line (desktop Python):
    python tests/run_tests.py

Usage from REPL:
    >>> import tests
    >>> tests.run_all()

Or run specific test suites:
    >>> tests.run_unit()
    >>> tests.run_integration()
    >>> tests.run_functional()
"""

import sys
import os
import unittest
from unittest import run_class

# Add root to path (source files are in root on CircuitPython device)
sys.path.insert(0, '/')

# Import logging after path is set up
try:
    from logging_helper import get_logger
    logger = get_logger('wicid.tests')
except ImportError:
    # Fallback if logging not available
    class FallbackLogger:
        def info(self, msg): print(f"[INFO] {msg}")
        def warning(self, msg): print(f"[WARNING] {msg}")
        def error(self, msg): print(f"[ERROR] {msg}")
        def testing(self, msg): print(msg)
    logger = FallbackLogger()


def run_all_tests(verbosity=2, tick_callback=None):
    """Run all tests in the test suite.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)
        tick_callback: Optional callback to call between tests (e.g., for LED animation)

    Returns:
        TestResult object
    """
    logger.testing("\n" + "=" * 70)
    logger.testing("WICID FIRMWARE TEST SUITE")
    logger.testing("=" * 70)
    logger.testing("")

    # CircuitPython unittest doesn't have TestLoader.discover()
    # Manually import and add test modules
    suite = unittest.TestSuite()

    # Helper to add all TestCase classes from a module
    def add_tests_from_module(module_name):
        try:
            module = __import__(module_name, None, None, ['*'])
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, unittest.TestCase) and attr is not unittest.TestCase:
                    suite.addTest(attr)
        except ImportError as e:
            msg = f"Could not import {module_name}: {e}"
            logger.warning(msg)
            logger.testing(f"Warning: {msg}")
        except Exception as e:
            msg = f"Error loading {module_name}: {e}"
            logger.error(msg)
            logger.testing(f"Error: {msg}")

    # Automatically discover all test_*.py files in test directories
    def discover_tests_in_directory(dir_path, package_prefix):
        """Scan directory for test_*.py files and add them to the suite."""
        try:
            files = os.listdir(dir_path)
            for filename in sorted(files):
                # Look for test_*.py files (but not __init__.py)
                if filename.startswith('test_') and filename.endswith('.py'):
                    # Convert filename to module name (remove .py)
                    module_name = filename[:-3]
                    # Import as package.module (e.g., 'unit.test_smoke')
                    full_module_name = f"{package_prefix}.{module_name}"
                    add_tests_from_module(full_module_name)
        except OSError:
            # Directory doesn't exist or can't be read - silently skip
            pass

    # Auto-discover tests from all test directories
    discover_tests_in_directory('/tests/unit', 'unit')
    discover_tests_in_directory('/tests/integration', 'integration')
    discover_tests_in_directory('/tests/functional', 'functional')

    # Run tests with optional tick callback between tests
    runner = unittest.TestRunner()

    # If tick callback provided, wrap test execution to call it between tests
    if tick_callback:
        original_run = runner.run
        def run_with_tick(suite):
            # Get test result
            result = unittest.TestResult()
            # Run each test class individually, calling tick between them
            for test_class in suite.tests:
                run_class(test_class, result)
                tick_callback()  # Update animation between tests
            logger.testing('Ran %d tests\n' % result.testsRun)
            if result.failuresNum > 0 or result.errorsNum > 0:
                logger.testing('FAILED (failures=%d, errors=%d)' % (result.failuresNum, result.errorsNum))
            else:
                msg = 'OK'
                if result.skippedNum > 0:
                    msg += ' (%d skipped)' % result.skippedNum
                logger.testing(msg)
            return result
        runner.run = run_with_tick

    result = runner.run(suite)

    # Summary
    logger.testing("\n" + "=" * 70)
    logger.testing("TEST SUMMARY")
    logger.testing("=" * 70)
    logger.testing(f"Tests run: {result.testsRun}")
    logger.testing(f"Failures: {result.failuresNum}")
    logger.testing(f"Errors: {result.errorsNum}")
    logger.testing(f"Skipped: {result.skippedNum}")

    if result.wasSuccessful():
        logger.testing("\nALL TESTS PASSED")
    else:
        logger.testing("\nSOME TESTS FAILED")

    logger.testing("=" * 70)
    logger.testing("")

    return result


def run_unit_tests(verbosity=2):
    """Run only unit tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    logger.testing("\n" + "=" * 70)
    logger.testing("UNIT TESTS")
    logger.testing("=" * 70)
    logger.testing("")

    # For now, just call the main test runner
    # Can be refined later to only run unit tests
    return run_all_tests(verbosity)


def run_integration_tests(verbosity=2):
    """Run only integration tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    logger.testing("\n" + "=" * 70)
    logger.testing("INTEGRATION TESTS")
    logger.testing("=" * 70)
    logger.testing("")
    logger.testing("No integration tests yet.")
    logger.testing("=" * 70)
    return unittest.TestResult()


def run_functional_tests(verbosity=2):
    """Run only functional tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    logger.testing("\n" + "=" * 70)
    logger.testing("FUNCTIONAL TESTS")
    logger.testing("=" * 70)
    logger.testing("")
    logger.testing("No functional tests yet.")
    logger.testing("=" * 70)
    return unittest.TestResult()


def main():
    """Main entry point for test runner."""
    result = run_all_tests(verbosity=2)

    # Exit with error code if tests failed
    sys.exit(result.failuresNum > 0 or result.errorsNum > 0)


if __name__ == '__main__':
    main()
