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

import os
import sys
import traceback
import unittest

# Add root to path (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Add tests to path for custom unittest
if "/tests" not in sys.path:
    sys.path.insert(0, "/tests")

# Import custom TestResult from our unittest implementation
from unittest import TestResult as CustomTestResult

# Import logging after path is set up
from core.app_typing import Any, Callable
from core.logging_helper import logger

TEST_LOG = logger("wicid.tests")


def _restore_hardware_input_manager() -> None:
    """
    Reinitialize InputManager with real hardware after tests complete.

    Tests replace the controller with mocks; this helper ensures the
    production InputManager is recreated so the physical button works
    again without requiring a device reset.
    """
    try:
        from managers.input_manager import InputManager

        InputManager.instance()
    except Exception:
        # If InputManager can't be imported (e.g., desktop host)
        # we silently skip hardware restoration.
        TEST_LOG.debug("Skipping InputManager hardware restoration after tests")


class GroupedTestResult(unittest.TestResult):
    """Custom TestResult that groups tests by module and class.

    CircuitPython's unittest doesn't use the standard addSuccess/addFailure
    interface, so we need to manually track tests as they run.
    """

    def __init__(self) -> None:
        super().__init__()
        self.test_results: dict[
            str, dict[str, list[tuple[str, str, str | None]]]
        ] = {}  # module_name -> class_name -> list of (test_name, status, error_msg)
        self.current_test_info: tuple[str, str, str] | None = None  # (module_name, class_name, test_name)

    def start_test(self, module_name: str, class_name: str, test_name: str) -> None:
        """Called when a test starts."""
        if module_name not in self.test_results:
            self.test_results[module_name] = {}
        if class_name not in self.test_results[module_name]:
            self.test_results[module_name][class_name] = []
        self.current_test_info = (module_name, class_name, test_name)

    def record_success(self) -> None:
        """Record a successful test."""
        if self.current_test_info:
            module_name, class_name, test_name = self.current_test_info
            self.test_results[module_name][class_name].append((test_name, "PASS", None))
            self.current_test_info = None

    def record_failure(self, error_msg: str) -> None:
        """Record a failed test."""
        if self.current_test_info:
            module_name, class_name, test_name = self.current_test_info
            self.test_results[module_name][class_name].append((test_name, "FAIL", error_msg))
            self.current_test_info = None

    def record_error(self, error_msg: str) -> None:
        """Record an errored test."""
        if self.current_test_info:
            module_name, class_name, test_name = self.current_test_info
            self.test_results[module_name][class_name].append((test_name, "ERROR", error_msg))
            self.current_test_info = None

    def record_skip(self, reason: str) -> None:
        """Record a skipped test."""
        if self.current_test_info:
            module_name, class_name, test_name = self.current_test_info
            self.test_results[module_name][class_name].append((test_name, "SKIP", reason))
            self.current_test_info = None


