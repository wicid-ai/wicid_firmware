"""
Unit tests for NTP RTC Service.

Tests RTC synchronization with NTP servers, including:
- Service initialization and lifecycle
- Connection status checking
- RTC update functionality
- Error handling
- Task scheduling

NOTE: These tests mock CircuitPython-native modules (rtc, adafruit_ntp) and
only run on desktop. On-device, the module import will fail gracefully and
these tests will be skipped.

See tests.unit for instructions on running tests.
"""

import asyncio
import sys
from unittest.mock import patch

from core.app_typing import Any
from core.scheduler import TaskNonFatalError
from tests.unit import TestCase
from tests.unit.mocks import (
    MockConnectionManager,
    MockNTP,
    MockRTCModule,
    MockScheduler,
    reset_all_mocks,
)

# Install mocks in sys.modules BEFORE importing the service.
# On CircuitPython, rtc and adafruit_ntp are real modules, so this
# would shadow them - but on CircuitPython we want to use the real
# modules anyway (integration tests), not mocks.
sys.modules["rtc"] = MockRTCModule  # type: ignore[assignment]
sys.modules["adafruit_ntp"] = type("MockNTPModule", (), {"NTP": MockNTP})()  # type: ignore[assignment]

# Also mock socketpool if not available (needed by ConnectionManager)
if "socketpool" not in sys.modules:
    sys.modules["socketpool"] = type("socketpool", (), {"SocketPool": lambda radio: None})()  # type: ignore[assignment]

# Now import the service (it will use our mocked modules)
from services.ntp_rtc_service import NTPRTCService  # noqa: E402


