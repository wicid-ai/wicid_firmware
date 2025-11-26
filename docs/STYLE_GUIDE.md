# WICID Firmware Style Guide

## 1. Philosophy

This guide defines the coding conventions for the WICID firmware project. Our goal is to produce code that is clean, consistent, and easy to maintain.

This document is not exhaustive. It builds on established Python standards by providing project-specific rules. For anything not covered here, we defer to the broader community standards.

**The primary rule is consistency.** New code should blend in with the existing codebase.

## 2. Complexity and Code Simplicity

**Always choose the simplest, most easily understood, maintained, consistent, architecturally sound, and Pythonic approach available.**

Code complexity is the enemy of maintainability, especially in embedded systems where debugging is challenging. Every design decision should prioritize simplicity and clarity.

### 2.1 Core Principles

- **Prefer Simple Solutions**: If there are multiple ways to solve a problem, choose the one that is easiest to understand and maintain. Clever code is often fragile code.

- **Avoid Over-Engineering**: Don't add abstractions, patterns, or features that aren't needed today. YAGNI (You Aren't Gonna Need It) applies strongly in this codebase.

- **Consistency Over Novelty**: Use existing patterns and approaches from the codebase rather than introducing new ones, even if the new approach might be "better" in isolation.

- **Architectural Alignment**: All code must align with the patterns defined in `docs/ARCHITECTURE.md`. Don't introduce new architectural patterns without updating the architecture document first.

- **Pythonic Code**: Follow established Python idioms and conventions. If you're writing code that looks like it came from another language, you're probably doing it wrong.

### 2.2 Practical Guidelines

- **Functions Should Do One Thing**: If a function is hard to name or requires "and" in its name, it's probably doing too much.

- **Shallow Nesting**: Deeply nested code (more than 2-3 levels) is hard to follow. Use early returns, guard clauses, and helper functions to flatten logic.

  ```python
  # Good - Early return pattern
  def process_data(data: Optional[Dict[str, Any]]) -> bool:
      if data is None:
          return False

      if not validate_data(data):
          return False

      return perform_processing(data)

  # Bad - Nested conditions
  def process_data(data: Optional[Dict[str, Any]]) -> bool:
      if data is not None:
          if validate_data(data):
              return perform_processing(data)
      return False
  ```

- **Avoid Clever Tricks**: Code golf and one-liners that sacrifice readability are not acceptable. If it takes more than a few seconds to understand what a line does, break it up.

- **Use Standard Library**: Prefer standard library solutions over custom implementations. Don't reinvent the wheel.

- **Limit Abstraction Layers**: Each layer of abstraction adds cognitive load. Only introduce abstractions when they eliminate significant duplication or complexity.

### 2.3 Anti-Patterns to Avoid

- **Premature Optimization**: Don't optimize for performance until you have evidence it's needed. Readable code first, fast code second.

- **Unnecessary Classes**: Not everything needs to be a class. Simple functions are often clearer than single-method classes.

- **Magic Numbers and Strings**: Use named constants to make code self-documenting.

- **Implicit Behavior**: Avoid side effects and implicit state changes. Functions should be as pure and explicit as possible.

## 3. Foundational Standards

- **CircuitPython Compatibility**: All Python code **MUST** be compatible with [CircuitPython](https://circuitpython.org/), which is a subset of CPython designed for microcontrollers.
  - CircuitPython does not support all CPython features (e.g., threading, some standard library modules).
  - Only use libraries available in CircuitPython or from the [Adafruit CircuitPython Bundle](https://docs.circuitpython.org/projects/bundle/en/latest/index.html).
  - Test on actual hardware when possible, as behavior may differ from CPython.
  - Our development tooling (mypy, ruff) runs on CPython for static analysis, but the production code runs on CircuitPython.

  **Blocking I/O Limitation**: CircuitPython's WiFi stack is fundamentally blocking at the hardware/firmware level. Non-blocking socket operations (`setblocking(False)`) do not work as expected and will fail with timeout errors. The correct pattern for async network operations is:

  ```python
  from scheduler import Scheduler

  async def fetch_data(session):
      # session.get() blocks, but we yield control immediately after
      response = session.get(url)
      await Scheduler.yield_control()

      data = response.json()
      response.close()
      return data
  ```

  This provides cooperative multitasking by allowing the scheduler to run other tasks (LED updates, button checks) between network calls. Do not attempt to implement custom async socket clients - use `adafruit_requests.Session` with `yield_control()`.

- **PEP 8**: All Python code **MUST** adhere to [PEP 8](https://peps.python.org/pep-0008/). Our automated linter (`ruff`) enforces this standard.

- **PEP 257**: Docstrings **MUST** adhere to PEP 257.

## 3. Naming Conventions

We use naming to communicate the role of a component, consistent with `docs/ARCHITECTURE.md`.

- **Components**:
  - `*Manager`: For high-level orchestrators (e.g., `ModeManager`).
  - `*Controller`: For low-level hardware abstractions (e.g., `PixelController`).
  - `*Service`: For components interacting with external services (e.g., `WeatherService`).

- **Variables and Functions**:
  - `snake_case` for all variables, functions, and methods.
  - `_leading_underscore`: For internal implementation details that are not part of the public API of a module or class. Our linters should help enforce this boundary.

- **Constants**:
  - `UPPER_SNAKE_CASE` for module-level constants (e.g., `REBOOT_INTERVAL = 24`).

## 4. Type Hinting

Static typing is critical for maintaining a large embedded project. `Mypy` is used to enforce this.

- **Centralized Types**: All typing imports (like `List`, `Dict`, `Optional`, `Any`) **MUST** come from `app_typing` (e.g., `from core.app_typing import List`).
  - **Do NOT** import from the standard `typing` module, as this will crash on the device.
  - `app_typing` provides a shim that works for both static analysis (CPython) and runtime (CircuitPython).

- **Strict Typing**: All new functions and methods **MUST** include full type hints for all arguments and return values.

  ```python
  # Good
  from core.app_typing import Dict, Any, Optional

  def get_weather(zip_code: str) -> Optional[Dict[str, Any]]:
      ...
  ```

- **Incomplete Definitions**: Untyped functions are not allowed. If you are writing a function, you are responsible for typing it.

- **CircuitPython Libraries**: Many CircuitPython libraries lack type stubs (`.pyi` files). `Mypy` is configured with `ignore_missing_imports = true` to prevent errors from these libraries. You do not need to add `# type: ignore` for imports like `import board` or `import neopixel`.

## 5. Docstrings and Comments

- **Docstring Format**: Use Google-style docstrings for all public modules, classes, and functions.

  ```python
  def my_function(arg1: str) -> bool:
      """Does something interesting.

      Args:
          arg1: A description of the first argument.

      Returns:
          True on success, False on failure.
      """
      # ...
  ```

- **Comment Quality**: Follow the rules in `CODE_REVIEW_GUIDELINES.md`. Comments must explain the "why," not the "what."

## 6. Imports

Our linter (`ruff`) automatically formats imports according to PEP 8 and `isort` standards.

- **Structure**: Imports should be grouped in the following order:
  1. Standard library imports (e.g., `sys`, `asyncio`).
  2. Third-party library imports (e.g., `adafruit_requests`, `neopixel`).
  3. First-party (local application) imports (e.g., `from config_manager import ConfigManager`).

- **Test Imports**: In test files, the `sys.path` modification **MUST** come before any local `src` imports.

  ```python
  import sys
  sys.path.insert(0, '/src')

  from unittest import TestCase
  from scheduler import Scheduler # Local import
  ```
