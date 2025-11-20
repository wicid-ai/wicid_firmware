# WICID Firmware Test Suite

On-device testing framework for CircuitPython firmware built on a lightweight unittest shim (`tests/unittest.py`). The shim mirrors CPython's familiar API closely enough for most tests while remaining compatible with constrained hardware.

## Overview

This test suite runs directly on CircuitPython hardware via the REPL. It uses the custom shim plus a higher-level orchestrator (`tests/run_tests.py`) to provide discovery, grouping, and logging functionality that mirrors CPython's unittest experience.

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
├── unittest.py              # Lightweight unittest shim (inspired by CircuitPython_Unittest)
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

## Testing Philosophy: Layered Testing with Strategic Hardware Usage

### The Hardware Testing Hierarchy

WICID firmware follows a **layered testing approach** that minimizes hardware dependencies while maintaining comprehensive test coverage. This philosophy balances real hardware validation with scalable, deterministic testing.

### Three-Layer Testing Model

```
┌─────────────────────────────────────────────────────────────┐
│  HIGH-LEVEL COMPONENTS (Modes, Managers, Orchestrators)    │
│  ─────────────────────────────────────────────────────────  │
│  Hardware: ALWAYS use mocks                                  │
│  Why: Complex behavior, composition of lower layers          │
│  Examples: WeatherMode, ModeManager, InputManager           │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ Builds on
                             │
┌─────────────────────────────────────────────────────────────┐
│  MID-LEVEL COMPONENTS (Services, Coordinators)              │
│  ─────────────────────────────────────────────────────────  │
│  Hardware: Prefer mocks, use real HW only for integration   │
│  Why: Business logic, service orchestration                 │
│  Examples: WeatherService, UpdateManager                    │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ Builds on
                             │
┌─────────────────────────────────────────────────────────────┐
│  LOW-LEVEL COMPONENTS (Controllers, Hardware Abstraction)   │
│  ─────────────────────────────────────────────────────────  │
│  Hardware: Use real HW ONLY when safe and contention-free   │
│           Otherwise use mocks (preferred for automation)     │
│  Why: Direct hardware interaction, minimal dependencies     │
│  Examples: ButtonController, PixelController                │
└─────────────────────────────────────────────────────────────┘
```

### Rules for Hardware Usage in Tests

#### Rule 1: Low-Level Controller Tests
**Controllers** (ButtonController, PixelController, etc.) MAY use real hardware when:
- ✅ Safe to use without hardware conflicts
- ✅ Can be reliably cleaned up (deinit)
- ✅ Deterministic behavior (no race conditions)
- ✅ Only one component owns the hardware resource

**Otherwise, controllers MUST use mocks** when:
- ❌ Hardware resource can only be owned once (e.g., board.BUTTON)
- ❌ Test automation requires running multiple tests in parallel
- ❌ Behavior is non-deterministic (timing-sensitive)
- ❌ Hardware may not be present in all test environments

**Example: ButtonController Testing**
```python
# LOW-LEVEL: ButtonController tests use MOCK hardware
from test_helpers import create_mock_button_pin

class TestButtonController(TestCase):
    def setUp(self):
        self.logger = get_logger('test')
        self.mock_pin = create_mock_button_pin()  # Mock, not board.BUTTON

    def test_controller_init(self):
        # Test ButtonController in isolation without hardware conflicts
        controller = ButtonController(self.logger, button_pin=self.mock_pin)
        self.assertIsNotNone(controller)
        controller.deinit()
```

#### Rule 2: High-Level Component Tests
**All higher-level components** (managers, modes, services) that rely on hardware components **MUST ONLY use mocks**.

**Why?**
- Managers orchestrate multiple lower-level components
- Testing managers with real hardware creates resource conflicts
- Mock-based testing is faster, more reliable, and deterministic
- Enables parallel test execution

**Example: InputManager Testing**
```python
# HIGH-LEVEL: InputManager tests use MOCK hardware (ALWAYS)
from test_helpers import create_mock_button_pin

class TestInputManager(TestCase):
    @classmethod
    def setUpClass(cls):
        # InputManager is high-level - ALWAYS use mock
        cls.test_button_pin = create_mock_button_pin(pin_number=99)

    def test_input_manager_callbacks(self):
        # Test event-driven behavior with mock hardware
        mgr = InputManager.instance(button_pin=self.test_button_pin)

        def callback(event):
            self.callback_fired = True

        mgr.register_callback(ButtonEvent.PRESS, callback)

        # Simulate button press with mock
        self.test_button_pin.simulate_press()
        # ... assertions ...
```

