# Code Patterns Cookbook

This document provides concrete, copy-pasteable examples of common architectural patterns used in the firmware. Use this as a reference for implementation details ("how") to complement the architectural documentation ("what" and "why").

## Table of Contents

1. [Scheduler Usage](#scheduler-usage)
2. [Manager Singleton Pattern](#manager-singleton-pattern)
3. [Error Handling](#error-handling)
4. [Exception Suppression](#exception-suppression)
5. [Testing with Mocks](#testing-with-mocks)
6. [Cooperative Yielding](#cooperative-yielding)
7. [Type Hinting](#type-hinting)

---

## Scheduler Usage

**Concept:** The system runs on a cooperative scheduler. Tasks must be scheduled rather than run directly if they are long-running or periodic.

### ✅ Do (Correct)

Use `Scheduler.sleep()` for delays within tasks. This allows other tasks to run while waiting.

```python
from core.scheduler import Scheduler

async def my_task():
    # ... do some work ...
    await Scheduler.sleep(0.1)  # Yields control for 0.1s
```

### ❌ Don't (Incorrect)

Do not use `asyncio.sleep()` directly, as it bypasses the scheduler's time management.

```python
import asyncio

async def my_task():
    # ... do some work ...
    await asyncio.sleep(0.1) # Wrong: Use Scheduler.sleep()
```

---

## Manager Singleton Pattern

**Concept:** core system components (Managers) are Singletons. They should be accessed via their `.instance()` method, which handles initialization and dependency injection (useful for testing).

### ✅ Do (Correct)

Access the singleton instance using `.instance()`. You can pass dependencies (like mock pins) here if needed (e.g., in tests).

```python
from managers.input_manager import InputManager

# Normal usage
mgr = InputManager.instance()

# Usage in tests (injecting a mock pin)
mgr = InputManager.instance(button_pin=mock_pin)
```

### ❌ Don't (Incorrect)

Do not instantiate Managers directly or manually manage the `_instance` variable.

```python
from input_manager import InputManager

# Wrong: Direct instantiation bypasses singleton logic
mgr = InputManager()
mgr._instance = mgr # Wrong: Never manually set _instance
```

---

## Error Handling

**Concept:** Distinguish between recoverable errors (Network glitches, API failures) and fatal errors (Hardware failure).

### ✅ Do (Correct)

Raise `TaskNonFatalError` for issues that should be logged but shouldn't crash the system. The scheduler will catch this and keep the task alive (or restart it).

```python
from core.scheduler import TaskNonFatalError

def fetch_data():
    if response.status_code == 404:
        raise TaskNonFatalError("API returned 404 - Resource not found")
```

### ❌ Don't (Incorrect)

Do not just print errors and return, as this hides visibility from the system manager. Do not crash the whole system for minor issues.

```python
def fetch_data():
    if response.status_code == 404:
        print("Error: API returned 404")
        return # Wrong: Scheduler doesn't know an error occurred
```

---

## Exception Suppression

**Concept:** Use `suppress` context manager for clean exception handling when you want to ignore specific exceptions. CircuitPython doesn't include `contextlib`, so we provide our own implementation in `utils.py`.

### ✅ Do (Correct)

Use `suppress` from `utils.utils` to cleanly ignore expected exceptions.

```python
from utils.utils import suppress

# Suppress a single exception type
with suppress(OSError):
    os.remove(file_path)  # Ignore if file doesn't exist

# Suppress multiple exception types
with suppress(OSError, ValueError):
    risky_operation()

# Combine with other context managers (file operations)
with suppress(OSError, ValueError), open(manifest_path) as f:
    data = json.load(f)
    process(data)
```

### ❌ Don't (Incorrect)

Do not use `try-except-pass` blocks or import `contextlib` (not available in CircuitPython).

```python
# Wrong: Verbose and less clear
try:
    os.remove(file_path)
except OSError:
    pass

# Wrong: contextlib not available in CircuitPython
import contextlib
with contextlib.suppress(OSError):
    os.remove(file_path)
```

**Note:** Ruff SIM105 will flag `try-except-pass` patterns. When you see this warning, use `from utils import suppress` instead of `import contextlib`.

---

## Testing with Mocks

**Concept:** Hardware dependencies (Pins, I2C, SPI) should be mocked in high-level logic tests to ensure tests run on non-hardware platforms (like CI runners).

### ✅ Do (Correct)

Use `create_mock_button_pin` or similar helpers to create simulated hardware objects.

```python
from tests.test_helpers import create_mock_button_pin

def test_button_logic():
    mock_pin = create_mock_button_pin()
    # Pass mock to the manager
    mgr = InputManager.instance(button_pin=mock_pin)
```

### ❌ Don't (Incorrect)

Do not import `board` or access physical pins in high-level logic tests.

```python
import board

def test_button_logic():
    pin = board.BUTTON # Wrong: Fails on computers without this specific hardware
```

---

## Cooperative Yielding

**Concept:** The system is single-threaded. Long-running loops (like `while True`) must explicitly yield control to the scheduler to prevent "starving" other tasks.

### ✅ Do (Correct)

Use `await Scheduler.yield_control()` inside tight loops.

```python
from core.scheduler import Scheduler

async def processing_loop():
    while True:
        process_chunk()
        # Allow other tasks to run
        await Scheduler.yield_control()
```

### ❌ Don't (Incorrect)

Do not write blocking infinite loops without yielding.

```python
async def processing_loop():
    while True:
        pass # Wrong: Blocks the entire system, watchdog will trigger reset
```

---

## Type Hinting

**Concept:** CircuitPython lacks the `typing` module to save space. We use a centralized `app_typing.py` shim that provides real types for development/static analysis but lightweight dummy classes for the device runtime.

### ✅ Do (Correct)

Import types from `app_typing` instead of `typing`. This allows standard syntax `List[int]` without runtime crashes or memory overhead.

```python
from core.app_typing import List, Dict, Optional

def process_data(data: List[int]) -> Optional[Dict[str, int]]:
    # ... implementation ...
    pass
```

### ❌ Don't (Incorrect)

Do not import directly from `typing` (crashes on device) or use stringified types everywhere (messy).

```python
# Wrong: Will crash on device (ImportError)
from typing import List

# Wrong: Messy and harder to read
def process_data(data: "List[int]") -> "Optional[Dict[str, int]]":
    pass
```