def run_all_tests(verbosity: int = 2, tick_callback: Callable[[], None] | None = None) -> Any:
    """Run all tests in the test suite.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)
        tick_callback: Optional callback to call between tests (e.g., for LED animation)

    Returns:
        TestResult object
    """
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("WICID FIRMWARE TEST SUITE")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    # CircuitPython unittest doesn't have TestLoader.discover()
    # Manually import and add test modules
    suite: Any = unittest.TestSuite()

    # Track test modules by name for organization
    test_modules = {}  # module_name -> (dir_path, package_prefix, filename)

    # Helper to add all TestCase classes from a module
    def add_tests_from_module(module_name: str, dir_path: str, filename: str) -> None:
        module = __import__(module_name, None, None, ["*"])
        test_modules[module_name] = (dir_path, filename)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, unittest.TestCase) and attr is not unittest.TestCase:
                suite.addTest(attr)

    # Automatically discover all test_*.py files in test directories
    def discover_tests_in_directory(dir_path: str, package_prefix: str) -> None:
        """Scan directory for test_*.py files and add them to the suite."""
        try:
            files = os.listdir(dir_path)
        except OSError:
            # Directory doesn't exist or can't be read - skip silently
            return
        for filename in sorted(files):
            # Look for test_*.py files (but not __init__.py)
            if filename == "__init__.py":
                continue
            if filename.startswith("test_") and filename.endswith(".py"):
                # Convert filename to module name (remove .py)
                module_name = filename[:-3]
                # Import as package.module (e.g., 'unit.test_smoke')
                full_module_name = f"{package_prefix}.{module_name}"
                try:
                    add_tests_from_module(full_module_name, dir_path, filename)
                except Exception as e:
                    # Log import error but continue with other tests
                    TEST_LOG.warning(f"Failed to import test module {full_module_name}: {e}")

    # Auto-discover tests from all test directories
    discover_tests_in_directory("/tests/unit", "unit")
    discover_tests_in_directory("/tests/integration", "integration")
    discover_tests_in_directory("/tests/functional", "functional")

    # Require at least one test to be discovered in Test Mode
    if suite.countTestCases() == 0:
        raise RuntimeError("No tests discovered in /tests directories. This is a blocking error in Test Mode.")

    # Create custom result collector and output capture
    grouped_result = GroupedTestResult()
    result: Any = CustomTestResult()

    # Run tests, grouping by module and class, suppressing default output
    def format_error(e: Exception) -> str:
        """Format exception with full traceback."""
        return "".join(traceback.format_exception(e))

    for test_class in suite:
        if tick_callback:
            tick_callback()  # Update animation between test classes

        # Get module name for this test class
        class_module = test_class.__module__
        class_name = test_class.__name__

        # Extract module display name (e.g., 'unit.test_smoke' -> 'test_smoke')
        module_display_name = class_module
        if "." in class_module:
            module_display_name = class_module.split(".")[-1]

        # Get the module object to access its __file__ if available
        module_obj = sys.modules.get(class_module)
        if module_obj and hasattr(module_obj, "__file__"):
            module_path = module_obj.__file__
            if module_path:
                # Split by '/' and take the last part (basename)
                path_parts = module_path.split("/")
                filename = path_parts[-1] if path_parts else module_path
                if filename.endswith(".py"):
                    module_display_name = filename[:-3]

        # Run the test class, capturing output and tracking results
        test_instance = None
        try:
            # Call setUpClass if it exists
            if hasattr(test_class, "setUpClass"):
                try:
                    test_class.setUpClass()
                except Exception as e:
                    # Error in setUpClass - record and skip this class
                    error_msg = format_error(e)
                    grouped_result.start_test(module_display_name, class_name, "setUpClass")
                    grouped_result.record_error(error_msg)
                    result.errorsNum += 1
                    continue  # Skip to next test class

            # Instantiate the test class to get test methods
            test_instance = test_class()

            # Get all test method names (must be callable and start with 'test')
            test_methods = [
                name
                for name in dir(test_instance)
                if name.startswith("test") and callable(getattr(test_instance, name))
            ]

            # Run each test method individually
            for test_method_name in sorted(test_methods):
                test_method = getattr(test_instance, test_method_name)

                # Track this test in grouped results
                grouped_result.start_test(module_display_name, class_name, test_method_name)

                try:
                    # Run setUp
                    test_instance.setUp()

                    try:
                        # Run the test
                        result.testsRun += 1
                        test_method()

                        # Test passed
                        grouped_result.record_success()

                    except AssertionError as e:
                        # Test failed
                        error_msg = str(e.args[0]) if e.args else "no assert message"
                        grouped_result.record_failure(error_msg)
                        result.failuresNum += 1

                    except (SystemExit, KeyboardInterrupt):
                        raise

                    except Exception as e:
                        # Check if it's a SkipTest (CircuitPython might not have it in unittest)
                        skip_test = None
                        try:
                            from unittest import SkipTest

                            if isinstance(e, SkipTest):
                                skip_test = e
                        except ImportError:
                            # SkipTest might be at module level
                            try:
                                import unittest as unittest_mod

                                if hasattr(unittest_mod, "SkipTest") and isinstance(e, unittest_mod.SkipTest):
                                    skip_test = e
                            except Exception:
                                pass

                        if skip_test:
                            # Test was skipped
                            reason = str(skip_test.args[0]) if skip_test.args else "no reason"
                            grouped_result.record_skip(reason)
                            result.skippedNum += 1
                            result.testsRun -= 1  # CircuitPython doesn't count skipped tests
                        else:
                            # Test errored
                            error_msg = format_error(e)
                            grouped_result.record_error(error_msg)
                            result.errorsNum += 1

                    finally:
                        # Run tearDown (only if test_instance was successfully created)
                        if test_instance is not None:
                            test_instance.tearDown()

                except Exception as e:
                    # Error in setUp or tearDown
                    error_msg = format_error(e)
                    grouped_result.record_error(error_msg)
                    result.errorsNum += 1

        except Exception as exc:
            # Error instantiating test class
            error_msg = format_error(exc)
            grouped_result.start_test(module_display_name, class_name, "__init__")
            grouped_result.record_error(error_msg)
            result.errorsNum += 1
        finally:
            # Always call tearDownClass if it exists
            if hasattr(test_class, "tearDownClass"):
                test_class.tearDownClass()

    # Display results grouped by file and class
    TEST_LOG.testing("")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("TEST RESULTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_skipped = 0

    # Sort modules for consistent output
    for module_name in sorted(grouped_result.test_results.keys()):
        module_data = grouped_result.test_results[module_name]

        TEST_LOG.testing(f"Test File: {module_name}")
        TEST_LOG.testing("-" * 70)

        # Sort classes for consistent output
        for class_name in sorted(module_data.keys()):
            class_tests = module_data[class_name]

            TEST_LOG.testing(f"  Test Class: {class_name}")

            # Display each test in this class
            for test_name, status, error_info in class_tests:
                total_tests += 1
                status_symbol = "✓" if status == "PASS" else "✗" if status in ("FAIL", "ERROR") else "⊘"
                status_text = status

                TEST_LOG.testing(f"    {status_symbol} {test_name} - {status_text}")

                if status == "PASS":
                    total_passed += 1
                elif status == "FAIL":
                    total_failed += 1
                elif status == "ERROR":
                    total_errors += 1
                elif status == "SKIP":
                    total_skipped += 1

                # Show error details for failures/errors
                if status in ("FAIL", "ERROR") and error_info:
                    # Format error message
                    try:
                        err_msg = str(error_info)
                        # Truncate long error messages and limit lines
                        lines = err_msg.split("\n")
                        if len(lines) > 10:
                            err_msg = "\n".join(lines[:10]) + f"\n... ({len(lines) - 10} more lines)"
                        elif len(err_msg) > 300:
                            err_msg = err_msg[:300] + "..."
                        # Indent error message
                        for line in err_msg.split("\n"):
                            TEST_LOG.testing(f"      {line}")
                    except Exception:
                        pass

            TEST_LOG.testing("")

        TEST_LOG.testing("")

    # Update result object counts (for compatibility)
    result.testsRun = total_tests
    result.failuresNum = total_failed
    result.errorsNum = total_errors
    result.skippedNum = total_skipped

    # Summary
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("TEST SUMMARY")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing(f"Tests run: {total_tests}")
    TEST_LOG.testing(f"Passed: {total_passed}")
    if total_failed > 0:
        TEST_LOG.testing(f"Failed: {total_failed}")
    if total_errors > 0:
        TEST_LOG.testing(f"Errors: {total_errors}")
    if total_skipped > 0:
        TEST_LOG.testing(f"Skipped: {total_skipped}")

    if result.wasSuccessful():
        TEST_LOG.testing("\n✓ ALL TESTS PASSED")
    else:
        TEST_LOG.testing("\n✗ SOME TESTS FAILED")

    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    _restore_hardware_input_manager()
    return result


def run_unit_tests(verbosity: int = 2) -> Any:
    """Run only unit tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("UNIT TESTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    # For now, just call the main test runner
    # Can be refined later to only run unit tests
    return run_all_tests(verbosity)


def run_integration_tests(verbosity: int = 2) -> Any:
    """Run only integration tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("INTEGRATION TESTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")
    TEST_LOG.testing("No integration tests yet.")
    TEST_LOG.testing("=" * 70)
    return unittest.TestResult()


def run_functional_tests(verbosity: int = 2) -> Any:
    """Run only functional tests.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("FUNCTIONAL TESTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")
    TEST_LOG.testing("No functional tests yet.")
    TEST_LOG.testing("=" * 70)
    return unittest.TestResult()


def main() -> None:
    """Main entry point for test runner."""
    result = run_all_tests(verbosity=2)

    # Exit with error code if tests failed
    exit_code = 1 if (result.failuresNum > 0 or result.errorsNum > 0) else 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
