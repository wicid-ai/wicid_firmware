# WICID Firmware Style Guide

## 1. Philosophy

This guide defines the coding conventions for the WICID firmware project. Our goal is to produce code that is clean, consistent, and easy to maintain.

This document is not exhaustive. It builds on established Python standards by providing project-specific rules. For anything not covered here, we defer to the broader community standards.

**The primary rule is consistency.** New code should blend in with the existing codebase.

## 2. Foundational Standards

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

- **Strict Typing**: All new functions and methods **MUST** include full type hints for all arguments and return values.

  ```python
  # Good
  def get_weather(zip_code: str) -> dict[str, any] | None:
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
