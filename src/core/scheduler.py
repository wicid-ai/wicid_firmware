"""
Scheduler subsystem for WICID firmware.

Provides cooperative multitasking with priority-based scheduling, starvation prevention,
and complete asyncio isolation. Only this module imports asyncio.

Architecture: See docs/SCHEDULER_ARCHITECTURE.md
Version: 0.1
"""

import asyncio
import time

from core.app_typing import Any, Callable
from core.logging_helper import logger


# Simple min-heap for CircuitPython (lacks heapq module)
class _MinHeap:
    """Minimal binary heap for priority queue operations."""

    def __init__(self) -> None:
        self.heap: list[Any] = []

    def push(self, item: Any) -> None:
        """Add item and maintain heap property."""
        self.heap.append(item)
        self._sift_up(len(self.heap) - 1)

    def pop(self) -> Any:
        """Remove and return smallest item."""
        if not self.heap:
            raise IndexError("pop from empty heap")
        self.heap[0], self.heap[-1] = self.heap[-1], self.heap[0]
        item = self.heap.pop()
        if self.heap:
            self._sift_down(0)
        return item

    def heapify(self) -> None:
        """Rebuild heap after modifications."""
        n = len(self.heap)
        for i in range(n // 2 - 1, -1, -1):
            self._sift_down(i)

    def __len__(self) -> int:
        """Return number of items in heap."""
        return len(self.heap)

    def _sift_up(self, idx: int) -> None:
        while idx > 0:
            parent = (idx - 1) // 2
            if self.heap[idx] < self.heap[parent]:
                self.heap[idx], self.heap[parent] = self.heap[parent], self.heap[idx]
                idx = parent
            else:
                break

    def _sift_down(self, idx: int) -> None:
        n = len(self.heap)
        while True:
            smallest = idx
            left = 2 * idx + 1
            right = 2 * idx + 2
            if left < n and self.heap[left] < self.heap[smallest]:
                smallest = left
            if right < n and self.heap[right] < self.heap[smallest]:
                smallest = right
            if smallest != idx:
                self.heap[idx], self.heap[smallest] = self.heap[smallest], self.heap[idx]
                idx = smallest
            else:
                break


# Simple enum for CircuitPython (lacks enum module)
class _EnumMember:
    """Simple enum member for CircuitPython compatibility."""

    def __init__(self, name: str, value: Any) -> None:
        self.name = name
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _EnumMember) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f"{self.name}"


# Exception types for error handling
class TaskNonFatalError(Exception):
    """Task cannot recover from this error, but system can continue.

    The scheduler will:
    - Log the error with task context
    - Cancel the current execution
    - For periodic/recurring tasks: Reschedule for next interval
    - For one-shot tasks: Cancel entirely

    Examples:
    - HTTP 404 during update check
    - Weather API rate limit exceeded
    - Network timeout
    - Invalid sensor reading
    """

    pass


class TaskFatalError(Exception):
    """Task cannot recover AND system integrity is compromised.

    The scheduler will:
    - Log the error with full traceback
    - Propagate exception to main loop
    - Main loop should trigger graceful shutdown and watchdog reboot

    Examples:
    - Out of memory (MemoryError)
    - Hardware fault (I2C bus failure)
    - Corrupted critical configuration
    - File system corruption
    """

    pass


class TaskType:
    """Task scheduling type (CircuitPython-compatible)."""

    PERIODIC = _EnumMember("PERIODIC", 1)  # Fixed-rate: next_run = last_scheduled + period
    ONE_SHOT = _EnumMember("ONE_SHOT", 2)  # Run once after delay
    RECURRING = _EnumMember("RECURRING", 3)  # Interval starts after task completes


class TaskHandle:
    """Opaque handle for task management.

    Returned by schedule_* methods. Can be used to cancel tasks.
    Do not construct directly.
    """

    _next_id = 0

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id

    def __repr__(self) -> str:
        return f"TaskHandle({self.task_id})"

    @classmethod
    def _generate_id(cls) -> int:
        """Generate unique task ID."""
        task_id = cls._next_id
        cls._next_id += 1
        return task_id


