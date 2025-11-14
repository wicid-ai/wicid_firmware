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

import sys

# Add src to path for imports
sys.path.insert(0, '/src')


def run_all():
    """Run all tests in the test suite.

    Usage from REPL:
        >>> import tests
        >>> tests.run_all()
    """
    from unittest import main
    print("\n" + "=" * 60)
    print("WICID FIRMWARE - ALL TESTS")
    print("=" * 60)
    main(module='tests', exit=False, verbosity=2)


def run_unit():
    """Run only unit tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_unit()
    """
    from unittest import main
    print("\n" + "=" * 60)
    print("WICID FIRMWARE - UNIT TESTS")
    print("=" * 60)
    main(module='tests.unit', exit=False, verbosity=2)


def run_integration():
    """Run only integration tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_integration()
    """
    from unittest import main
    print("\n" + "=" * 60)
    print("WICID FIRMWARE - INTEGRATION TESTS")
    print("=" * 60)
    main(module='tests.integration', exit=False, verbosity=2)


def run_functional():
    """Run only functional tests.

    Usage from REPL:
        >>> import tests
        >>> tests.run_functional()
    """
    from unittest import main
    print("\n" + "=" * 60)
    print("WICID FIRMWARE - FUNCTIONAL TESTS")
    print("=" * 60)
    main(module='tests.functional', exit=False, verbosity=2)
