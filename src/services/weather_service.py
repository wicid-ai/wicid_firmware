from core.app_typing import Any
from core.logging_helper import logger
from core.scheduler import Scheduler
from managers.connection_manager import ConnectionManager


class WeatherService:
    """
    Service for fetching weather data from Open-Meteo API.

    Uses the HTTP session managed by ConnectionManager. The session lifecycle
    is handled by ConnectionManager, so this service does not need to manage
    socket resources.
    """

    def __init__(self, weather_zip: str, session: Any = None) -> None:
        """
        Initialize the WeatherService.

        Args:
            weather_zip: ZIP code string for weather location
            session: Optional adafruit_requests.Session instance (for tests only)

        Note:
            Uses adafruit_requests.Session (blocking) because CircuitPython does not
            support true non-blocking socket I/O. See docs/STYLE_GUIDE.md section on
            CircuitPython Compatibility for details on the blocking I/O limitation.
        """
        self.logger = logger("wicid.weather")
        self.zip_code = weather_zip
        self._test_session = session  # Only used for testing

        # Coordinates will be fetched on first use
        self.lat: float | None = None
        self.lon: float | None = None
        self.timezone: str = "America%2FNew_York"

    def _get_session(self) -> Any:
        """
        Get the HTTP session for making requests.

        Uses the test session if provided, otherwise gets the session from ConnectionManager.
        ConnectionManager owns the session lifecycle.
        """
        if self._test_session is not None:
            return self._test_session
        return ConnectionManager.instance().get_session()

    async def _ensure_location(self) -> bool:
        """Ensure we have coordinates for the ZIP code."""
        if self.lat is not None and self.lon is not None:
            return True

        try:
            # NOTE: session.get() is blocking (CircuitPython limitation)
            # We yield control immediately after to allow scheduler to run other tasks
            # See docs/STYLE_GUIDE.md (CircuitPython Compatibility) for details
            url = f"https://nominatim.openstreetmap.org/search?postalcode={self.zip_code}&country=US&format=json&limit=1&addressdetails=1"
            session = self._get_session()
            response = session.get(url)
            await Scheduler.yield_control()

            data = response.json()
            response.close()

            if data and len(data) > 0:
                result = data[0]
                self.lat = float(result["lat"])
                self.lon = float(result["lon"])
                return True
            else:
                self.logger.warning(f"No location found for ZIP {self.zip_code}")
                return False

        except Exception as e:
            self.logger.error(f"Geocoding failed: {e}")
            return False

    async def get_current_temperature(self) -> float | None:
        """
        Returns the current temperature in degrees Fahrenheit.

        Returns:
            float: Current temperature in °F, or None if location data unavailable
        """
        if not await self._ensure_location():
            return None

        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true&temperature_unit=fahrenheit&timezone={self.timezone}&models=dmi_seamless"
        session = self._get_session()
        response = session.get(url)
        await Scheduler.yield_control()

        data = response.json()
        response.close()

        return data["current_weather"]["temperature"]

    async def get_daily_high(self) -> float | None:
        """
        Returns the forecasted high temperature (in °F) for the current day.

        Returns:
            float: Daily high temperature in °F, or None if location data unavailable
        """
        if not await self._ensure_location():
            return None

        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&daily=temperature_2m_max&forecast_days=1&temperature_unit=fahrenheit&timezone={self.timezone}&models=dmi_seamless"
        session = self._get_session()
        response = session.get(url)
        await Scheduler.yield_control()

        data = response.json()
        response.close()

        return data["daily"]["temperature_2m_max"][0]

    async def get_precip_chance_in_window(
        self, start_time_offset: float, forecast_window_duration: float
    ) -> int | None:
        """
        Returns the maximum precipitation probability (%) from the hourly data array,
        by matching the hour in 'current_weather.time' to the hour entries in 'hourly.time'.
        For example, if current_weather.time is '2025-02-06T14:15', it will look for
        '2025-02-06T14:00' in hourly.time.

        Args:
            start_time_offset: Hours from 'current hour' to start
            forecast_window_duration: Hours to include

        Returns:
            int: Maximum precipitation probability in that window (0-100), or 0 if no data
        """
        if not await self._ensure_location():
            return None

        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true&hourly=precipitation_probability&forecast_days=3&timezone={self.timezone}&models=dmi_seamless"
        session = self._get_session()
        response = session.get(url)
        await Scheduler.yield_control()

        data = response.json()
        response.close()

        times = data["hourly"]["time"]  # e.g., ["2025-02-06T14:00", ...]
        probs = data["hourly"]["precipitation_probability"]
        current_time_str = data["current_weather"]["time"]  # e.g. "2025-02-06T14:15"

        # Extract just the "YYYY-MM-DDTHH"
        hour_str = current_time_str[:13]  # e.g. "2025-02-06T14"

        # Match against the first 13 chars of each entry in 'times'
        current_index = None
        for i, t in enumerate(times):
            if t[:13] == hour_str:
                current_index = i
                break

        if current_index is None:
            self.logger.warning("Could not match current_weather hour in hourly data")
            return 0

        start_hour = current_index + int(start_time_offset)
        end_hour = start_hour + int(forecast_window_duration)

        # Clamp to array bounds
        if start_hour >= len(probs):
            return 0
        if end_hour > len(probs):
            end_hour = len(probs)
        if start_hour < 0:
            start_hour = 0

        window_probs = probs[start_hour:end_hour]
        if not window_probs:
            return 0

        return max(window_probs)
