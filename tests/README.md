# WICID Firmware Test Suite

On-device testing framework for CircuitPython firmware using the standard unittest API.

## Overview

This test suite runs directly on CircuitPython hardware via the REPL. It uses **CircuitPython_Unittest**, a lightweight implementation of Python's standard `unittest` module designed for microcontrollers.

Tests are organized following Python conventions:
- `tests/unit/` - Unit tests (isolated component testing)
- `tests/integration/` - Integration tests (multi-component interactions)
- `tests/functional/` - Functional/E2E tests (complete system behaviors)

## Quick Start

### Run All Tests

Connect to your device's REPL and run:

```python
>>> import tests
>>> tests.run_all()
```

### Run Specific Test Suites

```python
>>> import tests
>>> tests.run_unit()          # Unit tests only
>>> tests.run_integration()   # Integration tests only
>>> tests.run_functional()    # Functional tests only
```

### Run From Command Line (Desktop Python)

```bash
python tests/run_tests.py
```

## How the Test Framework Works

### Test Discovery

The framework automatically discovers and runs all test files in the test directories:

1. **Auto-discovery**: The test runner scans each test directory (`unit/`, `integration/`, `functional/`) for files matching the pattern `test_*.py`
2. **Module loading**: Each discovered file is imported as a module
3. **Test collection**: The framework finds all classes that inherit from `unittest.TestCase`
4. **Suite building**: All discovered test classes are added to a test suite
5. **Execution**: The test suite runs all test methods (methods starting with `test_`)

This means you can add new tests simply by creating a `test_*.py` file in the appropriate directory—no registration or configuration needed.

### Test Runner Architecture

The test runner (`run_tests.py`) provides:

- **Unified interface**: Single entry point for all test execution
- **Selective execution**: Run all tests or filter by test type (unit/integration/functional)
- **Progress feedback**: Optional tick callback for visual feedback (e.g., LED animations) between test classes
- **Logging integration**: Uses the firmware's logging system when available, with fallback for standalone execution
- **Cross-platform**: Works both on-device (CircuitPython REPL) and desktop (standard Python)

## Writing Tests

### Basic Test Structure

Create a new test module in the appropriate directory:

```python
# tests/unit/test_my_feature.py
import sys
sys.path.insert(0, '/src')

from unittest import TestCase
from my_module import MyClass

class TestMyFeature(TestCase):
    """Tests for MyFeature functionality."""

    def setUp(self):
        """Called before each test method."""
        self.obj = MyClass()

    def tearDown(self):
        """Called after each test method."""
        self.obj = None

    def test_basic_functionality(self):
        """Test basic feature works."""
        result = self.obj.do_something()
        self.assertEqual(result, 42)

    def test_error_handling(self):
        """Test error handling."""
        with self.assertRaises(ValueError):
            self.obj.invalid_operation()
```

### Class-Level Setup (Suite-Wide)

For expensive setup that should run once per test class:

```python
class TestExpensiveSetup(TestCase):
    """Tests requiring expensive setup."""

    @classmethod
    def setUpClass(cls):
        """Called once before any tests in this class."""
        cls.expensive_resource = create_expensive_resource()

    @classmethod
    def tearDownClass(cls):
        """Called once after all tests in this class."""
        cls.expensive_resource.cleanup()

    def test_something(self):
        """Test using the class-level resource."""
        self.assertIsNotNone(self.expensive_resource)
```

### Available Assertions

Standard unittest assertions (same API as CPython):

- `assertEqual(a, b, msg)` - Verify a == b
- `assertNotEqual(a, b, msg)` - Verify a != b
- `assertTrue(x, msg)` - Verify x is True
- `assertFalse(x, msg)` - Verify x is False
- `assertIs(a, b, msg)` - Verify a is b (identity)
- `assertIsNot(a, b, msg)` - Verify a is not b
- `assertIsNone(x, msg)` - Verify x is None
- `assertIsNotNone(x, msg)` - Verify x is not None
- `assertIn(a, b, msg)` - Verify a in b
- `assertNotIn(a, b, msg)` - Verify a not in b
- `assertIsInstance(obj, cls, msg)` - Verify isinstance(obj, cls)
- `assertAlmostEqual(a, b, places, msg, delta)` - Verify a ≈ b (floating point)
- `assertNotAlmostEqual(a, b, places, msg, delta)` - Verify a ≉ b
- `assertRaises(exc, func, *args, **kwargs)` - Verify exception raised

### Testing Exceptions

Two ways to test exceptions:

```python
# Method 1: Context manager (recommended)
def test_exception_context_manager(self):
    with self.assertRaises(ValueError):
        do_something_invalid()

# Method 2: Direct call
def test_exception_direct(self):
    self.assertRaises(ValueError, do_something_invalid, arg1, arg2)
```

### Testing Async Code

Use `asyncio.run()` to test async functions:

```python
import asyncio

class TestAsyncCode(TestCase):
    """Tests for async functionality."""

    def test_async_function(self):
        """Test an async function."""
        async def my_async_func():
            await asyncio.sleep(0.1)
            return 42

        result = asyncio.run(my_async_func())
        self.assertEqual(result, 42)
```

### Skipping Tests

Use decorators to skip tests conditionally:

