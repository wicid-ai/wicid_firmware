"""
Unit tests for the scheduler subsystem.

Tests cover:
- Task scheduling and execution
- Priority ordering
- Error handling
- TaskType enum compatibility

See tests.unit for instructions on running tests.
"""

from core.app_typing import Any
from core.scheduler import (
    Scheduler,
    Task,
    TaskFatalError,
    TaskHandle,
    TaskNonFatalError,
    TaskType,
)
from tests.unit import TestCase


class TestTaskType(TestCase):
    """Tests for TaskType pseudo-enum."""

    def test_task_types_exist(self) -> None:
        """All expected task types are defined."""
        self.assertEqual(TaskType.PERIODIC.name, "PERIODIC")
        self.assertEqual(TaskType.ONE_SHOT.name, "ONE_SHOT")
        self.assertEqual(TaskType.RECURRING.name, "RECURRING")

    def test_task_type_values_unique(self) -> None:
        """Task type values are distinct."""
        values = [TaskType.PERIODIC.value, TaskType.ONE_SHOT.value, TaskType.RECURRING.value]
        self.assertEqual(len(values), len(set(values)))


class TestSchedulerBasic(TestCase):
    """Basic scheduler functionality tests."""

    def setUp(self) -> None:
        """Reset scheduler state before each test."""
        # Note: Scheduler is a singleton, so we can't truly reset it
        # Tests must be independent and not interfere with each other
        self.test_results = {
            "executions": 0,
            "last_value": None,
            "error_caught": False,
        }

    def test_scheduler_singleton(self) -> None:
        """Verify scheduler is a singleton."""
        scheduler1 = Scheduler.instance()
        scheduler2 = Scheduler.instance()
        scheduler3 = Scheduler()

        self.assertIs(scheduler1, scheduler2, "Scheduler.instance() returns same object")
        self.assertIs(scheduler1, scheduler3, "Scheduler() returns same object")

    def test_task_handle_creation(self) -> None:
        """Verify TaskHandle generates unique IDs."""
        handle1 = TaskHandle(TaskHandle._generate_id())
        handle2 = TaskHandle(TaskHandle._generate_id())

        self.assertNotEqual(handle1.task_id, handle2.task_id, "Handles have unique IDs")

    def test_task_creation(self) -> None:
        """Verify Task dataclass creation and field access."""

        async def dummy_coro() -> None:
            pass

        task = Task(
            name="Test Task",
            priority=50,
            coroutine_factory=dummy_coro,
            task_type=TaskType.PERIODIC,
            timing_param=1.0,
        )

        self.assertEqual(task.name, "Test Task", "Task name set correctly")
        self.assertEqual(task.priority, 50, "Priority set correctly")
        self.assertEqual(task.task_type, "PERIODIC", "Task type is PERIODIC (stored as string)")
        self.assertEqual(task.timing_param, 1.0, "Timing param set correctly")
        self.assertEqual(task.execution_count, 0, "Execution count starts at 0")
        self.assertFalse(task.cancelled, "Cancelled is initially False")

    def test_task_comparison(self) -> None:
        """Verify task heap ordering."""

        async def dummy() -> None:
            pass

        task1 = Task("A", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task1.next_run_time = 100.0
        task1.effective_priority = 50

        task2 = Task("B", 0, dummy, TaskType.ONE_SHOT, 1.0)
        task2.next_run_time = 100.0
        task2.effective_priority = 0

        task3 = Task("C", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task3.next_run_time = 50.0
        task3.effective_priority = 50

        # Earlier time wins
        self.assertTrue(task3 < task1, "Earlier next_run_time has priority")

        # Same time, lower priority value wins
        self.assertTrue(task2 < task1, "Lower priority value wins when times equal")

    def test_task_comparison_with_none_times(self) -> None:
        """Tasks with None next_run_time sort first."""

        async def dummy() -> None:
            pass

        task_none = Task("A", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task_none.next_run_time = None

        task_with_time = Task("B", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task_with_time.next_run_time = 100.0

        # None sorts before any value
        self.assertTrue(task_none < task_with_time)
        self.assertFalse(task_with_time < task_none)

    def test_task_comparison_same_time_same_priority(self) -> None:
        """Tasks with same time/priority are ordered by task_id."""

        async def dummy() -> None:
            pass

        task1 = Task("A", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task1.next_run_time = 100.0
        task1.effective_priority = 50

        task2 = Task("B", 50, dummy, TaskType.ONE_SHOT, 1.0)
        task2.next_run_time = 100.0
        task2.effective_priority = 50

        # Lower task_id wins (task1 created before task2)
        self.assertTrue(task1 < task2)

    def test_task_repr(self) -> None:
        """Task repr includes key info."""

        async def dummy() -> None:
            pass

        task = Task("Test Task", 50, dummy, TaskType.PERIODIC, 1.0)
        repr_str = repr(task)

        self.assertIn("Test Task", repr_str)
        self.assertIn("50", repr_str)
        self.assertIn("PERIODIC", repr_str)

    def test_task_handle_repr(self) -> None:
        """TaskHandle repr includes task_id."""
        handle = TaskHandle(42)
        self.assertEqual(repr(handle), "TaskHandle(42)")

    def test_exceptions_exist(self) -> None:
        """Verify custom exception types are defined."""
        with self.assertRaises(TaskNonFatalError):
            raise TaskNonFatalError("test")

        with self.assertRaises(TaskFatalError):
            raise TaskFatalError("test")


class TestSchedulerHelpers(TestCase):
    """Tests for scheduler helper methods."""

    def test_is_awaitable_with_coroutine(self) -> None:
        """_is_awaitable returns True for coroutines."""

        async def coro() -> None:
            pass

        awaitable = coro()
        self.assertTrue(Scheduler._is_awaitable(awaitable))
        # Clean up the coroutine to avoid warnings
        awaitable.close()

    def test_is_awaitable_with_non_awaitable(self) -> None:
        """_is_awaitable returns False for regular objects."""
        self.assertFalse(Scheduler._is_awaitable(42))
        self.assertFalse(Scheduler._is_awaitable("string"))
        self.assertFalse(Scheduler._is_awaitable(lambda: None))

    def test_make_coroutine_factory_with_non_callable(self) -> None:
        """_make_coroutine_factory raises TypeError for non-callable."""
        scheduler = Scheduler.instance()

        with self.assertRaises(TypeError):
            scheduler._make_coroutine_factory(42)  # type: ignore[arg-type]


class TestSchedulerTaskScheduling(TestCase):
    """Tests for task scheduling API."""

    def setUp(self) -> None:
        """Setup test state."""
        self.scheduler = Scheduler.instance()
        self.execution_log: list[Any] = []

    def test_schedule_periodic_returns_handle(self) -> None:
        """Verify schedule_periodic returns TaskHandle."""

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = self.scheduler.schedule_periodic(coroutine=task, period=1.0, priority=50, name="Test Periodic")

        self.assertIsInstance(handle, TaskHandle)

        # Clean up
        self.scheduler.cancel(handle)

    def test_schedule_recurring_returns_handle(self) -> None:
        """Verify schedule_recurring returns TaskHandle."""

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = self.scheduler.schedule_recurring(coroutine=task, interval=1.0, priority=50, name="Test Recurring")

        self.assertIsInstance(handle, TaskHandle)

        # Clean up
        self.scheduler.cancel(handle)

    def test_schedule_now_returns_handle(self) -> None:
        """Verify schedule_now returns TaskHandle."""

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = self.scheduler.schedule_now(coroutine=task, priority=50, name="Test Now")

        self.assertIsInstance(handle, TaskHandle)

        # Clean up
        self.scheduler.cancel(handle)

    def test_cancel_task(self) -> None:
        """Verify task cancellation."""

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = self.scheduler.schedule_periodic(
            coroutine=task,
            period=10.0,
            priority=50,
            name="Test Cancel",
        )

        # Cancel should succeed
        result = self.scheduler.cancel(handle)
        self.assertTrue(result, "First cancel returns True")

        # Second cancel should fail (already cancelled)
        result = self.scheduler.cancel(handle)
        self.assertFalse(result, "Second cancel returns False")


class TestSchedulerAsyncWrappers(TestCase):
    """Tests for asyncio wrapper functions."""

    def test_yield_control(self) -> None:
        """Verify yield_control returns an awaitable and works correctly."""
        import asyncio

        async def test_coro() -> bool:
            # yield_control should return an awaitable that completes immediately
            await Scheduler.yield_control()
            return True

        result = asyncio.run(test_coro())
        self.assertTrue(result, "yield_control() completes successfully")

    def test_sleep(self) -> None:
        """Verify sleep returns an awaitable and sleeps for the correct duration."""
        import asyncio
        import time

        async def test_coro() -> float:
            start = time.monotonic()
            await Scheduler.sleep(0.1)  # Sleep for 100ms
            return time.monotonic() - start

        duration = asyncio.run(test_coro())
        # Allow 50ms tolerance for timing (CircuitPython unittest doesn't have assertGreaterEqual)
        self.assertTrue(duration >= 0.05, f"sleep() duration {duration} should be at least 50ms")
        self.assertTrue(duration < 0.2, f"sleep() duration {duration} should be less than 200ms")


class TestSchedulerIntegration(TestCase):
    """Integration tests requiring scheduler execution.

    Note: These tests are simplified because we can't easily
    run the full scheduler event loop in a test context.
    """

    def test_task_registration(self) -> None:
        """Verify tasks are registered correctly."""
        scheduler = Scheduler.instance()

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = scheduler.schedule_periodic(coroutine=task, period=1.0, priority=50, name="Test Registration")

        # Task should be in registry
        task_obj = scheduler.task_registry.get(handle.task_id)
        self.assertIsNotNone(task_obj, "Task exists in registry")
        if task_obj:
            self.assertEqual(task_obj.name, "Test Registration")
            self.assertEqual(task_obj.priority, 50)

        # Clean up
        scheduler.cancel(handle)

    def test_task_in_ready_queue(self) -> None:
        """Verify tasks are added to ready queue."""
        scheduler = Scheduler.instance()
        initial_queue_size = len(scheduler.ready_queue)

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = scheduler.schedule_periodic(coroutine=task, period=1.0, priority=50, name="Test Queue")

        # Queue should have one more task
        self.assertEqual(len(scheduler.ready_queue), initial_queue_size + 1, "Task added to ready queue")

        # Clean up
        scheduler.cancel(handle)


class TestTaskTypeEnum(TestCase):
    """Additional tests for TaskType enum behavior."""

    def test_task_type_equality(self) -> None:
        """TaskType values can be compared."""
        self.assertEqual(TaskType.PERIODIC, TaskType.PERIODIC)
        self.assertNotEqual(TaskType.PERIODIC, TaskType.ONE_SHOT)

    def test_task_type_in_set(self) -> None:
        """TaskType values can be used in sets."""
        s = {TaskType.PERIODIC, TaskType.ONE_SHOT}
        self.assertIn(TaskType.PERIODIC, s)
        self.assertNotIn(TaskType.RECURRING, s)


class TestSchedulerSingleton(TestCase):
    """Additional singleton tests."""

    def test_instance_same_as_constructor(self) -> None:
        """Both access methods return same instance."""
        s1 = Scheduler.instance()
        s2 = Scheduler()
        self.assertIs(s1, s2)


class TestTaskExceptions(TestCase):
    """Test exception classes."""

    def test_non_fatal_error_message(self) -> None:
        """TaskNonFatalError preserves message."""
        err = TaskNonFatalError("test message")
        self.assertEqual(str(err), "test message")

    def test_fatal_error_message(self) -> None:
        """TaskFatalError preserves message."""
        err = TaskFatalError("fatal message")
        self.assertEqual(str(err), "fatal message")


class TestSchedulerMakeCoroutineFactory(TestCase):
    """Tests for _make_coroutine_factory."""

    def test_factory_accepts_callable(self) -> None:
        """Factory accepts callable functions."""
        scheduler = Scheduler.instance()

        def sync_fn() -> int:
            return 42

        factory = scheduler._make_coroutine_factory(sync_fn)
        self.assertTrue(callable(factory))

    def test_factory_accepts_async_function(self) -> None:
        """Factory accepts async functions."""
        scheduler = Scheduler.instance()

        async def async_fn() -> str:
            return "async"

        factory = scheduler._make_coroutine_factory(async_fn)
        self.assertTrue(callable(factory))


# Entry point for running tests
if __name__ == "__main__":
    import unittest

    unittest.main()