class Task:
    """Task abstraction encapsulating scheduling metadata and execution state."""

    def __init__(
        self,
        name: str,
        priority: int,
        coroutine_factory: Callable[[], Any],
        task_type: Any,
        timing_param: float,
    ) -> None:
        """Create a new task.

        Args:
            name: Human-readable identifier
            priority: Original priority (0-90, lower = higher priority)
            coroutine_factory: Callable that returns a coroutine when invoked
            task_type: TaskType enum value (string or _EnumMember)
            timing_param: Period/delay/interval in seconds
        """
        self.task_id = TaskHandle._generate_id()
        self.name = name
        self.priority = priority
        self.coroutine_factory = coroutine_factory
        self.task_type = task_type.name if hasattr(task_type, "name") else str(task_type)
        self.timing_param = timing_param

        # Runtime state
        self.next_run_time: float | None = None  # Monotonic timestamp
        self.ready_since: float | None = None  # For starvation prevention
        self.effective_priority = priority
        self.last_run_time: float | None = None
        self.last_scheduled_time: float | None = None  # For fixed-rate periodic tasks
        self.execution_count = 0
        self.total_runtime = 0.0
        self.cancelled = False

    def __lt__(self, other: "Task") -> bool:
        """Comparison for heap ordering: (next_run_time, effective_priority, task_id)."""
        if self.next_run_time != other.next_run_time:
            if self.next_run_time is None:
                return True  # None sorts before any value
            if other.next_run_time is None:
                return False  # Any value sorts after None
            return self.next_run_time < other.next_run_time
        if self.effective_priority != other.effective_priority:
            return self.effective_priority < other.effective_priority
        return self.task_id < other.task_id

    def __repr__(self) -> str:
        return f"Task(id={self.task_id}, name='{self.name}', pri={self.priority}, type={self.task_type})"


