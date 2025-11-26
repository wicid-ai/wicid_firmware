"""
WeatherManager - Scheduled weather data fetching and caching.

Wraps the WeatherService class with scheduler integration for periodic updates.
Provides cached weather data accessible synchronously by other components.

Architecture: See docs/SCHEDULER_ARCHITECTURE.md
"""

from core.app_typing import Any, Optional
from core.logging_helper import logger
from core.scheduler import Scheduler, TaskFatalError, TaskNonFatalError
from managers.connection_manager import ConnectionManager
from managers.manager_base import ManagerBase
from services.weather_service import WeatherService


class WeatherManager(ManagerBase):
    """
    Singleton manager for weather data with scheduled updates.

    Fetches weather data periodically via scheduler and caches results
    for synchronous access by display and other components.
    """

    _instance = None

    # Update interval: 20 minutes (1200 seconds)
    UPDATE_INTERVAL = 1200.0

    @classmethod
    def instance(cls, session: Optional[Any] = None, weather_zip: Optional[str] = None) -> "WeatherManager":
        """
        Get the WeatherManager singleton.

        Supports smart reinitialization: if session/weather_zip changes (e.g., in tests),
        the existing instance will be shut down and reinitialized.

        Args:
            session: Optional HTTP session (for initialization)
            weather_zip: Optional ZIP code (for initialization)

        Returns:
            WeatherManager: The global WeatherManager instance
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._init(session, weather_zip)
        else:
            # Check if reinitialization is needed (different session/zip)
            if not cls._instance._is_compatible_with(session=session, weather_zip=weather_zip):
                cls._instance.shutdown()
                cls._instance._init(session, weather_zip)
        return cls._instance

    def __init__(self, session: Optional[Any] = None, weather_zip: Optional[str] = None) -> None:
        """Initialize weather manager (called via singleton pattern or directly).

        Args:
            session: Optional HTTP session (for initialization)
            weather_zip: Optional ZIP code (for initialization)
        """
        # Guard against re-initialization
        if getattr(self, "_initialized", False):
            return
        # If _instance is already set, don't override it
        if WeatherManager._instance is None:
            WeatherManager._instance = self
        self._init(session, weather_zip)

    def _init(self, session: Optional[Any] = None, weather_zip: Optional[str] = None) -> None:
        """Internal initialization method.

        Args:
            session: Optional HTTP session (for initialization)
            weather_zip: Optional ZIP code (for initialization)
        """
        self.logger = logger("wicid.weather_mgr")
        self.logger.info("Initializing WeatherManager")

        # Store init parameters for compatibility checking
        self._init_weather_zip = weather_zip

        # Cached weather data
        self._current_temp: Optional[float] = None
        self._daily_high: Optional[float] = None
        self._daily_precip_chance: Optional[int] = None
        self._last_update_time: Optional[float] = None
        self._last_error: Optional[str] = None

        # Weather service instance (lazy-initialized)
        self._weather: Optional[Any] = None
        self._weather_zip = weather_zip
        self.connection_manager = ConnectionManager.instance()

        # Task handle for cancellation
        self._task_handle = None

        self._initialized = True
        self.logger.info("WeatherManager initialized (weather service will be initialized on first update)")

    def _is_compatible_with(self, session: Optional[Any] = None, weather_zip: Optional[str] = None) -> bool:
        """
        Check if this instance is compatible with the given session/weather_zip.

        Args:
            session: Optional HTTP session to check compatibility with
            weather_zip: Optional ZIP code to check compatibility with

        Returns:
            bool: True if instance is compatible, False if reinit needed
        """
        # If not initialized yet, always compatible (will initialize)
        if not getattr(self, "_initialized", False):
            return True

        # Compare stored init parameters with requested ones
        # Same object references or both None means compatible
        zip_compat = (self._init_weather_zip is None and weather_zip is None) or (self._init_weather_zip == weather_zip)
        return zip_compat

    def initialize_weather_service(self, session: Any, weather_zip: str) -> None:
        """
        Initialize the weather service with session and ZIP code.

        Must be called before scheduling updates (typically after WiFi connects).

        Args:
            session: Legacy placeholder (ignored; kept for compatibility)
            weather_zip: ZIP code for weather location
        """
        self.logger.info(f"Initializing weather service for ZIP: {weather_zip}")

        try:
            session = self.connection_manager.create_session()
            self._weather = WeatherService(weather_zip, session=session)
            self._weather_zip = weather_zip

            # Schedule recurring weather update task
            if self._task_handle is None:
                scheduler = Scheduler.instance()
                handle = scheduler.schedule_recurring(
                    coroutine=self._update_weather,
                    interval=self.UPDATE_INTERVAL,
                    priority=40,  # Background data fetching
                    name="Weather Updates",
                )
                self._task_handle = self._track_task_handle(handle)
                self.logger.info(f"Scheduled weather updates every {self.UPDATE_INTERVAL}s")

        except Exception as e:
            self.logger.error(f"Failed to initialize weather service: {e}")
            raise

    async def _update_weather(self) -> None:
        """
        Fetch weather data from API (called by scheduler every 20 minutes).

        This task runs periodically to update cached weather data.
        Explicitly yields after each network call to ensure scheduler responsiveness.
        """
        if self._weather is None:
            self.logger.warning("Weather service not initialized - skipping update")
            return

        try:
            self.logger.debug("Fetching weather data...")

            # Network calls are now async and non-blocking
            try:
                temp = await self._weather.get_current_temperature()
                high = await self._weather.get_daily_high()
                precip = await self._weather.get_daily_precip_chance()
            except Exception as fetch_error:
                raise TaskNonFatalError(f"Weather API error: {fetch_error}") from fetch_error

            # Update cached data
            self._current_temp = temp
            self._daily_high = high
            self._daily_precip_chance = precip

            import time

            self._last_update_time = time.monotonic()
            self._last_error = None

            temp_msg = f"{temp}°F" if temp is not None else "n/a"
            high_msg = f"{high}°F" if high is not None else "n/a"
            precip_msg = f"{precip}%" if precip is not None else "n/a"
            self.logger.info(f"Weather updated: {temp_msg} (high: {high_msg}, precip: {precip_msg})")

        except TaskNonFatalError:
            # Re-raise to let scheduler handle retry
            raise

        except MemoryError as e:
            # Fatal: out of memory
            raise TaskFatalError(f"OOM during weather fetch: {e}") from e

        except Exception as e:
            # Unknown exception - treat as non-fatal
            self._last_error = str(e)
            self.logger.error(f"Unexpected error fetching weather: {e}", exc_info=True)
            raise TaskNonFatalError(f"Weather fetch failed: {e}") from e

    def get_current_temperature(self) -> float | None:
        """
        Get cached current temperature (synchronous).

        Returns:
            float: Temperature in °F, or None if no data available
        """
        return self._current_temp

    def get_daily_high(self) -> float | None:
        """
        Get cached daily high temperature (synchronous).

        Returns:
            float: High temperature in °F, or None if no data available
        """
        return self._daily_high

    def get_daily_precip_chance(self) -> int | None:
        """
        Get cached precipitation chance (synchronous).

        Returns:
            int: Precipitation probability 0-100%, or None if no data available
        """
        return self._daily_precip_chance

    async def get_precip_chance_in_window(self, start_offset: float, duration: float) -> int | None:
        """
        Get precipitation chance for a future time window.

        Note: This makes a blocking API call but yields control to the scheduler.

        Args:
            start_offset: Hours from now to start window
            duration: Window duration in hours

        Returns:
            int: Maximum precipitation probability in window, or None on error
        """
        if self._weather is None:
            self.logger.warning("Weather service not initialized")
            return None

        try:
            return await self._weather.get_precip_chance_in_window(start_offset, duration)
        except Exception as e:
            self.logger.error(f"Error fetching precip window: {e}")
            return None

    def get_last_update_time(self) -> float | None:
        """
        Get timestamp of last successful update (monotonic time).

        Returns:
            float: Monotonic timestamp, or None if never updated
        """
        return self._last_update_time

    def get_last_error(self) -> str | None:
        """
        Get last error message if update failed.

        Returns:
            str: Error message, or None if no error
        """
        return self._last_error

    def is_data_stale(self, max_age_seconds: float = 1800) -> bool:
        """
        Check if cached data is stale.

        Args:
            max_age_seconds: Maximum age before data is considered stale (default: 30min)

        Returns:
            bool: True if data is stale or unavailable
        """
        if self._last_update_time is None:
            return True

        import time

        age = time.monotonic() - self._last_update_time
        return age > max_age_seconds

    async def force_update(self) -> None:
        """
        Force an immediate weather update (bypasses schedule).

        Returns when update completes. Use sparingly.
        """
        self.logger.info("Forcing weather update")
        await self._update_weather()

    def shutdown(self) -> None:
        """
        Release all resources owned by WeatherManager.

        Cancels scheduled weather updates and clears references.
        This is called automatically when reinitializing with different dependencies,
        or can be called explicitly for cleanup.

        This method is idempotent (safe to call multiple times).
        """
        if not getattr(self, "_initialized", False):
            return

        super().shutdown()
        self._task_handle = None
        # Clear references
        self._weather = None
        self._weather_zip = None
        self._init_weather_zip = None
        self._current_temp = None
        self._daily_high = None
        self._daily_precip_chance = None
        self._last_update_time = None
        self._last_error = None

        self.logger.debug("WeatherManager shut down")
