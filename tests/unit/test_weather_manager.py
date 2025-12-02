"""
Unit tests for WeatherManager.

Tests cover singleton behavior, weather service lifecycle, cached data access,
and error handling.
"""

import asyncio
import sys
from unittest.mock import MagicMock

from tests.unit import TestCase
from tests.unit.unit_mocks import MockConnectionManager, MockWeatherService, reset_all_mocks

# Patch ConnectionManager at module level before WeatherManager is imported
_original_cm = sys.modules.get("managers.connection_manager")
mock_cm_module = type(sys)("managers.connection_manager")
mock_cm_module.ConnectionManager = MockConnectionManager  # type: ignore[attr-defined]
sys.modules["managers.connection_manager"] = mock_cm_module

from managers.weather_manager import WeatherManager  # noqa: E402


def run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestWeatherManagerCachedData(TestCase):
    """Test cached weather data access."""

    def setUp(self) -> None:
        """Reset mocks and manager."""
        reset_all_mocks()
        WeatherManager._instance = None
        MockConnectionManager.set_test_instance(MockConnectionManager())

    def tearDown(self) -> None:
        """Clean up manager."""
        if WeatherManager._instance is not None:
            WeatherManager._instance.shutdown()
            WeatherManager._instance = None
        reset_all_mocks()

    def test_initial_cached_values_are_none(self) -> None:
        """All cached values are None before first update."""
        manager = WeatherManager.instance()

        self.assertIsNone(manager.get_current_temperature())
        self.assertIsNone(manager.get_daily_high())
        self.assertIsNone(manager.get_precip_chance())

    def test_cached_getters_return_stored_values(self) -> None:
        """Getters return values set during update."""
        manager = WeatherManager.instance()

        # Manually set cached values (simulating successful update)
        manager._current_temp = 72.5
        manager._daily_high = 85.0
        manager._precip_chance = 30

        self.assertEqual(manager.get_current_temperature(), 72.5)
        self.assertEqual(manager.get_daily_high(), 85.0)
        self.assertEqual(manager.get_precip_chance(), 30)


class TestWeatherManagerSingleton(TestCase):
    """Test singleton and compatibility behavior."""

    def setUp(self) -> None:
        """Reset mocks and manager."""
        reset_all_mocks()
        WeatherManager._instance = None
        MockConnectionManager.set_test_instance(MockConnectionManager())

    def tearDown(self) -> None:
        """Clean up manager."""
        if WeatherManager._instance is not None:
            WeatherManager._instance.shutdown()
            WeatherManager._instance = None
        reset_all_mocks()

    def test_instance_returns_same_object(self) -> None:
        """Multiple instance() calls return same object."""
        manager1 = WeatherManager.instance()
        manager2 = WeatherManager.instance()

        self.assertIs(manager1, manager2)

    def test_reinit_on_zip_change(self) -> None:
        """New ZIP triggers reinitialization."""
        manager1 = WeatherManager.instance(weather_zip="10001")
        manager2 = WeatherManager.instance(weather_zip="90210")

        # Same instance (reinited), but with new zip stored
        self.assertIs(manager1, manager2)
        self.assertEqual(manager2._init_weather_zip, "90210")


class TestWeatherManagerShutdown(TestCase):
    """Test shutdown behavior."""

    def setUp(self) -> None:
        """Reset mocks and manager."""
        reset_all_mocks()
        WeatherManager._instance = None
        MockConnectionManager.set_test_instance(MockConnectionManager())

    def tearDown(self) -> None:
        """Clean up manager."""
        if WeatherManager._instance is not None:
            WeatherManager._instance.shutdown()
            WeatherManager._instance = None
        reset_all_mocks()

    def test_shutdown_clears_references(self) -> None:
        """Shutdown clears weather service and cached data."""
        manager = WeatherManager.instance()

        # Set some values
        manager._current_temp = 72.5
        manager._precip_chance = 30
        manager._weather = MagicMock()

        manager.shutdown()

        self.assertIsNone(manager._current_temp)
        self.assertIsNone(manager._precip_chance)
        self.assertIsNone(manager._weather)

    def test_shutdown_is_idempotent(self) -> None:
        """Multiple shutdown calls are safe."""
        manager = WeatherManager.instance()

        manager.shutdown()
        manager.shutdown()  # Should not raise


class TestWeatherManagerUpdate(TestCase):
    """Test weather update logic."""

    def setUp(self) -> None:
        """Reset mocks and manager."""
        reset_all_mocks()
        WeatherManager._instance = None
        MockConnectionManager.set_test_instance(MockConnectionManager())

    def tearDown(self) -> None:
        """Clean up manager."""
        if WeatherManager._instance is not None:
            WeatherManager._instance.shutdown()
            WeatherManager._instance = None
        reset_all_mocks()

    def test_update_skips_when_service_none(self) -> None:
        """Update does nothing when weather service not initialized."""
        manager = WeatherManager.instance()
        # Don't initialize weather service

        # Should not raise, just return early
        run_async(manager._update_weather())

        self.assertIsNone(manager._current_temp)

    def test_update_stores_fetched_data(self) -> None:
        """Update stores data from weather service."""
        manager = WeatherManager.instance()
        mock_weather = MockWeatherService(
            current_temp=75.0,
            daily_high=88.0,
            window_precip=25,
        )
        manager._weather = mock_weather

        run_async(manager._update_weather())

        self.assertEqual(manager._current_temp, 75.0)
        self.assertEqual(manager._daily_high, 88.0)
        self.assertEqual(manager._precip_chance, 25)

    def test_update_handles_api_error(self) -> None:
        """Update wraps API errors in TaskNonFatalError."""
        manager = WeatherManager.instance()
        mock_weather = MockWeatherService(should_raise=OSError("Network error"))
        manager._weather = mock_weather

        try:
            run_async(manager._update_weather())
            self.fail("Expected exception not raised")
        except Exception as e:
            # Check the exception type by name to avoid module identity issues
            self.assertEqual(type(e).__name__, "TaskNonFatalError")

    def test_update_handles_memory_error(self) -> None:
        """MemoryError from weather service is wrapped as TaskNonFatalError.

        Note: MemoryError is a subclass of Exception, so it's caught by
        the inner exception handler and wrapped as TaskNonFatalError.
        """
        manager = WeatherManager.instance()
        mock_weather = MockWeatherService(should_raise=MemoryError("OOM"))
        manager._weather = mock_weather

        try:
            run_async(manager._update_weather())
            self.fail("Expected exception not raised")
        except Exception as e:
            # MemoryError from service gets wrapped as TaskNonFatalError
            # (the outer MemoryError handler only catches direct MemoryErrors)
            self.assertEqual(type(e).__name__, "TaskNonFatalError")