class TestNTPRTCService(TestCase):
    """Tests for NTP RTC Service."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Reset all mock state
        reset_all_mocks()

        # Create and install mock connection manager
        self.mock_connection_manager = MockConnectionManager(connected=True)
        MockConnectionManager.set_test_instance(self.mock_connection_manager)

        # Create mock scheduler
        self.mock_scheduler = MockScheduler()
        MockScheduler.set_test_instance(self.mock_scheduler)

        # Patch the service's imports using unittest.mock.patch
        self._cm_patcher = patch("services.ntp_rtc_service.ConnectionManager", MockConnectionManager)
        self._scheduler_patcher = patch("services.ntp_rtc_service.Scheduler", MockScheduler)
        self._cm_patcher.start()
        self._scheduler_patcher.start()

    def tearDown(self) -> None:
        """Clean up after tests."""
        # Stop patchers
        self._scheduler_patcher.stop()
        self._cm_patcher.stop()

        # Reset all mock state
        reset_all_mocks()

    def test_service_initialization(self) -> None:
        """Test service initializes correctly."""
        service = NTPRTCService()

        self.assertFalse(service._initialized)
        self.assertIsNone(service._task_handle)
        self.assertEqual(service.connection_manager, self.mock_connection_manager)

    def test_start_schedules_recurring_task(self) -> None:
        """Test that start() schedules a recurring task."""
        service = NTPRTCService()
        service.start()

        # Verify scheduler was called
        tasks = self.mock_scheduler.get_tasks_by_name("RTC Update")
        self.assertEqual(len(tasks), 1)

        task = tasks[0]
        self.assertEqual(task["type"], "recurring")
        self.assertEqual(task["interval"], NTPRTCService.UPDATE_INTERVAL)
        self.assertEqual(task["priority"], 70)
        self.assertEqual(task["coroutine"], service._update_rtc)

        # Verify service state
        self.assertTrue(service._initialized)
        self.assertIsNotNone(service._task_handle)

    def test_start_idempotent(self) -> None:
        """Test that calling start() twice doesn't schedule duplicate tasks."""
        service = NTPRTCService()
        service.start()
        service.start()  # Call again

        # Should only schedule once
        tasks = self.mock_scheduler.get_tasks_by_name("RTC Update")
        self.assertEqual(len(tasks), 1)

    def test_stop_cancels_task(self) -> None:
        """Test that stop() cancels the scheduled task."""
        service = NTPRTCService()
        service.start()
        task_handle = service._task_handle
        service.stop()

        # Verify task was cancelled
        self.assertIn(task_handle, self.mock_scheduler.cancelled_handles)
        self.assertFalse(service._initialized)
        self.assertIsNone(service._task_handle)

    def test_stop_when_not_started(self) -> None:
        """Test that stop() is safe to call when service hasn't been started."""
        service = NTPRTCService()
        service.stop()  # Should not raise

        # Should not try to cancel anything
        self.assertEqual(len(self.mock_scheduler.cancelled_handles), 0)

    def test_update_rtc_when_connected(self) -> None:
        """Test RTC update when connection is available."""
        service = NTPRTCService()

        # Run async update
        asyncio.run(service._update_rtc())

        # Verify connection was checked
        self.assertEqual(self.mock_connection_manager.is_connected_call_count, 1)

        # Verify socket pool was retrieved
        self.assertEqual(self.mock_connection_manager.get_socket_pool_call_count, 1)

        # Verify NTP was called with correct parameters
        self.assertEqual(MockNTP.call_count, 1)
        self.assertEqual(MockNTP.last_tz_offset, NTPRTCService.TZ_OFFSET)

        # Verify RTC was updated with NTP datetime
        expected_datetime = (2025, 1, 15, 14, 30, 0, 2, 15)
        self.assertEqual(MockRTCModule.instance().datetime, expected_datetime)

    def test_update_rtc_skips_when_not_connected(self) -> None:
        """Test that RTC update is skipped when no connection."""
        # Configure disconnected state
        self.mock_connection_manager.set_connected(False)

        service = NTPRTCService()
        asyncio.run(service._update_rtc())

        # Verify connection was checked
        self.assertEqual(self.mock_connection_manager.is_connected_call_count, 1)

        # Verify socket pool was NOT retrieved (update skipped)
        self.assertEqual(self.mock_connection_manager.get_socket_pool_call_count, 0)

        # RTC should not have been updated
        self.assertIsNone(MockRTCModule.instance().datetime)

    def test_update_rtc_handles_socket_pool_none(self) -> None:
        """Test that TaskNonFatalError is raised when socket pool is None."""
        # Configure to return None socket pool
        self.mock_connection_manager.set_socket_pool(None)

        service = NTPRTCService()

        with self.assertRaises(TaskNonFatalError) as context:
            asyncio.run(service._update_rtc())

        self.assertIn("Socket pool not available", str(context.exception))

    def test_update_rtc_handles_ntp_error(self) -> None:
        """Test that NTP errors are wrapped as TaskNonFatalError."""
        # Configure NTP to raise error
        MockNTP.should_raise = OSError("Network error")

        service = NTPRTCService()

        with self.assertRaises(TaskNonFatalError) as context:
            asyncio.run(service._update_rtc())

        self.assertIn("NTP RTC update failed", str(context.exception))
        self.assertIn("Network error", str(context.exception))

    def test_update_rtc_handles_rtc_error(self) -> None:
        """Test that RTC update errors are wrapped as TaskNonFatalError."""
        # Configure RTC to raise error on datetime set
        MockRTCModule.configure(should_raise_on_set=ValueError("Invalid datetime"))

        service = NTPRTCService()

        with self.assertRaises(TaskNonFatalError) as context:
            asyncio.run(service._update_rtc())

        self.assertIn("NTP RTC update failed", str(context.exception))

    def test_update_rtc_re_raises_task_non_fatal_error(self) -> None:
        """Test that TaskNonFatalError is re-raised without wrapping."""
        # Create connection manager that raises TaskNonFatalError
        original_error = TaskNonFatalError("Custom error")

        class ErrorManager(MockConnectionManager):
            def get_socket_pool(self) -> Any:
                raise original_error

        error_manager = ErrorManager(connected=True)
        MockConnectionManager.set_test_instance(error_manager)

        service = NTPRTCService()

        with self.assertRaises(TaskNonFatalError) as context:
            asyncio.run(service._update_rtc())

        # Should be the same exception, not wrapped
        self.assertIs(context.exception, original_error)

    def test_update_interval_constant(self) -> None:
        """Test that UPDATE_INTERVAL is set correctly (50 minutes = 3000 seconds)."""
        self.assertEqual(NTPRTCService.UPDATE_INTERVAL, 3000.0)

    def test_tz_offset_constant(self) -> None:
        """Test that TZ_OFFSET is set correctly."""
        self.assertEqual(NTPRTCService.TZ_OFFSET, -5)
