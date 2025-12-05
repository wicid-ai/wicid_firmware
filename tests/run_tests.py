"""
WICID Firmware Test Runner

Unified test runner for executing WICID firmware tests.

Testing Philosophy:
- Unit tests: Desktop-only, fully mocked, fast feedback (pre-commit integration)
- Integration/Functional tests: On-device only, real hardware validation

Desktop (python tests/run_tests.py):
    Runs unit tests only. Uses MagicMock for CircuitPython modules.

On-device (CircuitPython REPL):
    >>> import tests
    >>> tests.run_all()           # Integration + functional tests
    >>> tests.run_integration()   # Integration tests only
    >>> tests.run_functional()    # Functional tests only
"""

import os
import sys
import traceback

# Add root to path (source files are in root on CircuitPython device)
IS_CIRCUITPYTHON = hasattr(sys, "implementation") and sys.implementation.name == "circuitpython"

if IS_CIRCUITPYTHON:
    sys.path.insert(0, "/")
    # Add /tests to path so "integration.test_foo" imports work
    # (looks for /tests/integration/test_foo.py)
    sys.path.insert(0, "/tests")
    TEST_ROOT = "/tests"
else:
    # Desktop execution - add src and project root to path
    # CRITICAL: src must be added FIRST and remain accessible
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    src_dir = os.path.join(project_root, "src")

    # Add src FIRST so core modules can be imported even when tests/ is temporarily removed
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    # Add project_root so that 'tests' package can be imported (tests.unit.test_smoke)
    # This must be added, not tests/ directory itself
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    TEST_ROOT = current_dir


def mock_circuitpython_modules() -> None:
    """Mock CircuitPython modules for desktop testing."""
    import sys

    # Temporarily remove tests directory from path to import standard unittest.mock
    # because tests/unittest.py shadows the standard unittest package
    # IMPORTANT: Only remove tests/, keep src/ and project_root in path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_restore = []

    # Remove only the tests directory, not src or project_root
    while current_dir in sys.path:
        sys.path.remove(current_dir)
        paths_to_restore.append(current_dir)

    try:
        from unittest.mock import MagicMock
    finally:
        # Restore paths (in reverse order to maintain roughly same order)
        for p in reversed(paths_to_restore):
            sys.path.insert(0, p)

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


if not IS_CIRCUITPYTHON:
    mock_circuitpython_modules()

# Import unittest - use standard library on desktop, custom shim on CircuitPython
if IS_CIRCUITPYTHON:
    import unittest  # noqa: E402  # Uses tests/unittest.py on device
else:
    # Desktop: Use standard library unittest (not tests/unittest.py)
    # Temporarily remove tests/ from path to get real unittest
    _tests_dir = os.path.dirname(os.path.abspath(__file__))
    _paths_removed = []
    while _tests_dir in sys.path:
        sys.path.remove(_tests_dir)
        _paths_removed.append(_tests_dir)

    import unittest  # noqa: E402

    # Restore paths
    for _p in reversed(_paths_removed):
        sys.path.insert(0, _p)

# Import logging after path is set up
from core.app_typing import Any, Callable  # noqa: E402
from core.logging_helper import configure_logging, logger  # noqa: E402

# Configure logging to TESTING level to suppress all log output except test output
configure_logging("TESTING")

# Import suppress - use stdlib on desktop, custom implementation on CircuitPython
if IS_CIRCUITPYTHON:
    from utils.utils import suppress  # noqa: E402
else:
    from contextlib import suppress  # type: ignore[assignment]  # noqa: E402

TEST_LOG = logger("wicid.tests")


class _CircuitPythonTestResult:
    """Test result class with CircuitPython-compatible attributes.

    CircuitPython's unittest.TestResult has different attributes than the standard library.
    This class provides a consistent interface that works on both platforms.
    """

    def __init__(self) -> None:
        self.testsRun: int = 0
        self.failuresNum: int = 0
        self.errorsNum: int = 0
        self.skippedNum: int = 0
        self.failures: list[Any] = []
        self.errors: list[Any] = []

    def wasSuccessful(self) -> bool:
        """Return True if all tests passed."""
        return self.failuresNum == 0 and self.errorsNum == 0


