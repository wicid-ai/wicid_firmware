"""
Unit tests for the scheduler subsystem.

These tests run on CircuitPython hardware and verify:
- Task scheduling and execution
- Priority ordering
- Error handling
- Starvation prevention
- Timing accuracy

Run via REPL:
    >>> import tests
    >>> tests.run_unit()

Or run specific test class:
    >>> from tests.unit.test_scheduler import TestSchedulerBasic
    >>> import unittest
    >>> unittest.main(module='tests.unit.test_scheduler', exit=False)
"""

import sys

# Add root to path for imports (source files are in root on CircuitPython device)
sys.path.insert(0, "/")

# Import unittest framework
from unittest import TestCase
from unittest.mock import patch

from core.app_typing import Any
from core.scheduler import Scheduler, Task, TaskFatalError, TaskHandle, TaskNonFatalError, TaskType


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
        """Verify Task object creation."""

        async def dummy_coro() -> None:
            pass

        task = Task(
            name="Test Task", priority=50, coroutine_factory=dummy_coro, task_type=TaskType.PERIODIC, timing_param=1.0
        )

        self.assertEqual(task.name, "Test Task")
        self.assertEqual(task.priority, 50)
        self.assertEqual(task.task_type, TaskType.PERIODIC)
        self.assertEqual(task.timing_param, 1.0)
        self.assertEqual(task.execution_count, 0)
        self.assertFalse(task.cancelled)

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

    def test_exceptions_exist(self) -> None:
        """Verify custom exception types are defined."""
        with self.assertRaises(TaskNonFatalError):
            raise TaskNonFatalError("test")

        with self.assertRaises(TaskFatalError):
            raise TaskFatalError("test")


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

    def test_schedule_once_returns_handle(self) -> None:
        """Verify schedule_once returns TaskHandle."""

        async def task() -> None:
            await Scheduler.sleep(0.01)

        handle = self.scheduler.schedule_once(coroutine=task, delay=1.0, priority=50, name="Test Once")

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

        handle = self.scheduler.schedule_once(
            coroutine=task,
            delay=10.0,  # Far in future
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
        """Verify yield_control proxies to asyncio.sleep(0)."""
        sentinel = object()
        with patch("scheduler.asyncio.sleep", return_value=sentinel) as mock_sleep:
            awaitable = Scheduler.yield_control()

        mock_sleep.assert_called_once_with(0)
        self.assertIs(awaitable, sentinel, "Returns awaitable from asyncio.sleep(0)")

    def test_sleep(self) -> None:
        """Verify sleep proxies to asyncio.sleep with duration."""
        sentinel = object()
        with patch("scheduler.asyncio.sleep", return_value=sentinel) as mock_sleep:
            awaitable = Scheduler.sleep(1.23)

        mock_sleep.assert_called_once_with(1.23)
        self.assertIs(awaitable, sentinel, "Returns awaitable from asyncio.sleep(seconds)")


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


# Entry point for running tests
if __name__ == "__main__":
    import unittest

    unittest.main()
