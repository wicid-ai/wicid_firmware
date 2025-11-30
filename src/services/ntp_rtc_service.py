"""
NTP RTC Service - Periodic RTC synchronization using NTP.

Updates the device RTC from NTP servers when an active internet connection is available.
"""

import adafruit_ntp  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
import rtc  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

from core.app_typing import Any, Optional
from core.logging_helper import logger
from core.scheduler import Scheduler, TaskNonFatalError
from managers.connection_manager import ConnectionManager


class NTPRTCService:
    """
    Service for synchronizing device RTC with NTP servers.

    Schedules periodic RTC updates when an active internet connection is available.
    Updates are skipped if no connection is available.
    """

    # Update interval: 50 minutes (3000 seconds)
    UPDATE_INTERVAL = 3000.0

    # Timezone offset in hours (UTC-5 for Eastern Time)
    # Adjust as needed for your timezone
    TZ_OFFSET = -5

    def __init__(self) -> None:
        """Initialize the NTP RTC service."""
        self.logger = logger("wicid.ntp_rtc")
        self.connection_manager = ConnectionManager.instance()
        self._task_handle: Optional[Any] = None
        self._initialized = False

    def start(self) -> None:
        """
        Start the NTP RTC update service.

        Schedules a recurring task to update the RTC every UPDATE_INTERVAL seconds.
        Should be called after the system is initialized and connection is available.
        """
        if self._initialized:
            self.logger.warning("NTP RTC service already started")
            return

        scheduler = Scheduler.instance()
        handle = scheduler.schedule_recurring(
            coroutine=self._update_rtc,
            interval=self.UPDATE_INTERVAL,
            priority=70,  # Lower priority background task
            name="RTC Update",
        )
        self._task_handle = handle
        self._initialized = True
        self.logger.info(f"NTP RTC service started (update interval: {self.UPDATE_INTERVAL}s)")

    def stop(self) -> None:
        """
        Stop the NTP RTC update service.

        Cancels the scheduled recurring task.
        """
        if not self._initialized:
            return

        if self._task_handle is not None:
            scheduler = Scheduler.instance()
            scheduler.cancel(self._task_handle)
            self._task_handle = None

        self._initialized = False
        self.logger.info("NTP RTC service stopped")

    async def _update_rtc(self) -> None:
        """
        Update RTC from NTP server.

        Checks for active connection before attempting update.
        Raises TaskNonFatalError on failure to allow scheduler retry.
        """
        # Check if we have an active internet connection
        if not self.connection_manager.is_connected():
            self.logger.debug("Skipping RTC update - no active connection")
            return

        try:
            self.logger.debug("Updating RTC from NTP server...")

            # Get socket pool from connection manager
            socket_pool = self.connection_manager.get_socket_pool()
            if socket_pool is None:
                raise TaskNonFatalError("Socket pool not available for NTP update")

            # Create NTP client and fetch time
            ntp_client = adafruit_ntp.NTP(socket_pool, tz_offset=self.TZ_OFFSET)

            # Update RTC
            rtc.RTC().datetime = ntp_client.datetime

            self.logger.info("RTC updated successfully from NTP server")

        except TaskNonFatalError:
            # Re-raise to let scheduler handle retry
            raise

        except Exception as e:
            # Wrap any other exception as TaskNonFatalError
            error_msg = f"NTP RTC update failed: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise TaskNonFatalError(error_msg) from e
