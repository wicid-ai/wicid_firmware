"""
Unit tests for WeatherService.

Tests cover initialization, geocoding, weather API calls, and error handling.
Uses MockSession for HTTP responses without network access.
"""

import asyncio
import sys

# Mock CircuitPython modules before importing the service
from tests.unit.unit_mocks import MockSession

# Install minimal scheduler mock for yield_control
mock_scheduler_module = type(sys)("core.scheduler")


class _MockScheduler:
    @staticmethod
    async def yield_control() -> None:
        pass

    @staticmethod
    async def sleep(seconds: float) -> None:
        pass


mock_scheduler_module.Scheduler = _MockScheduler  # type: ignore[attr-defined]
sys.modules["core.scheduler"] = mock_scheduler_module

from services.weather_service import WeatherService  # noqa: E402
from tests.unit import TestCase  # noqa: E402


def run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestWeatherServiceInit(TestCase):
    """Test WeatherService initialization."""

    def test_init_stores_zip_code(self) -> None:
        """Service stores provided ZIP code."""
        session = MockSession()
        service = WeatherService("10001", session=session)
        self.assertEqual(service.zip_code, "10001")

    def test_init_coordinates_none(self) -> None:
        """Coordinates are None until geocoding."""
        session = MockSession()
        service = WeatherService("10001", session=session)
        self.assertIsNone(service.lat)
        self.assertIsNone(service.lon)

    def test_default_timezone(self) -> None:
        """Default timezone is set."""
        session = MockSession()
        service = WeatherService("10001", session=session)
        self.assertEqual(service.timezone, "America%2FNew_York")


class TestWeatherServiceGeocoding(TestCase):
    """Test location geocoding functionality."""

    def test_ensure_location_success(self) -> None:
        """Geocoding extracts coordinates from response."""
        session = MockSession()
        session.add_response(
            {
                "results": [
                    {
                        "latitude": 40.7128,
                        "longitude": -74.006,
                        "timezone": "America/New_York",
                    }
                ]
            }
        )
        service = WeatherService("10001", session=session)

        result = run_async(service._ensure_location())

        self.assertTrue(result)
        self.assertEqual(service.lat, 40.7128)
        self.assertEqual(service.lon, -74.006)

    def test_ensure_location_caches_result(self) -> None:
        """Second call returns True without HTTP request."""
        session = MockSession()
        session.add_response({"results": [{"latitude": 40.0, "longitude": -74.0}]})
        service = WeatherService("10001", session=session)

        run_async(service._ensure_location())
        run_async(service._ensure_location())

        # Only one HTTP call despite two ensure_location calls
        self.assertEqual(session.get_call_count, 1)

    def test_ensure_location_no_results(self) -> None:
        """Returns False when no geocoding results."""
        session = MockSession()
        session.add_response({"results": []})
        service = WeatherService("10001", session=session)

        result = run_async(service._ensure_location())

        self.assertFalse(result)
        self.assertIsNone(service.lat)

    def test_ensure_location_handles_exception(self) -> None:
        """Returns False on HTTP error."""
        session = MockSession()
        session.add_response(should_raise=OSError("Network error"))
        service = WeatherService("10001", session=session)

        result = run_async(service._ensure_location())

        self.assertFalse(result)


class TestWeatherServiceAPI(TestCase):
    """Test weather API methods."""

    def setUp(self) -> None:
        """Create service with pre-set coordinates."""
        self.session = MockSession()
        self.service = WeatherService("10001", session=self.session)
        # Pre-set coordinates to skip geocoding
        self.service.lat = 40.7128
        self.service.lon = -74.006

    def test_get_current_temperature(self) -> None:
        """Returns temperature from API response."""
        self.session.add_response({"current_weather": {"temperature": 72.5}})

        result = run_async(self.service.get_current_temperature())

        self.assertEqual(result, 72.5)

    def test_get_current_temperature_no_location(self) -> None:
        """Returns None when location unavailable."""
        self.service.lat = None
        self.service.lon = None
        self.session.add_response({"results": []})  # Geocoding fails

        result = run_async(self.service.get_current_temperature())

        self.assertIsNone(result)

    def test_get_daily_high(self) -> None:
        """Returns daily high from API response."""
        self.session.add_response({"daily": {"temperature_2m_max": [85.0]}})

        result = run_async(self.service.get_daily_high())

        self.assertEqual(result, 85.0)

    def test_get_daily_precip_chance(self) -> None:
        """Returns precipitation chance from API response."""
        self.session.add_response({"daily": {"precipitation_probability_max": [45]}})

        result = run_async(self.service.get_daily_precip_chance())

        self.assertEqual(result, 45)


class TestWeatherServicePrecipWindow(TestCase):
    """Test precipitation window calculation."""

    def setUp(self) -> None:
        """Create service with pre-set coordinates."""
        self.session = MockSession()
        self.service = WeatherService("10001", session=self.session)
        self.service.lat = 40.7128
        self.service.lon = -74.006

    def test_precip_window_finds_max(self) -> None:
        """Returns max probability in window."""
        self.session.add_response(
            {
                "current_weather": {"time": "2025-02-06T14:15"},
                "hourly": {
                    "time": ["2025-02-06T14:00", "2025-02-06T15:00", "2025-02-06T16:00", "2025-02-06T17:00"],
                    "precipitation_probability": [10, 30, 50, 20],
                },
            }
        )

        # Start 1 hour from current, duration 2 hours (covers 15:00 and 16:00)
        result = run_async(self.service.get_precip_chance_in_window(1, 2))

        self.assertEqual(result, 50)

    def test_precip_window_no_match(self) -> None:
        """Returns 0 when current hour not found in data."""
        self.session.add_response(
            {
                "current_weather": {"time": "2025-02-06T14:15"},
                "hourly": {
                    "time": ["2025-02-06T10:00"],  # Doesn't match current hour
                    "precipitation_probability": [50],
                },
            }
        )

        result = run_async(self.service.get_precip_chance_in_window(0, 1))

        self.assertEqual(result, 0)

    def test_precip_window_out_of_bounds(self) -> None:
        """Returns 0 when window extends beyond data."""
        self.session.add_response(
            {
                "current_weather": {"time": "2025-02-06T14:15"},
                "hourly": {
                    "time": ["2025-02-06T14:00"],
                    "precipitation_probability": [25],
                },
            }
        )

        # Start 5 hours out (beyond available data)
        result = run_async(self.service.get_precip_chance_in_window(5, 2))

        self.assertEqual(result, 0)

    def test_precip_window_clamps_negative_start(self) -> None:
        """Negative offset is clamped to 0."""
        self.session.add_response(
            {
                "current_weather": {"time": "2025-02-06T14:15"},
                "hourly": {
                    "time": ["2025-02-06T14:00", "2025-02-06T15:00"],
                    "precipitation_probability": [60, 40],
                },
            }
        )

        result = run_async(self.service.get_precip_chance_in_window(-1, 2))

        self.assertEqual(result, 60)
