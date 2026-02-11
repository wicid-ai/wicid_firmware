# Agents

Context and guidelines for AI agents working on the WICID firmware.

## Overview

WICID (Wireless Internet Connected Info Display) is an embedded firmware project running on CircuitPython with a custom cooperative scheduler. The target hardware is the Adafruit Feather ESP32-S3.

All code must be compatible with CircuitPython (a subset of CPython). Development tooling (mypy, ruff, tests) runs on CPython for static analysis, but production code runs on the microcontroller.

## Documentation Reference

Align all code generation and architectural decisions with these documents:

| Topic | Source | Description |
|-------|--------|-------------|
| **Architecture** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Manager patterns, error handling, system design |
| **Patterns** | [`docs/PATTERNS_COOKBOOK.md`](docs/PATTERNS_COOKBOOK.md) | Golden examples for Scheduler, Singletons, Mocks, error handling. Use these exact patterns. |
| **Style** | [`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md) | Naming conventions, type hinting, import order |
| **Scheduler** | [`docs/SCHEDULER_ARCHITECTURE.md`](docs/SCHEDULER_ARCHITECTURE.md) | Cooperative multitasking rules (`async`, `await`, `Scheduler.yield_control()`) |
| **Code Review** | [`docs/CODE_REVIEW_GUIDELINES.md`](docs/CODE_REVIEW_GUIDELINES.md) | Review checklist and quality standards |
| **Build** | [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md) | Release process, OTA updates, deployment |
| **Testing** | [`tests/README.md`](tests/README.md) | Testing strategy, mocks vs hardware, TDD workflow |
| **Developer Setup** | [`docs/DEVELOPER_SETUP.md`](docs/DEVELOPER_SETUP.md) | Environment setup, filesystem modes, configuration |

## Key Constraints

- **Scheduler isolation**: Only `scheduler.py` may import `asyncio`. All other modules use `Scheduler.sleep()` and `Scheduler.yield_control()`.
- **Type imports**: Import from `core.app_typing`, never from `typing` (crashes on device).
- **No blocking**: Long loops must yield control. Use `await Scheduler.sleep()` instead of `time.sleep()`.
- **Manager singletons**: Access via `Manager.instance()`, never direct instantiation.
- **Error handling**: Recoverable errors use `TaskNonFatalError`; fatal errors use `TaskFatalError`.

## Verification

After any code changes, run:

```bash
pipenv run pre-commit run --all-files
```

This validates formatting, linting, type checking, and unit tests. Do not run integration or functional tests — those require physical hardware.

## Project Status

This project is open source under the MIT License. Pull requests are not actively reviewed. Contributors are welcome to fork and extend the project independently.
