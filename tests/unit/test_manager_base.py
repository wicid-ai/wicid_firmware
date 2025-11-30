"""
Unit tests for ManagerBase class.

Tests verify:
- Singleton pattern behavior
- Lifecycle hooks (_init, shutdown)
- Context manager support
- Task handle tracking
"""

from unittest.mock import MagicMock, patch

from core.app_typing import Any, cast
from managers.manager_base import ManagerBase
from tests.unit import TestCase


class ConcreteManager(ManagerBase):
    """Concrete implementation of ManagerBase for testing."""

    _instance: "ConcreteManager | None" = None

    # Declare instance attributes for type checking
    init_args: tuple[Any, ...] | None
    init_kwargs: dict[str, Any] | None
    shutdown_called: bool

    def _init(self, *args: Any, **kwargs: Any) -> None:
        """Initialize manager with tracked arguments."""
        self.init_args = args
        self.init_kwargs = kwargs
        self.shutdown_called = False
        self._initialized = True

    def shutdown(self) -> None:
        """Shutdown and track that it was called."""
        super().shutdown()
        self.shutdown_called = True

    @classmethod
    def instance(cls, *args: Any, **kwargs: Any) -> "ConcreteManager":
        """Override to return correctly typed instance."""
        return cast("ConcreteManager", super().instance(*args, **kwargs))


class TestManagerBaseSingleton(TestCase):
    """Test singleton pattern behavior."""

    def setUp(self) -> None:
        """Reset singleton between tests."""
        ConcreteManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConcreteManager._instance = None

    def test_instance_returns_same_object(self) -> None:
        """instance() returns the same object on repeated calls."""
        mgr1 = ConcreteManager.instance()
        mgr2 = ConcreteManager.instance()
        self.assertIs(mgr1, mgr2)

    def test_instance_calls_init_once(self) -> None:
        """_init is only called on first instance() call."""
        mgr1 = ConcreteManager.instance(arg1="value1")
        self.assertEqual(mgr1.init_kwargs, {"arg1": "value1"})

        # Second call doesn't reinitialize
        mgr2 = ConcreteManager.instance(arg1="value2")
        self.assertEqual(mgr2.init_kwargs, {"arg1": "value1"})

    def test_instance_sets_initialized_flag(self) -> None:
        """instance() sets _initialized to True."""
        mgr = ConcreteManager.instance()
        self.assertTrue(mgr._initialized)


class TestManagerBaseLifecycle(TestCase):
    """Test lifecycle hooks."""

    def setUp(self) -> None:
        """Reset singleton between tests."""
        ConcreteManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConcreteManager._instance = None

    def test_shutdown_sets_initialized_false(self) -> None:
        """shutdown() sets _initialized to False."""
        mgr = ConcreteManager.instance()
        self.assertTrue(mgr._initialized)

        mgr.shutdown()
        self.assertFalse(mgr._initialized)

    def test_shutdown_is_idempotent(self) -> None:
        """shutdown() can be called multiple times safely."""
        mgr = ConcreteManager.instance()

        mgr.shutdown()
        mgr.shutdown()
        mgr.shutdown()

        self.assertFalse(mgr._initialized)

    def test_init_receives_args_and_kwargs(self) -> None:
        """_init receives positional and keyword arguments."""
        mgr = ConcreteManager.instance("arg1", "arg2", key1="val1")
        self.assertEqual(mgr.init_args, ("arg1", "arg2"))
        self.assertEqual(mgr.init_kwargs, {"key1": "val1"})


class TestManagerBaseContextManager(TestCase):
    """Test context manager support."""

    def setUp(self) -> None:
        """Reset singleton between tests."""
        ConcreteManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConcreteManager._instance = None

    def test_enter_returns_manager(self) -> None:
        """__enter__ returns the manager instance."""
        mgr = ConcreteManager.instance()
        with mgr as ctx:  # pylint: disable=not-context-manager
            self.assertIs(ctx, mgr)

    def test_exit_calls_shutdown(self) -> None:
        """__exit__ calls shutdown()."""
        mgr = ConcreteManager.instance()
        self.assertFalse(mgr.shutdown_called)

        with mgr:  # pylint: disable=not-context-manager
            pass

        self.assertTrue(mgr.shutdown_called)

    def test_exit_does_not_suppress_exceptions(self) -> None:
        """__exit__ does not suppress exceptions from the block."""
        mgr = ConcreteManager.instance()

        with self.assertRaises(ValueError):  # noqa: SIM117
            with mgr:  # pylint: disable=not-context-manager
                raise ValueError("test error")


class TestManagerBaseTaskTracking(TestCase):
    """Test task handle tracking and cleanup."""

    def setUp(self) -> None:
        """Reset singleton between tests."""
        ConcreteManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConcreteManager._instance = None

    def test_track_task_handle_stores_handles(self) -> None:
        """_track_task_handle stores handles for later cleanup."""
        mgr = ConcreteManager.instance()

        handle1 = MagicMock()
        handle2 = MagicMock()

        mgr._track_task_handle(handle1)
        mgr._track_task_handle(handle2)

        self.assertEqual(len(mgr._scheduled_handles), 2)
        self.assertIn(handle1, mgr._scheduled_handles)
        self.assertIn(handle2, mgr._scheduled_handles)

    def test_track_task_handle_returns_handle(self) -> None:
        """_track_task_handle returns the handle for chaining."""
        mgr = ConcreteManager.instance()
        handle = MagicMock()

        result = mgr._track_task_handle(handle)
        self.assertIs(result, handle)

    def test_shutdown_cancels_tracked_tasks(self) -> None:
        """shutdown() cancels all tracked task handles."""
        mgr = ConcreteManager.instance()

        handle1 = MagicMock()
        handle2 = MagicMock()
        mgr._track_task_handle(handle1)
        mgr._track_task_handle(handle2)

        with patch("managers.manager_base.Scheduler") as MockScheduler:
            mock_scheduler = MagicMock()
            MockScheduler.instance.return_value = mock_scheduler

            mgr.shutdown()

            # Verify cancel was called for each handle
            self.assertEqual(mock_scheduler.cancel.call_count, 2)

    def test_shutdown_clears_handles_list(self) -> None:
        """shutdown() clears the handles list."""
        mgr = ConcreteManager.instance()
        mgr._track_task_handle(MagicMock())

        with patch("managers.manager_base.Scheduler"):
            mgr.shutdown()

        self.assertEqual(mgr._scheduled_handles, [])


class TestManagerBaseCompatibility(TestCase):
    """Test compatibility checking."""

    def setUp(self) -> None:
        """Reset singleton between tests."""
        ConcreteManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConcreteManager._instance = None

    def test_is_compatible_with_default_true(self) -> None:
        """Default _is_compatible_with returns True."""
        mgr = ConcreteManager.instance()
        self.assertTrue(mgr._is_compatible_with())
        self.assertTrue(mgr._is_compatible_with("any", "args", key="value"))
