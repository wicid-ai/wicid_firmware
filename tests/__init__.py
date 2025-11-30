"""
WICID Firmware Test Suite

Test organization:
- tests/unit/          - Unit tests (isolated component testing)
- tests/integration/   - Integration tests (multi-component interactions)
- tests/functional/    - Functional/E2E tests (complete system behaviors)

Usage from REPL:
    >>> import tests
    >>> tests.run_all()
    >>> tests.run_unit()
    >>> tests.run_integration()
"""

import os
import sys

# Add src to path for imports
# On CircuitPython, use /src (absolute path on device)
# On desktop, use relative path from project root
IS_CIRCUITPYTHON = hasattr(sys, "implementation") and sys.implementation.name == "circuitpython"

if IS_CIRCUITPYTHON:
    sys.path.insert(0, "/src")
else:
    # Desktop: add src directory relative to project root
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _src_dir = os.path.join(_project_root, "src")
    if _src_dir not in sys.path:
        sys.path.insert(0, _src_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)


def run_all() -> None:
    """Run all tests in the test suite.

    Usage from REPL:
        >>> import tests
        >>> tests.run_all()
    """
    from unittest import main

    print("\n" + "=" * 60)
    print("WICID FIRMWARE - ALL TESTS")
    print("=" * 60)
    main(module="tests", exit=False, verbosity=2)


def run_unit() -> None:
    """Run only unit tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_unit()
    """
    from unittest import main

    print("\n" + "=" * 60)
    print("WICID FIRMWARE - UNIT TESTS")
    print("=" * 60)
    main(module="tests.unit", exit=False, verbosity=2)


def run_integration() -> None:
    """Run only integration tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_integration()
    """
    from unittest import main

    print("\n" + "=" * 60)
    print("WICID FIRMWARE - INTEGRATION TESTS")
    print("=" * 60)
    main(module="tests.integration", exit=False, verbosity=2)


def run_functional() -> None:
    """Run only functional tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_functional()
    """
    from unittest import main

    print("\n" + "=" * 60)
    print("WICID FIRMWARE - FUNCTIONAL TESTS")
    print("=" * 60)
    main(module="tests.functional", exit=False, verbosity=2)
