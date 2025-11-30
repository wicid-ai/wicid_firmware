"""
Unit test mocks for WICID firmware.

Provides configurable mocks for CircuitPython-only modules and services.
These mocks use MagicMock when available and are designed for desktop-only
unit testing (not on-device execution).

Design Principles:
- Configurable via constructor arguments with sensible defaults
- Reusable across multiple tests
- Class-level state tracking for assertions
- Reset methods for test isolation

For hardware mocks that need to run on CircuitPython (on-device tests),
see tests/hardware_mocks.py instead.

Usage:
    from tests.unit.mocks import MockNTP, MockRTCModule, MockConnectionManager

    # Configure mock behavior via constructor
    ntp = MockNTP(datetime=(2025, 1, 15, 12, 0, 0, 2, 15))
    cm = MockConnectionManager(connected=True, socket_pool=my_pool)
"""

import sys

# =============================================================================
# Environment Detection
# =============================================================================
# These mocks are primarily designed for desktop unit testing. They can be
# imported on CircuitPython, but tests using them should skip on-device
# since mocking CircuitPython-native modules (rtc, adafruit_ntp) makes no
# sense when running on actual hardware.
#
# For hardware simulation mocks that work on CircuitPython (MockPin, MockPixel),
# see tests/hardware_mocks.py instead.

IS_CIRCUITPYTHON = hasattr(sys, "implementation") and sys.implementation.name == "circuitpython"

from core.app_typing import Any  # noqa: E402

# Try to import MagicMock for enhanced mocking capabilities
try:
    from unittest.mock import MagicMock
except ImportError:
    MagicMock = None  # type: ignore[assignment,misc]


# =============================================================================
# RTC Mocks (for rtc module)
# =============================================================================


class MockRTCInstance:
    """
    Mock RTC instance that tracks datetime assignment.

    Attributes:
        datetime: The current datetime value (read/write)
        datetime_history: List of all datetime values that were set
        should_raise_on_set: Exception to raise when datetime is set (for error testing)
    """

    def __init__(
        self,
        initial_datetime: Any = None,
        should_raise_on_set: Exception | None = None,
    ) -> None:
        """
        Initialize mock RTC instance.

        Args:
            initial_datetime: Initial datetime value
            should_raise_on_set: Exception to raise when datetime is set
        """
        self._datetime = initial_datetime
        self._datetime_history: list[Any] = []
        self.should_raise_on_set = should_raise_on_set

    @property
    def datetime(self) -> Any:
        """Get current datetime."""
        return self._datetime

    @datetime.setter
    def datetime(self, value: Any) -> None:
        """Set datetime, optionally raising configured exception."""
        if self.should_raise_on_set is not None:
            raise self.should_raise_on_set
        self._datetime = value
        self._datetime_history.append(value)

    @property
    def datetime_history(self) -> list[Any]:
        """Get history of all datetime values that were set."""
        return self._datetime_history.copy()

    def reset(self) -> None:
        """Reset instance state for test isolation."""
        self._datetime = None
        self._datetime_history.clear()
        self.should_raise_on_set = None


class MockRTCModule:
    """
    Mock rtc module that provides a singleton RTC instance.

    Use MockRTCModule.reset() between tests for isolation.

    Example:
        # In test setup
        MockRTCModule.reset()
        MockRTCModule.configure(initial_datetime=(2025, 1, 1, 0, 0, 0, 0, 1))

        # In test
        import rtc  # Will use MockRTCModule if installed in sys.modules
        rtc.RTC().datetime = new_value
        assert MockRTCModule.instance().datetime == new_value
    """

    _rtc_instance: MockRTCInstance | None = None
    _config: dict[str, Any] = {}

    @classmethod
    def configure(
        cls,
        initial_datetime: Any = None,
        should_raise_on_set: Exception | None = None,
    ) -> None:
        """
        Configure the mock RTC behavior.

        Args:
            initial_datetime: Initial datetime value
            should_raise_on_set: Exception to raise when datetime is set
        """
        cls._config = {
            "initial_datetime": initial_datetime,
            "should_raise_on_set": should_raise_on_set,
        }
        # Reset instance to apply new config
        cls._rtc_instance = None

    @classmethod
    def RTC(cls) -> MockRTCInstance:
        """Get the singleton RTC instance."""
        if cls._rtc_instance is None:
            cls._rtc_instance = MockRTCInstance(**cls._config)
        return cls._rtc_instance

    @classmethod
    def instance(cls) -> MockRTCInstance:
        """Alias for RTC() - get the singleton instance."""
        return cls.RTC()

    @classmethod
    def reset(cls) -> None:
        """Reset module state for test isolation."""
        cls._rtc_instance = None
        cls._config = {}


