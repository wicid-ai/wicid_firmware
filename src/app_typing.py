"""
Centralized type definitions for WICID firmware.

This module handles compatibility between CPython (static analysis) and CircuitPython (runtime).
It allows using standard typing syntax (List[int], Dict[str, Any]) on the device without
crashing or requiring the heavy 'typing' module.

Usage:
    from app_typing import List, Dict, Optional, Any

    def my_func(items: List[str]) -> Optional[Dict[str, Any]]:
        ...
"""

# 1. Try to import standard typing symbols (for static analysis/CPython)
try:
    from collections.abc import Callable, Generator

    # noqa: UP035 - We explicitly need these deprecated types for the shim interface to match.
    # The suppression must be at the start of the block.
    from typing import (  # noqa: UP035
        TYPE_CHECKING,
        Any,
        Dict,
        List,
        Optional,
        Set,
        Tuple,
        Union,
        cast,
    )
except ImportError:
    # Runtime fallback for CircuitPython if typing is missing.
    # This allows code to run without the 'typing' module.
    # CircuitPython doesn't support metaclass= syntax or __metaclass__ assignment,
    # and typically doesn't evaluate type annotations at runtime anyway.
    # We use plain classes without subscripting support since type hints
    # like List[int] are not evaluated at runtime in CircuitPython.

    # Define simple dummy classes
    # These are fallbacks when typing import fails - mypy sees both branches
    # Note: Subscripting like List[int] won't work at runtime, but type annotations
    # are not evaluated in CircuitPython, so this is fine.
    class List:  # type: ignore[no-redef]  # noqa: UP006
        pass

    class Tuple:  # type: ignore[no-redef]  # noqa: UP006
        pass

    class Optional:  # type: ignore[no-redef]
        pass

    class Dict:  # type: ignore[no-redef]  # noqa: UP006
        pass

    class Set:  # type: ignore[no-redef]  # noqa: UP006
        pass

    class Union:  # type: ignore[no-redef]
        pass

    class Callable:  # type: ignore[no-redef]  # noqa: UP035
        pass

    class Generator:  # type: ignore[no-redef]  # noqa: UP035
        pass

    # Simple alias for Any
    Any: object = object()  # type: ignore[no-redef]

    # TYPE_CHECKING is always False at runtime
    TYPE_CHECKING: bool = False  # type: ignore[no-redef]

    # Cast does nothing at runtime
    def cast(typ: type, val: object) -> object:  # type: ignore[no-redef]
        return val


# 2. Try to import CircuitPython-specific types (for static analysis)
try:
    from circuitpython_typing import (  # type: ignore[import-not-found]  # CircuitPython-only module
        ReadableBuffer,
        WriteableBuffer,
    )
except ImportError:
    # Fallback if library is not installed on device
    ReadableBuffer: type = Any  # type: ignore[no-redef]
    WriteableBuffer: type = Any  # type: ignore[no-redef]