#### Rule 3: Mock Infrastructure is Shared
All mock objects that could be reused across tests MUST be provided as shared helpers in `test_helpers.py`.

**Available Mock Helpers:**
- `create_mock_button_pin()` - Mock GPIO pin for button testing
- `create_mock_pixel()` - Mock NeoPixel/LED for display testing

**Example: Using Shared Mocks**
```python
from test_helpers import create_mock_button_pin, create_mock_pixel

class TestMode(TestCase):
    def setUp(self):
        # Use shared mock infrastructure
        self.mock_button = create_mock_button_pin()
        self.mock_pixel = create_mock_pixel()

    def test_mode_behavior(self):
        # Mode uses mock button and pixel - no hardware conflicts
        mode = WeatherMode(button=self.mock_button, pixel=self.mock_pixel)
        # ... test mode behavior ...
```

### Benefits of Layered Testing

1. **No Resource Conflicts**: Mock hardware eliminates "pin in use" errors
2. **Deterministic Behavior**: Tests produce consistent results
3. **Parallel Execution**: Multiple tests can run simultaneously
4. **Fast Execution**: No hardware delays or initialization overhead
5. **Comprehensive Coverage**: Test edge cases impossible with real hardware
6. **Portable Tests**: Tests run on any platform, not just hardware

### When to Use Real Hardware

Real hardware should be used **sparingly** and **strategically**:

✅ **Use Real Hardware For:**
- Low-level controller validation (when safe and contention-free)
- Integration tests verifying hardware compatibility
- Final end-to-end system validation
- Manual testing sessions

❌ **Don't Use Real Hardware For:**
- Unit tests of high-level components
- Automated CI/CD pipelines
- Tests that can be mocked effectively
- Tests requiring specific hardware states

### Example: Complete Test Suite Structure

```python
# tests/unit/test_button_controller.py (LOW-LEVEL)
# ✅ Uses mocks to avoid conflicts
from test_helpers import create_mock_button_pin

class TestButtonController(TestCase):
    """Low-level controller tests with mock hardware."""
    def setUp(self):
        self.mock_pin = create_mock_button_pin()

# tests/unit/test_input_manager.py (HIGH-LEVEL)
# ✅ Uses mocks (ALWAYS for managers)
from test_helpers import create_mock_button_pin

class TestInputManager(TestCase):
    """High-level manager tests with mock hardware."""
    @classmethod
    def setUpClass(cls):
        cls.mock_pin = create_mock_button_pin()

# tests/integration/test_mode_switching.py (INTEGRATION)
# ✅ Uses mocks for automated testing
from test_helpers import create_mock_button_pin, create_mock_pixel

class TestModeSwitching(TestCase):
    """Integration tests with mock hardware."""
    def setUp(self):
        self.mock_button = create_mock_button_pin()
        self.mock_pixel = create_mock_pixel()
```

## Best Practices

1. **Keep tests independent:** Don't rely on execution order
2. **Clean up resources:** Cancel tasks, close files, release hardware resources in `tearDown()`
3. **Test one thing:** Each test should verify a single behavior
4. **Use descriptive names:** `test_component_performs_expected_behavior_under_specific_conditions()`
5. **Handle timing:** Allow tolerance for timing-sensitive tests (±50ms for async operations)
6. **Prefer mocks:** Use mock hardware unless there's a specific need for real hardware
7. **Follow the hierarchy:** Low-level MAY use real HW (when safe), high-level MUST use mocks

## Test Helpers and Mocking

### Using Mock Hardware

The `test_helpers.py` module provides reusable mock objects following our **layered testing philosophy**. All mocks are designed to be shared across tests and mimic real hardware APIs closely.

**Mock Pin for Button Testing:**

```python
from test_helpers import create_mock_button_pin

# Create mock pin
mock_pin = create_mock_button_pin(pin_number=42)

# Simulate button press/release
mock_pin.simulate_press()   # Set to LOW (active-low button)
mock_pin.simulate_release() # Set to HIGH

# Or set value directly
mock_pin.value = False  # Pressed
mock_pin.value = True   # Released
```

**Testing ButtonController with Mock Pin:**

```python
from test_helpers import create_mock_button_pin
from button_controller import ButtonController
from logging_helper import get_logger

class TestButtonController(TestCase):
    def setUp(self):
        self.logger = get_logger('test')
        self.mock_pin = create_mock_button_pin()

    def test_controller_init(self):
        # No hardware conflict - uses mock pin instead of board.BUTTON
        controller = ButtonController(self.logger, button_pin=self.mock_pin)
        self.assertIsNotNone(controller)
        controller.deinit()
```