```python
from unittest import skip, skipIf, skipUnless

class TestConditional(TestCase):
    """Tests with conditional skipping."""

    @skip("Not implemented yet")
    def test_future_feature(self):
        """This test is skipped."""
        pass

    @skipIf(sys.platform == 'circuitpython', "Not supported on CircuitPython")
    def test_desktop_only(self):
        """Skipped on CircuitPython."""
        pass

    @skipUnless(hasattr(board, 'NEOPIXEL'), "Requires NeoPixel")
    def test_neopixel(self):
        """Only runs if NeoPixel available."""
        pass
```

## File Structure

```
tests/
├── __init__.py              # Package initialization with convenience functions
├── unittest.py              # CircuitPython_Unittest framework
├── run_tests.py             # Test runner
├── README.md                # This file
├── unit/                    # Unit tests
│   ├── __init__.py
│   └── test_*.py            # Unit test modules
├── integration/             # Integration tests
│   └── __init__.py
└── functional/              # Functional/E2E tests
    └── __init__.py
```

## Adding New Tests

1. Create `test_your_feature.py` in the appropriate directory:
   - `tests/unit/` for isolated component tests
   - `tests/integration/` for multi-component tests
   - `tests/functional/` for end-to-end tests

2. Import `TestCase` from `unittest`:
   ```python
   from unittest import TestCase
   ```

3. Create test classes inheriting from `TestCase`:
   ```python
   class TestYourFeature(TestCase):
       def test_something(self):
           self.assertEqual(1 + 1, 2)
   ```

4. Run tests via REPL or command line

## Test Naming Conventions

Follow Python unittest conventions:

- **Files:** `test_*.py` (e.g., `test_display.py`, `test_sensor.py`)
- **Classes:** `Test*` (e.g., `TestDisplayController`, `TestSensorManager`)
- **Methods:** `test_*` (e.g., `test_display_initialization`, `test_sensor_reading`)

Descriptive method names:
- `test_<component>_<behavior>_<expected_result>`
- Example: `test_display_updates_when_data_changes()`
- Example: `test_sensor_raises_error_on_invalid_config()`

## CircuitPython Compatibility

The `unittest.py` module is specifically designed for CircuitPython:

- **Minimal imports:** Only `sys` and `traceback`
- **No external dependencies:** Self-contained
- **Lightweight:** Optimized for memory-constrained devices
- **Standard API:** Matches CPython's unittest where possible

### Differences from CPython unittest

- No test discovery from command line (use `run_tests.py`)
- No TestLoader.loadTestsFromName()
- No subtests or test parameterization
- No mock/patch support (manual mocking required)

## Best Practices

1. **Keep tests independent:** Don't rely on execution order
2. **Clean up resources:** Cancel tasks, close files, release hardware resources in `tearDown()`
3. **Test one thing:** Each test should verify a single behavior
4. **Use descriptive names:** `test_component_performs_expected_behavior_under_specific_conditions()`
5. **Handle timing:** Allow tolerance for timing-sensitive tests (±50ms for async operations)
6. **Isolate hardware:** Mock hardware dependencies when possible to enable testing without physical devices

## Example Test Session

```python
>>> import tests
>>> tests.run_all()

======================================================================
WICID FIRMWARE TEST SUITE
======================================================================

test_basic_functionality (TestMyComponent) ... ok
test_edge_cases (TestMyComponent) ... ok
test_error_handling (TestMyComponent) ... ok
...
Ran 15 tests

======================================================================
TEST SUMMARY
======================================================================
Tests run: 15
Failures: 0
Errors: 0
Skipped: 0

ALL TESTS PASSED
======================================================================
```

## Debugging Failed Tests

When tests fail, the framework provides detailed error information to help you diagnose issues:

1. **Check error message:** Assertion messages show expected vs actual values
2. **Add print statements:** Use `print()` for debugging (visible in REPL output)
3. **Run specific test suites:** Use `tests.run_unit()`, `tests.run_integration()`, or `tests.run_functional()` to narrow down which category is failing
4. **Examine tracebacks:** Full Python tracebacks show exactly where failures occurred
5. **Check hardware state:** Verify device state (memory, storage, hardware connections)
6. **Review logs:** Check CircuitPython boot logs for initialization errors

### Common Test Failures

- **Memory errors:** CircuitPython has limited RAM; tests may fail if too many objects are created
- **Timing issues:** Async operations may need tolerance ranges for timing assertions
- **Hardware dependencies:** Tests requiring specific hardware (sensors, displays) will fail if not present
- **Import errors:** Missing dependencies or incorrect paths will prevent test modules from loading

## Visual Test Feedback

The test runner supports optional visual feedback during test execution:

- **LED animations**: Pass a `tick_callback` to `run_all_tests()` to update LED patterns between test classes
- **Progress indication**: Visual feedback helps indicate test progress on devices without displays
- **Status signaling**: Can be used to signal test completion or failure states

This feature is particularly useful for headless testing on embedded devices.

## Resources

- **CircuitPython_Unittest:** https://github.com/mytechnotalent/CircuitPython_Unittest
- **Python unittest docs:** https://docs.python.org/3/library/unittest.html
- **CircuitPython docs:** https://docs.circuitpython.org/