# =============================================================================
# NTP Mocks (for adafruit_ntp module)
# =============================================================================


class MockNTP:
    """
    Mock adafruit_ntp.NTP client.

    Tracks constructor calls and can simulate errors.

    Class Attributes:
        last_socket_pool: Socket pool from most recent instantiation
        last_tz_offset: Timezone offset from most recent instantiation
        call_count: Number of times NTP was instantiated
        should_raise: Exception to raise on instantiation

    Example:
        # Configure to return specific datetime
        ntp = MockNTP(socket_pool, tz_offset=-5)
        assert ntp.datetime == (2025, 1, 15, 14, 30, 0, 2, 15)

        # Configure to raise error
        MockNTP.should_raise = OSError("Network error")
        try:
            ntp = MockNTP(socket_pool)  # Raises OSError
        finally:
            MockNTP.reset()
    """

    # Class-level tracking
    last_socket_pool: Any = None
    last_tz_offset: int = 0
    call_count: int = 0
    should_raise: Exception | None = None

    # Default datetime to return
    _default_datetime = (2025, 1, 15, 14, 30, 0, 2, 15)

    def __init__(
        self,
        socket_pool: Any,
        tz_offset: int = 0,
        datetime: Any = None,
    ) -> None:
        """
        Initialize mock NTP client.

        Args:
            socket_pool: Socket pool (tracked for assertions)
            tz_offset: Timezone offset in hours
            datetime: Datetime tuple to return (uses default if None)

        Raises:
            Exception: If MockNTP.should_raise is set
        """
        # Check for configured error before anything else
        if MockNTP.should_raise is not None:
            raise MockNTP.should_raise

        # Track call
        MockNTP.call_count += 1
        MockNTP.last_socket_pool = socket_pool
        MockNTP.last_tz_offset = tz_offset

        # Store instance data
        self.socket_pool = socket_pool
        self.tz_offset = tz_offset
        self._datetime = datetime if datetime is not None else MockNTP._default_datetime

    @property
    def datetime(self) -> Any:
        """Get the datetime from NTP server (mocked)."""
        return self._datetime

    @classmethod
    def reset(cls) -> None:
        """Reset class-level state for test isolation."""
        cls.last_socket_pool = None
        cls.last_tz_offset = 0
        cls.call_count = 0
        cls.should_raise = None

    @classmethod
    def set_default_datetime(cls, datetime: Any) -> None:
        """Set the default datetime for all new instances."""
        cls._default_datetime = datetime


class MockNTPModule:
    """Mock adafruit_ntp module containing NTP class."""

    NTP = MockNTP


# =============================================================================
# Socket Pool Mock
# =============================================================================


class MockSocketPool:
    """
    Mock socket pool for testing network operations.

    Attributes:
        radio: The radio instance (if any) used to create the pool
    """

    def __init__(self, radio: Any = None) -> None:
        """
        Initialize mock socket pool.

        Args:
            radio: Optional radio instance
        """
        self.radio = radio


# =============================================================================
# Connection Manager Mock
# =============================================================================