**Testing InputManager with Mock Pin:**

```python
from test_helpers import create_mock_button_pin
from input_manager import InputManager

class TestInputManagerMocked(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_pin = create_mock_button_pin()

    def test_input_manager_with_mock(self):
        # Test InputManager without board.BUTTON ownership issues
        mgr = InputManager.instance(button_pin=self.mock_pin)
        self.assertIsNotNone(mgr)
```

**Mock Pixel for LED/Display Testing:**

```python
from test_helpers import create_mock_pixel

# Create mock pixel
mock_pixel = create_mock_pixel()

# Set color
mock_pixel.fill((255, 0, 0))  # Red
mock_pixel[0] = (0, 255, 0)   # Green (by index)

# Check current color
assert mock_pixel.color == (0, 255, 0)

# Brightness control
mock_pixel.brightness = 0.5

# History tracking for assertions
history = mock_pixel.get_history()
assert ('fill', (255, 0, 0)) in history
assert ('brightness', 0.5) in history
```

**Testing PixelController with Mock Pixel:**

```python
from test_helpers import create_mock_pixel
from pixel_controller import PixelController

class TestPixelController(TestCase):
    def setUp(self):
        self.mock_pixel = create_mock_pixel()

    def test_set_color(self):
        # Test PixelController without real NeoPixel hardware
        controller = PixelController(pixel=self.mock_pixel)
        controller.set_color((255, 0, 0))

        # Verify color was set via mock
        self.assertEqual(self.mock_pixel.color, (255, 0, 0))

        # Verify operation history
        history = self.mock_pixel.get_history()
        self.assertIn(('fill', (255, 0, 0)), history)
```

### Benefits of Using Test Helpers

1. **No Resource Conflicts:** Mock hardware eliminates "pin in use" and hardware ownership errors
2. **Parallel Testing:** Multiple components can use different mock instances simultaneously
3. **Deterministic Behavior:** Control exact hardware state for reproducible tests
4. **Layer Separation:** Test low-level components (ButtonController) and high-level components (InputManager) independently
5. **Reusable Infrastructure:** Shared mocks reduce code duplication
6. **History Tracking:** MockPixel tracks operations for detailed test assertions
7. **Full API Compatibility:** Mocks implement the same interface as real hardware

### Testing Managers with Singleton Pattern

All managers follow the `ManagerBase` lifecycle pattern. When testing managers:

**DO:**
- Use `Manager.instance(deps...)` to get singleton instances
- Inject test dependencies via `instance()` parameters (e.g., `InputManager.instance(button_pin=test_pin)`)
- Let managers handle their own cleanup via `shutdown()` - don't manipulate `_instance` directly
- Shut down existing instances before creating test pins if needed (via `instance.shutdown()`)

**DON'T:**
- Don't manipulate `_instance` directly (except in test setup to shut down existing instances)
- Don't call `deinit()` or `reset_for_test()` - use the standard lifecycle API
- Don't manually create/deinit hardware pins - let managers handle it

**Example:**
```python
class TestInputManager(TestCase):
    @classmethod
    def setUpClass(cls):
        # Shut down any existing instance to free hardware resources
        if InputManager._instance is not None and getattr(InputManager._instance, "_initialized", False):
            try:
                InputManager._instance.shutdown()
            except Exception:
                pass
        
        # Create test pin
        cls.test_button_pin = DigitalInOut(board.BUTTON)
        cls.test_button_pin.switch_to_input(pull=digitalio.Pull.UP)
    
    @classmethod
    def tearDownClass(cls):
        # Clean up test pin
        if hasattr(cls, 'test_button_pin') and cls.test_button_pin is not None:
            try:
                cls.test_button_pin.deinit()
            except Exception:
                pass
    
    def setUp(self):
        # Get manager instance with test dependencies
        # Manager will automatically reinitialize if needed
        self.mgr = InputManager.instance(button_pin=self.test_button_pin)
```

**Key Points:**
- `InputManager.instance(button_pin=test_pin)` automatically handles reinitialization if a different pin is passed
- Managers own their resources (pins, tasks, sessions) and clean them up in `shutdown()`
- Tests just need to inject dependencies - managers handle the rest

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

- **Shim reference:** https://github.com/mytechnotalent/CircuitPython_Unittest
- **Python unittest docs:** https://docs.python.org/3/library/unittest.html
- **CircuitPython docs:** https://docs.circuitpython.org/
