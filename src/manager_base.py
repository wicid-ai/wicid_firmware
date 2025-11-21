"""
ManagerBase - shared lifecycle and context-manager helpers for manager singletons.

This base class provides a consistent pattern for manager singletons:
- Provides a default singleton-style ``instance()`` accessor.
- Defines lifecycle hooks ``_init()`` and ``shutdown()`` for resource management.
- Implements ``__enter__`` / ``__exit__`` so managers can be used as context managers.
- Encapsulates resource cleanup so callers never manipulate internals directly.

Subclasses are expected to:
- Override ``_init(*args, **kwargs)`` to perform real initialization (allocate resources, start tasks, etc.).
- Override ``shutdown()`` to release resources (cancel tasks, deinit hardware, clear references).
- Optionally override ``instance()`` or ``_is_compatible_with()`` for smart reinitialization when dependencies change.
"""

import contextlib

from scheduler import Scheduler


class ManagerBase:
    """
    Base class for manager-style singletons with encapsulated resource lifecycle.

    Provides default singleton behavior with lifecycle hooks for initialization
    and cleanup. Subclasses can override ``instance()`` to support smart reinitialization
    when dependencies change (useful for testing).
    """

    # Subclasses should override this with their own class-level instance slot
    _instance = None

    @classmethod
    def instance(cls, *args, **kwargs):
        """
        Return the singleton instance for this manager.

        Default behavior:
        - Lazily creates a new instance on first call.
        - Calls ``_init(*args, **kwargs)`` once on first creation.
        - Ignores subsequent arguments on later calls.

        Subclasses may override this method to support reconfiguration when
        dependencies change (e.g., different button_pin in tests). In that case,
        they should:
        - Check if existing instance is compatible with new deps via ``_is_compatible_with()``
        - If not compatible, call ``_instance.shutdown()`` then ``_instance._init(...)``
        - Return the reconfigured instance

        Returns:
            ManagerBase: The singleton instance for this manager class
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            if hasattr(obj, "_init"):
                obj._init(*args, **kwargs)
        return cls._instance

    def _is_compatible_with(self, *args, **kwargs):
        """
        Check if this instance is compatible with the given dependencies.

        Default implementation always returns True (instance is always compatible).
        Subclasses can override to detect when reinitialization is needed.

        Args:
            *args: Positional arguments passed to instance()
            **kwargs: Keyword arguments passed to instance()

        Returns:
            bool: True if instance is compatible with deps, False if reinit needed
        """
        return True

    # Instance lifecycle hooks -------------------------------------------------

    def _init(self, *args, **kwargs):
        """
        Initialize this manager instance with resources and dependencies.

        Subclasses must implement this method to:
        - Allocate hardware resources (pins, radios, etc.)
        - Start scheduled tasks
        - Initialize service dependencies
        - Set ``self._initialized = True`` when complete
        """
        raise NotImplementedError("_init() must be implemented by Manager subclasses")

    def _track_task_handle(self, handle):
        """Record scheduler task handles for automatic cancellation."""
        if not hasattr(self, "_scheduled_handles"):
            self._scheduled_handles = []
        self._scheduled_handles.append(handle)
        return handle

    def shutdown(self):
        """
        Release all resources owned by this manager.

        Default implementation is a no-op. Subclasses should override to:
        - Cancel scheduled tasks (via scheduler handles)
        - Deinitialize hardware resources (pins, radios, etc.)
        - Clear long-lived references (services, sessions, etc.)
        - Set ``self._initialized = False``

        This method should be idempotent (safe to call multiple times).
        """
        if hasattr(self, "_scheduled_handles"):
            scheduler = Scheduler.instance()
            for handle in self._scheduled_handles:
                with contextlib.suppress(Exception):
                    scheduler.cancel(handle)
            self._scheduled_handles = []

        self._initialized = False

    # Context manager support --------------------------------------------------

    def __enter__(self):
        """Return the manager instance for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Ensure ``shutdown()`` is called when leaving a ``with`` block.

        Exceptions from the block are not suppressed (returns False).
        """
        self.shutdown()
        return False