class MockConnectionManager:
    """
    Mock ConnectionManager for testing network-dependent services.

    Configurable connection state and socket pool. Tracks method calls
    for assertions.

    Example:
        # Create connected manager
        cm = MockConnectionManager(connected=True)

        # Create disconnected manager
        cm = MockConnectionManager(connected=False)

        # After test, verify calls
        assert cm.is_connected_call_count == 1
    """

    _test_instance: "MockConnectionManager | None" = None

    def __init__(
        self,
        connected: bool = True,
        socket_pool: Any = None,
        session: Any = None,
    ) -> None:
        """
        Initialize mock connection manager.

        Args:
            connected: Whether to report as connected
            socket_pool: Socket pool to return (creates MockSocketPool if None and connected)
            session: HTTP session to return
        """
        self._connected = connected
        self._socket_pool = socket_pool if socket_pool is not None else (MockSocketPool() if connected else None)
        self._session = session

        # Call tracking
        self.is_connected_call_count = 0
        self.get_socket_pool_call_count = 0
        self.get_session_call_count = 0

    def is_connected(self) -> bool:
        """Check if connected (mocked)."""
        self.is_connected_call_count += 1
        return self._connected

    def get_socket_pool(self) -> Any:
        """Get socket pool (mocked)."""
        self.get_socket_pool_call_count += 1
        return self._socket_pool

    def get_session(self) -> Any:
        """Get HTTP session (mocked)."""
        self.get_session_call_count += 1
        return self._session

    def set_connected(self, connected: bool) -> None:
        """Change connection state during test."""
        self._connected = connected

    def set_socket_pool(self, socket_pool: Any) -> None:
        """Change socket pool during test."""
        self._socket_pool = socket_pool

    @classmethod
    def instance(cls) -> "MockConnectionManager":
        """Get the test instance (singleton pattern)."""
        if cls._test_instance is None:
            cls._test_instance = cls()
        return cls._test_instance

    @classmethod
    def set_test_instance(cls, instance: "MockConnectionManager") -> None:
        """Set the test instance."""
        cls._test_instance = instance

    @classmethod
    def reset(cls) -> None:
        """Reset class-level state for test isolation."""
        cls._test_instance = None


# =============================================================================
# Scheduler Mock
# =============================================================================


class MockScheduler:
    """
    Mock Scheduler for testing task scheduling.

    Tracks all scheduled tasks and provides assertion helpers.

    Example:
        scheduler = MockScheduler()
        handle = scheduler.schedule_recurring(
            coroutine=my_task,
            interval=60,
            priority=50,
            name="My Task"
        )
        assert len(scheduler.scheduled_tasks) == 1
        assert scheduler.scheduled_tasks[0]["name"] == "My Task"
    """

    _test_instance: "MockScheduler | None" = None

    def __init__(self) -> None:
        """Initialize mock scheduler."""
        self.scheduled_tasks: list[dict[str, Any]] = []
        self.cancelled_handles: list[Any] = []
        self._next_handle_id = 0

    def schedule_recurring(
        self,
        coroutine: Any,
        interval: float,
        priority: int = 50,
        name: str = "Unnamed Task",
        **kwargs: Any,
    ) -> "MockTaskHandle":
        """Schedule a recurring task (mocked)."""
        handle = MockTaskHandle(self._next_handle_id)
        self._next_handle_id += 1

        self.scheduled_tasks.append(
            {
                "type": "recurring",
                "coroutine": coroutine,
                "interval": interval,
                "priority": priority,
                "name": name,
                "handle": handle,
                **kwargs,
            }
        )
        return handle

    def schedule_periodic(
        self,
        coroutine: Any,
        period: float,
        priority: int = 50,
        name: str = "Unnamed Task",
        **kwargs: Any,
    ) -> "MockTaskHandle":
        """Schedule a periodic task (mocked)."""
        handle = MockTaskHandle(self._next_handle_id)
        self._next_handle_id += 1

        self.scheduled_tasks.append(
            {
                "type": "periodic",
                "coroutine": coroutine,
                "period": period,
                "priority": priority,
                "name": name,
                "handle": handle,
                **kwargs,
            }
        )
        return handle

    def schedule_once(
        self,
        coroutine: Any,
        delay: float,
        priority: int = 50,
        name: str = "Unnamed Task",
        **kwargs: Any,
    ) -> "MockTaskHandle":
        """Schedule a one-shot delayed task (mocked)."""
        handle = MockTaskHandle(self._next_handle_id)
        self._next_handle_id += 1

        self.scheduled_tasks.append(
            {
                "type": "once",
                "coroutine": coroutine,
                "delay": delay,
                "priority": priority,
                "name": name,
                "handle": handle,
                **kwargs,
            }
        )
        return handle

    def schedule_now(
        self,
        coroutine: Any,
        priority: int = 50,
        name: str = "Unnamed Task",
        **kwargs: Any,
    ) -> "MockTaskHandle":
        """Schedule a task to run immediately (mocked)."""
        handle = MockTaskHandle(self._next_handle_id)
        self._next_handle_id += 1

        self.scheduled_tasks.append(
            {
                "type": "now",
                "coroutine": coroutine,
                "priority": priority,
                "name": name,
                "handle": handle,
                **kwargs,
            }
        )
        return handle

    def cancel(self, handle: Any) -> bool:
        """Cancel a scheduled task (mocked)."""
        self.cancelled_handles.append(handle)
        return True

    def get_tasks_by_name(self, name: str) -> list[dict[str, Any]]:
        """Get all scheduled tasks with the given name."""
        return [t for t in self.scheduled_tasks if t["name"] == name]

    def get_tasks_by_type(self, task_type: str) -> list[dict[str, Any]]:
        """Get all scheduled tasks of the given type."""
        return [t for t in self.scheduled_tasks if t["type"] == task_type]

    @classmethod
    def instance(cls) -> "MockScheduler":
        """Get the test instance (singleton pattern)."""
        if cls._test_instance is None:
            cls._test_instance = cls()
        return cls._test_instance

    @classmethod
    def set_test_instance(cls, instance: "MockScheduler") -> None:
        """Set the test instance."""
        cls._test_instance = instance

    @classmethod
    def reset(cls) -> None:
        """Reset class-level state for test isolation."""
        cls._test_instance = None