def _restore_hardware_input_manager() -> None:
    """
    Skip hardware restoration after tests.

    CircuitPython hardware is in an inconsistent state after mocking during tests.
    Attempting to reinitialize real hardware causes hard faults. A device reset
    is required anyway to restore normal operation, so this restoration is skipped.
    """
    TEST_LOG.debug("Skipping InputManager hardware restoration (device reset required after tests)")


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


def _format_test_results(
    grouped_result: GroupedTestResult,
    elapsed_time: float,
    total_tests: int,
    total_passed: int,
    total_failed: int,
    total_errors: int,
    total_skipped: int = 0,
) -> None:
    """Format and display test results.

    Args:
        grouped_result: GroupedTestResult with collected test data
        elapsed_time: Total test run time in seconds
        total_tests: Total number of tests run
        total_passed: Number of passed tests
        total_failed: Number of failed tests
        total_errors: Number of errored tests
        total_skipped: Number of skipped tests
    """
    TEST_LOG.testing("")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("TEST RESULTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    for module_name in sorted(grouped_result.test_results.keys()):
        module_data = grouped_result.test_results[module_name]

        TEST_LOG.testing(f"📁 {module_name}.py")
        TEST_LOG.testing("-" * 70)

        for class_name in sorted(module_data.keys()):
            class_tests = module_data[class_name]

            TEST_LOG.testing(f"  📋 {class_name}")

            for test_name, status, error_info in class_tests:
                if status == "PASS":
                    TEST_LOG.testing(f"    ✅ {test_name}")
                elif status == "FAIL":
                    TEST_LOG.testing(f"    ❌ {test_name} - FAIL")
                    if error_info:
                        for line in str(error_info).split("\n")[:3]:
                            TEST_LOG.testing(f"      {line}")
                elif status == "ERROR":
                    TEST_LOG.testing(f"    ❌ {test_name} - ERROR")
                    if error_info:
                        for line in str(error_info).split("\n")[:3]:
                            TEST_LOG.testing(f"      {line}")
                elif status == "SKIP":
                    TEST_LOG.testing(f"    ⊘ {test_name} - SKIP")

            TEST_LOG.testing("")

    # Summary
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("TEST SUMMARY")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing(f"Tests run: {total_tests}")
    TEST_LOG.testing(f"Passed:    {total_passed}")
    if total_failed > 0:
        TEST_LOG.testing(f"Failed:    {total_failed}")
    if total_errors > 0:
        TEST_LOG.testing(f"Errors:    {total_errors}")
    if total_skipped > 0:
        TEST_LOG.testing(f"Skipped:   {total_skipped}")
    TEST_LOG.testing(f"Time:      {elapsed_time:.3f}s")

    if total_failed == 0 and total_errors == 0:
        TEST_LOG.testing("\n✅ ALL TESTS PASSED")
    else:
        TEST_LOG.testing("\n❌ SOME TESTS FAILED")

    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")


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

    # Desktop: Use standard unittest TextTestRunner for simplicity
    if not IS_CIRCUITPYTHON:
        return _run_desktop_tests(verbosity)

    # CircuitPython: Use custom test discovery and execution
    return _run_circuitpython_tests(verbosity, tick_callback)


def _run_desktop_tests(verbosity: int = 2) -> Any:
    """Run unit tests on desktop with formatted output."""
    import time as time_mod

    start_time = time_mod.time()

    # Discover unit tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    test_modules: dict[str, list[tuple[str, type]]] = {}  # module_name -> [(class_name, class)]

    unit_dir = os.path.join(TEST_ROOT, "unit")
    try:
        files = os.listdir(unit_dir)
    except OSError as e:
        raise RuntimeError(f"Cannot read unit test directory: {unit_dir}") from e

    for filename in sorted(files):
        if filename == "__init__.py":
            continue
        if filename.startswith("test_") and filename.endswith(".py"):
            module_name = filename[:-3]
            full_module_name = f"tests.unit.{module_name}"
            try:
                module = __import__(full_module_name, None, None, ["*"])
                test_modules[module_name] = []
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, unittest.TestCase) and attr is not unittest.TestCase:
                        test_modules[module_name].append((attr_name, attr))
                        suite.addTests(loader.loadTestsFromTestCase(attr))
            except Exception as e:
                TEST_LOG.warning(f"Failed to import test module {full_module_name}: {e}")

    if suite.countTestCases() == 0:
        raise RuntimeError("No unit tests discovered.")

    # Run tests and collect results
    grouped_result = GroupedTestResult()
    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0

    for module_name, classes in sorted(test_modules.items()):
        for class_name, test_class in sorted(classes, key=lambda x: x[0]):
            # Call setUpClass if it exists
            if hasattr(test_class, "setUpClass"):
                try:
                    test_class.setUpClass()
                except Exception as e:
                    # Record error for the class
                    grouped_result.start_test(module_name, class_name, "setUpClass")
                    grouped_result.record_error(f"{type(e).__name__}: {e}")
                    total_errors += 1
                    total_tests += 1
                    continue  # Skip all tests in this class

            try:
                # Get test methods
                test_methods = loader.getTestCaseNames(test_class)

                for method_name in test_methods:
                    grouped_result.start_test(module_name, class_name, method_name)
                    total_tests += 1

                    try:
                        test_instance = test_class(method_name)
                        test_instance.setUp()
                        try:
                            getattr(test_instance, method_name)()
                            grouped_result.record_success()
                            total_passed += 1
                        except AssertionError as e:
                            error_msg = str(e) if str(e) else "Assertion failed"
                            grouped_result.record_failure(error_msg)
                            total_failed += 1
                        except Exception as e:
                            error_msg = f"{type(e).__name__}: {e}"
                            grouped_result.record_error(error_msg)
                            total_errors += 1
                        finally:
                            test_instance.tearDown()
                    except Exception as e:
                        error_msg = f"{type(e).__name__}: {e}"
                        grouped_result.record_error(error_msg)
                        total_errors += 1
            finally:
                # Always call tearDownClass if it exists
                if hasattr(test_class, "tearDownClass"):
                    with suppress(Exception):
                        test_class.tearDownClass()

    elapsed_time = time_mod.time() - start_time

    # Display formatted results
    _format_test_results(grouped_result, elapsed_time, total_tests, total_passed, total_failed, total_errors)

    # Create a result object with compatible interface
    class DesktopTestResult:
        def __init__(self) -> None:
            self.failures: list[Any] = []
            self.errors: list[Any] = []
            self.testsRun = total_tests
            self.failuresNum = total_failed
            self.errorsNum = total_errors

        def wasSuccessful(self) -> bool:
            return total_failed == 0 and total_errors == 0

    result = DesktopTestResult()
    # Populate failures/errors for compatibility
    for module_name, module_data in grouped_result.test_results.items():
        for class_name, tests in module_data.items():
            for test_name, status, error_info in tests:
                if status == "FAIL":
                    result.failures.append((f"{module_name}.{class_name}.{test_name}", error_info))
                elif status == "ERROR":
                    result.errors.append((f"{module_name}.{class_name}.{test_name}", error_info))

    return result