class Scheduler:
    """Cooperative multitasking scheduler with priority-based scheduling.

    Singleton facade over asyncio. Provides unified task scheduling API
    with starvation prevention and error handling.
    """

    _instance = None

    # Configuration
    MAX_STARVATION_TIME = 60.0  # seconds
    STARVATION_PRIORITY_BOOST = 30  # priority points
    TASK_WARNING_THRESHOLD_MS = 100  # milliseconds
    FALL_BEHIND_DEBUG_THRESHOLD = 30.0  # seconds
    FALL_BEHIND_INFO_THRESHOLD = 120.0  # seconds
    FALL_BEHIND_WARNING_THRESHOLD = 180.0  # seconds

    def __new__(cls) -> "Scheduler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def instance(cls) -> "Scheduler":
        """Get the scheduler singleton.

        Returns:
            The global Scheduler instance
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._init()
        return cls._instance

    def __init__(self) -> None:
        """Initialize scheduler (called once via singleton pattern)."""
        # Guard against re-initialization
        if getattr(self, "_initialized", False):
            return
        # If _instance is already set, don't override it
        if Scheduler._instance is None:
            Scheduler._instance = self
        self._init()

    def _init(self) -> None:
        """Internal initialization method."""
        self.logger = logger("wicid.scheduler")
        self.logger.info("Initializing Scheduler v0.1")

        # Task management
        self.ready_queue = _MinHeap()  # Min-heap of tasks sorted by (next_run_time, priority, id)
        self.task_registry: dict[int, Task] = {}  # task_id -> Task

        # Statistics
        self.total_tasks_scheduled = 0
        self.total_tasks_executed = 0
        self.total_tasks_failed = 0

        # Event loop (set after run_forever starts)
        self.loop: Any = None
        self._active_asyncio_tasks: set[Any] = set()
        self._fatal_error: Any = None
        self._initialized: bool = True
        self.logger.info("Scheduler initialized")

    # -------------------------------------------------------------------------
    # Public API: Task Scheduling
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_awaitable(obj: Any) -> bool:
        """Check if an object is awaitable (coroutine or has __await__)."""
        return hasattr(obj, "__await__")

    def _make_coroutine_factory(self, coroutine: Any) -> Callable[[], Any]:
        """Convert various coroutine-like objects to a standardized factory function."""
        """Normalize callable into a factory that returns awaitables."""
        if not callable(coroutine):
            raise TypeError("Scheduler requires coroutine functions (pass the async function without calling it)")

        def factory() -> Any:
            result = coroutine()
            if not Scheduler._is_awaitable(result):
                raise TypeError(f"Scheduled callable '{coroutine}' must return an awaitable coroutine")
            return result

        return factory

    def schedule_periodic(
        self, coroutine: Any, period: float, priority: int = 50, name: str = "Unnamed Task"
    ) -> TaskHandle:
        """Schedule a task to run every N seconds at fixed rate.

        Uses fixed-rate scheduling: next run = last_scheduled_time + period.
        Prevents drift for timing-sensitive tasks like LED animations.

        Args:
            coroutine: Async callable to execute (pass the async function without calling it)
            period: Seconds between executions (fixed-rate)
            priority: Task priority (0-90, lower = higher priority)
            name: Human-readable task identifier

        Returns:
            TaskHandle for cancellation/management

        Example:
            # LED updates every 40ms (25Hz)
            handle = scheduler.schedule_periodic(
                coroutine=led_animation_task,
                period=0.04,
                priority=0,
                name="LED Animation"
            )
        """
        factory = self._make_coroutine_factory(coroutine)
        task = Task(name, priority, factory, TaskType.PERIODIC, period)
        task.next_run_time = time.monotonic()  # Run immediately
        task.last_scheduled_time = task.next_run_time

        self._register_task(task)
        return TaskHandle(task.task_id)

    def schedule_once(self, coroutine: Any, delay: float, priority: int = 50, name: str = "Unnamed Task") -> TaskHandle:
        """Schedule a task to run once after N seconds delay.

        Args:
            coroutine: Async callable to execute (pass the async function without calling it)
            delay: Seconds to wait before execution
            priority: Task priority (0-90, lower = higher priority)
            name: Human-readable task identifier

        Returns:
            TaskHandle for cancellation

        Example:
            # Initial update check 60 seconds after boot
            handle = scheduler.schedule_once(
                coroutine=check_for_updates,
                delay=60.0,
                priority=50,
                name="Initial Update Check"
            )
        """
        factory = self._make_coroutine_factory(coroutine)
        task = Task(name, priority, factory, TaskType.ONE_SHOT, delay)
        task.next_run_time = time.monotonic() + delay

        self._register_task(task)
        return TaskHandle(task.task_id)

    def schedule_recurring(
        self, coroutine: Any, interval: float, priority: int = 50, name: str = "Unnamed Task", count: int | None = None
    ) -> TaskHandle:
        """Schedule a task to run repeatedly with N seconds between completions.

        Unlike periodic tasks, recurring tasks wait for completion before
        scheduling the next run: next run = completion_time + interval.

        Args:
            coroutine: Async callable to execute (pass the async function without calling it)
            interval: Seconds between task completions
            priority: Task priority (0-90, lower = higher priority)
            name: Human-readable task identifier

        Returns:
            TaskHandle for cancellation/management

        Example:
            # Weather updates every 20 minutes (after previous update completes)
            handle = scheduler.schedule_recurring(
                coroutine=weather_update_task,
                interval=1200.0,
                priority=40,
                name="Weather Updates"
            )
        """
        factory = self._make_coroutine_factory(coroutine)
        task = Task(name, priority, factory, TaskType.RECURRING, interval)
        task.next_run_time = time.monotonic()  # Run immediately

        self._register_task(task)
        return TaskHandle(task.task_id)

    def schedule_now(self, coroutine: Any, priority: int = 50, name: str = "Unnamed Task") -> TaskHandle:
        """Schedule a task to run as soon as possible (one-shot).

        Args:
            coroutine: Async function to execute
            priority: Task priority (0-90, lower = higher priority)
            name: Human-readable task identifier

        Returns:
            TaskHandle for cancellation

        Example:
            # Handle button press immediately
            handle = scheduler.schedule_now(
                coroutine=handle_button_press,
                priority=10,
                name="Button Handler"
            )
        """
        factory = self._make_coroutine_factory(coroutine)
        task = Task(name, priority, factory, TaskType.ONE_SHOT, 0)
        task.next_run_time = time.monotonic()  # Run immediately

        self._register_task(task)
        return TaskHandle(task.task_id)

    def cancel(self, handle: TaskHandle) -> bool:
        """Cancel a scheduled task.

        Args:
            handle: TaskHandle returned from schedule_* methods

        Returns:
            True if task was cancelled, False if already completed/cancelled
        """
        task = self.task_registry.get(handle.task_id)
        if task and not task.cancelled:
            task.cancelled = True
            self.logger.info(f"Cancelled task '{task.name}' (id={task.task_id})")
            return True
        return False

    # -------------------------------------------------------------------------
    # Public API: Asyncio Wrappers
    # -------------------------------------------------------------------------

    @staticmethod
    def yield_control() -> Any:
        """Return awaitable that yields control to other tasks.

        Use this in tight loops or CPU-bound operations to prevent
        monopolizing the scheduler. Equivalent to asyncio.sleep(0).

        Returns:
            Awaitable that completes immediately after yielding
        """
        return asyncio.sleep(0)

    @staticmethod
    def sleep(seconds: float) -> Any:
        """Return awaitable that sleeps for specified duration.

        Args:
            seconds: Duration to sleep (can be fractional)

        Returns:
            Awaitable that completes after specified duration
        """
        return asyncio.sleep(seconds)

    # -------------------------------------------------------------------------
    # Internal: Task Management
    # -------------------------------------------------------------------------

    def _register_task(self, task: Task) -> None:
        """Register a task and add to ready queue."""
        self.task_registry[task.task_id] = task
        self.ready_queue.push(task)
        self.total_tasks_scheduled += 1

        self.logger.info(
            f"Registered task '{task.name}' "
            f"(id={task.task_id}, priority={task.priority}, "
            f"type={task.task_type}, param={task.timing_param}s)"
        )

    def _reschedule_task(self, task: Task) -> None:
        """Reschedule a task based on its type."""
        now = time.monotonic()

        if task.task_type == TaskType.PERIODIC.name:
            # Fixed-rate: next run = last_scheduled + period
            if task.last_scheduled_time is None:
                task.last_scheduled_time = time.monotonic()
            task.last_scheduled_time += task.timing_param
            task.next_run_time = task.last_scheduled_time

            # If we fell behind, catch up (run immediately)
            if task.next_run_time < now:
                delay = now - task.next_run_time
                if delay >= self.FALL_BEHIND_WARNING_THRESHOLD:
                    self.logger.warning(f"Task '{task.name}' fell behind schedule (behind by {delay:.3f}s)")
                elif delay >= self.FALL_BEHIND_INFO_THRESHOLD:
                    self.logger.info(f"Task '{task.name}' fell behind schedule (behind by {delay:.3f}s)")
                elif delay >= self.FALL_BEHIND_DEBUG_THRESHOLD:
                    self.logger.debug(f"Task '{task.name}' fell behind schedule (behind by {delay:.3f}s)")
                task.next_run_time = now
                task.last_scheduled_time = now

        elif task.task_type == TaskType.RECURRING.name:
            # Interval starts after completion
            task.next_run_time = now + task.timing_param

        elif task.task_type == TaskType.ONE_SHOT.name:
            # Don't reschedule one-shot tasks
            return

        # Reset starvation tracking
        task.ready_since = None
        task.effective_priority = task.priority

        # Re-add to queue
        self.ready_queue.push(task)

    def _apply_starvation_prevention(self) -> None:
        """Check for starved tasks and boost their priority."""
        now = time.monotonic()

        for task in self.ready_queue.heap:
            if task.cancelled:
                continue

            # Track when task became ready
            if task.ready_since is None and task.next_run_time <= now:
                task.ready_since = now

            # Check for starvation
            if task.ready_since is not None:
                waiting_time = now - task.ready_since

                if waiting_time > self.MAX_STARVATION_TIME:
                    # Boost priority
                    old_priority = task.effective_priority
                    task.effective_priority = max(0, task.priority - self.STARVATION_PRIORITY_BOOST)

                    if old_priority != task.effective_priority:
                        self.logger.info(
                            f"Task '{task.name}' starved for {waiting_time:.1f}s, "
                            f"boosted priority {old_priority} → {task.effective_priority}"
                        )

        # Re-heapify to apply priority changes
        self.ready_queue.heapify()

    # -------------------------------------------------------------------------
    # Internal: Task Execution
    # -------------------------------------------------------------------------

    async def _run_task(self, task: Task) -> None:
        """Execute a single task with error handling."""
        start_time = time.monotonic()

        try:
            # Disable debug logging for tasks to reduce noise
            # self.logger.debug(f"Running task '{task.name}'")

            # Execute the coroutine (create fresh instance each run)
            coroutine = task.coroutine_factory()
            await coroutine

            # Update statistics
            runtime = time.monotonic() - start_time
            task.total_runtime += runtime
            task.execution_count += 1
            task.last_run_time = start_time
            self.total_tasks_executed += 1

            # Warn if task exceeded threshold
            runtime_ms = runtime * 1000
            if runtime_ms > self.TASK_WARNING_THRESHOLD_MS:
                self.logger.debug(
                    f"Task '{task.name}' exceeded {self.TASK_WARNING_THRESHOLD_MS}ms "
                    f"CPU time (actual={runtime_ms:.1f}ms)"
                )

            # Disable debug logging for task completion to reduce noise
            # self.logger.debug(
            #     f"Task '{task.name}' completed in {runtime_ms:.1f}ms (total executions: {task.execution_count})"
            # )

            # Reschedule if periodic/recurring
            if task.task_type in (TaskType.PERIODIC.name, TaskType.RECURRING.name):
                self._reschedule_task(task)

        except TaskNonFatalError as e:
            # Task failed, but system continues
            self.logger.error(f"Task '{task.name}' failed (non-fatal): {e}")
            self.total_tasks_failed += 1

            # Reschedule periodic/recurring tasks
            if task.task_type in (TaskType.PERIODIC.name, TaskType.RECURRING.name):
                self._reschedule_task(task)

        except TaskFatalError as e:
            # System integrity compromised
            self.logger.critical(f"FATAL error in task '{task.name}': {e}")
            self.logger.critical("System stability compromised - propagating to main loop")
            raise  # Re-raise to enclosing wrapper

        except Exception as e:
            # Unknown exception - treat as non-fatal by default
            self.logger.error(f"Task '{task.name}' raised unexpected exception: {e}", exc_info=True)
            self.total_tasks_failed += 1

            # Reschedule periodic/recurring tasks
            if task.task_type in (TaskType.PERIODIC.name, TaskType.RECURRING.name):
                self._reschedule_task(task)

    async def _task_wrapper(self, task: Task) -> None:
        """Wrapper around _run_task that tracks asyncio task lifecycle."""
        try:
            await self._run_task(task)
        except TaskFatalError as fatal_error:
            # Capture fatal error so main loop can exit cleanly
            self._fatal_error = fatal_error
        finally:
            # Remove from active task set
            current = asyncio.current_task()
            if current in self._active_asyncio_tasks:
                self._active_asyncio_tasks.remove(current)

    async def _event_loop(self) -> None:
        """Main scheduler event loop."""
        self.logger.info("Scheduler event loop started")
        self.loop = asyncio.get_running_loop()

        last_starvation_check = time.monotonic()

        while True:
            if self._fatal_error is not None:
                raise self._fatal_error

            # Periodic starvation prevention check (every 10 seconds)
            now = time.monotonic()
            if now - last_starvation_check > 10.0:
                self._apply_starvation_prevention()
                last_starvation_check = now

            # Get next ready task
            if not self.ready_queue.heap:
                # No tasks scheduled - wait briefly
                await asyncio.sleep(0.1)
                continue

            # Peek at next task
            next_task = self.ready_queue.heap[0]

            # Skip cancelled tasks
            if next_task.cancelled:
                self.ready_queue.pop()
                del self.task_registry[next_task.task_id]
                continue

            # Check if task is ready to run
            now = time.monotonic()
            if next_task.next_run_time > now:
                # Sleep until next task is ready
                sleep_time = min(next_task.next_run_time - now, 0.1)
                await asyncio.sleep(sleep_time)
                continue

            # Remove task from queue and execute asynchronously
            task = self.ready_queue.pop()
            asyncio_task = asyncio.create_task(self._task_wrapper(task))
            self._active_asyncio_tasks.add(asyncio_task)

    # -------------------------------------------------------------------------
    # Public API: Scheduler Lifecycle
    # -------------------------------------------------------------------------

    def run_forever(self) -> None:
        """Start the scheduler event loop.

        This method never returns under normal conditions. It runs the
        asyncio event loop and continuously executes scheduled tasks.

        Raises:
            TaskFatalError: If a task encounters a fatal error
            Exception: If the scheduler itself crashes
        """
        self.logger.info("Starting scheduler event loop...")
        self.logger.info(
            f"Configuration: MAX_STARVATION_TIME={self.MAX_STARVATION_TIME}s, "
            f"STARVATION_PRIORITY_BOOST={self.STARVATION_PRIORITY_BOOST}, "
            f"TASK_WARNING_THRESHOLD_MS={self.TASK_WARNING_THRESHOLD_MS}ms"
        )

        try:
            # Run the event loop
            asyncio.run(self._event_loop())
        except TaskFatalError:
            # Re-raise fatal errors to caller
            raise
        except Exception as e:
            self.logger.critical(f"Scheduler event loop crashed: {e}", exc_info=True)
            raise

    # -------------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------------

    def dump_state(self) -> dict[str, Any]:
        """Return lightweight snapshot of scheduler state for debugging.

        Returns:
            dict: Scheduler statistics and queued task information
        """
        snapshot = []
        now = time.monotonic()

        for task in self.ready_queue.heap:
            snapshot.append(
                {
                    "id": task.task_id,
                    "name": task.name,
                    "priority": task.priority,
                    "next_in": task.next_run_time - now,
                    "effective_priority": task.effective_priority,
                    "ready_since": task.ready_since,
                }
            )

        return {
            "tasks_scheduled": self.total_tasks_scheduled,
            "tasks_executed": self.total_tasks_executed,
            "tasks_failed": self.total_tasks_failed,
            "queued_tasks": snapshot,
        }

    def describe(self) -> str:
        """Return human-readable snapshot useful for REPL debugging.

        Returns:
            str: Human-readable scheduler state and task queue
        """
        state = self.dump_state()
        lines = [
            f"Scheduler State: scheduled={state['tasks_scheduled']}, "
            f"executed={state['tasks_executed']}, failed={state['tasks_failed']}"
        ]
        if not state["queued_tasks"]:
            lines.append("  (no queued tasks)")
        else:
            lines.append("  Queued Tasks:")
            for task in state["queued_tasks"]:
                lines.append(
                    "    - {name} (id={task_id}, pri={priority}, effective={effective}, next_in={next_in:.3f}s)".format(
                        name=task["name"],
                        task_id=task["id"],
                        priority=task["priority"],
                        effective=task["effective_priority"],
                        next_in=task["next_in"],
                    )
                )
        return "\n".join(lines)