class MockTaskHandle:
    """Mock task handle returned by scheduler."""

    def __init__(self, task_id: int = 0) -> None:
        """Initialize with task ID."""
        self.task_id = task_id

    def __eq__(self, other: object) -> bool:
        """Compare by task ID."""
        if isinstance(other, MockTaskHandle):
            return self.task_id == other.task_id
        return False

    def __hash__(self) -> int:
        """Hash by task ID."""
        return hash(self.task_id)


# =============================================================================
# Module Installation Helper
# =============================================================================


def install_mocks() -> dict[str, Any]:
    """
    Install mock modules into sys.modules for CircuitPython-only imports.

    Returns a dict of original modules for restoration.

    Example:
        originals = install_mocks()
        try:
            from services.ntp_rtc_service import NTPRTCService
            # ... run tests ...
        finally:
            restore_mocks(originals)
    """
    import sys

    originals: dict[str, Any] = {}

    # RTC module
    if "rtc" in sys.modules:
        originals["rtc"] = sys.modules["rtc"]
    sys.modules["rtc"] = MockRTCModule  # type: ignore[assignment]

    # NTP module
    if "adafruit_ntp" in sys.modules:
        originals["adafruit_ntp"] = sys.modules["adafruit_ntp"]
    sys.modules["adafruit_ntp"] = MockNTPModule  # type: ignore[assignment]

    return originals


def restore_mocks(originals: dict[str, Any]) -> None:
    """
    Restore original modules after testing.

    Args:
        originals: Dict returned by install_mocks()
    """
    import sys

    for name, module in originals.items():
        sys.modules[name] = module

    # Remove mocks that weren't originally present
    for name in ["rtc", "adafruit_ntp"]:
        if name not in originals and name in sys.modules:
            del sys.modules[name]


def reset_all_mocks() -> None:
    """Reset all mock class-level state. Call in tearDown."""
    MockRTCModule.reset()
    MockNTP.reset()
    MockConnectionManager.reset()
    MockScheduler.reset()