def _run_circuitpython_tests(verbosity: int = 2, tick_callback: Callable[[], None] | None = None) -> Any:
    """Run integration/functional tests on CircuitPython."""
    suite: Any = unittest.TestSuite()

    # Track test modules by name for organization
    test_modules = {}  # module_name -> (dir_path, package_prefix, filename)

    # Helper to add all TestCase classes from a module
    def add_tests_from_module(module_name: str, dir_path: str, filename: str) -> None:
        module = __import__(module_name, None, None, ["*"])
        test_modules[module_name] = (dir_path, filename)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            # Check if it's a TestCase-like class by duck typing
            # This avoids issues with different TestCase imports (tests.unittest vs unittest)
            # Exclude "TestCase" itself - only include subclasses
            if (
                isinstance(attr, type)
                and attr_name.startswith("Test")
                and attr_name != "TestCase"
                and hasattr(attr, "run")
                and hasattr(attr, "setUp")
            ):
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
            # Look for test_*.py files (but not __init__.py or hidden files)
            if filename.startswith(".") or filename == "__init__.py":
                continue
            if filename.startswith("test_") and filename.endswith(".py"):
                # Convert filename to module name (remove .py)
                module_name = filename[:-3]
                # Import as package.module (e.g., 'integration.test_recovery')
                full_module_name = f"{package_prefix}.{module_name}"
                try:
                    add_tests_from_module(full_module_name, dir_path, filename)
                except Exception as e:
                    # Log import error but continue with other tests
                    TEST_LOG.warning(f"Failed to import test module {full_module_name}: {e}")

    # On-device: integration and functional tests only (NOT unit tests)
    discover_tests_in_directory(f"{TEST_ROOT}/integration", "integration")
    discover_tests_in_directory(f"{TEST_ROOT}/functional", "functional")

    # If no tests discovered, return early with informative message (not an error)
    if suite.countTestCases() == 0:
        TEST_LOG.testing("No integration or functional tests found.")
        TEST_LOG.testing("Integration tests go in: tests/integration/test_*.py")
        TEST_LOG.testing("Functional tests go in: tests/functional/test_*.py")
        TEST_LOG.testing("")
        TEST_LOG.testing("Unit tests are desktop-only. Run with: python tests/run_tests.py")
        TEST_LOG.testing("=" * 70)
        return _CircuitPythonTestResult()  # Return empty result

    # Create custom result collector and output capture
    grouped_result = GroupedTestResult()
    result = _CircuitPythonTestResult()

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

                # Log test start for visibility during long-running tests
                TEST_LOG.testing(f"▶ {class_name}.{test_method_name}")

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

    # Calculate passed count from tracked values
    total_passed = result.testsRun - result.failuresNum - result.errorsNum - result.skippedNum

    # Display formatted results (elapsed_time not tracked in CircuitPython version)
    _format_test_results(
        grouped_result,
        elapsed_time=0.0,  # CircuitPython doesn't track elapsed time
        total_tests=result.testsRun,
        total_passed=total_passed,
        total_failed=result.failuresNum,
        total_errors=result.errorsNum,
        total_skipped=result.skippedNum,
    )

    _restore_hardware_input_manager()
    return result


def run_unit_tests(verbosity: int = 2) -> Any:
    """Run only unit tests (desktop-only).

    Unit tests are designed to run on desktop Python with full mocking.
    They should not be run on CircuitPython devices.

    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object
    """
    TEST_LOG.testing("\n" + "=" * 70)
    TEST_LOG.testing("UNIT TESTS")
    TEST_LOG.testing("=" * 70)
    TEST_LOG.testing("")

    if IS_CIRCUITPYTHON:
        TEST_LOG.testing("Unit tests are desktop-only. Run with: python tests/run_tests.py")
        TEST_LOG.testing("On device, use: tests.run_integration() or tests.run_functional()")
        TEST_LOG.testing("=" * 70)
        return unittest.TestResult()

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
    # Handle both standard unittest (failures/errors lists) and custom (failuresNum/errorsNum counts)
    if hasattr(result, "failuresNum"):
        # Custom CircuitPython unittest
        exit_code = 1 if (result.failuresNum > 0 or result.errorsNum > 0) else 0
    else:
        # Standard unittest
        exit_code = 1 if (len(result.failures) > 0 or len(result.errors) > 0) else 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
