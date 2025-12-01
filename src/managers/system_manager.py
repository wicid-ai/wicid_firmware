"""
SystemManager for periodic system maintenance tasks.

Encapsulates update checks and periodic reboot timing. Modes call tick()
to allow system checks without knowing implementation details.
"""

import os
import time

import microcontroller  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

from core.app_typing import Any
from core.logging_helper import logger
from core.scheduler import Scheduler
from managers.manager_base import ManagerBase


class SystemManager(ManagerBase):
    """
    Singleton manager for periodic system maintenance tasks.

    Responsibilities:
    - Track boot time and schedule update checks
    - Track uptime for periodic reboots
    - Execute checks when scheduled via tick()
    """

    _instance = None
    SYSTEM_UPDATE_INITIAL_DELAY_SECONDS = 60

    @classmethod
    def instance(cls, update_manager: Any = None) -> "SystemManager":
        """
        Get singleton SystemManager instance.

        Args:
            update_manager: Optional UpdateManager for testing (only used on first call)

        Returns:
            SystemManager: The singleton instance
        """
        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._init(update_manager)
        return cls._instance

    def _init(self, update_manager: Any = None) -> None:
        """Internal initialization method.

        Args:
            update_manager: Optional UpdateManager instance for testing
        """
        # Encapsulate UpdateManager creation - callers don't need to know about it
        if update_manager is None:
            from managers.update_manager import UpdateManager

            update_manager = UpdateManager.instance()

        self.update_manager = update_manager
        self.boot_time = time.monotonic()
        self.logger = logger("wicid.system_manager")

        # Load configuration
        try:
            self.reboot_interval_hours = int(os.getenv("PERIODIC_REBOOT_INTERVAL", "0"))
        except (ValueError, TypeError):
            self.reboot_interval_hours = 0

        # Schedule next update check on boot
        self.update_manager.next_update_check = self.update_manager.schedule_next_update_check(
            delay_seconds=SystemManager.SYSTEM_UPDATE_INITIAL_DELAY_SECONDS
        )
        self.logger.info(f"First update check scheduled in {SystemManager.SYSTEM_UPDATE_INITIAL_DELAY_SECONDS} seconds")
        reboot_status = "disabled" if self.reboot_interval_hours == 0 else f"{self.reboot_interval_hours}h"
        self.logger.info(f"SystemManager initialized - periodic reboot: {reboot_status}")

        self._initialized = True

    def __init__(self, update_manager: Any = None) -> None:
        """Private constructor. Use instance() instead.

        Args:
            update_manager: Optional UpdateManager instance for testing
        """
        # Guard against re-initialization
        if getattr(self, "_initialized", False):
            return
        # If _instance is already set, don't override it
        if SystemManager._instance is None:
            SystemManager._instance = self
        self._init(update_manager)

    def shutdown(self) -> None:
        """
        Release all resources owned by SystemManager.

        Default implementation is no-op (SystemManager doesn't own external resources).
        This method is idempotent (safe to call multiple times).
        """
        super().shutdown()

    async def tick(self) -> None:
        """
        Check if any system maintenance is needed.

        This method should be called regularly from modes that run long-term
        (e.g., weather mode). It's safe to call frequently as it only performs
        actions when scheduled thresholds are reached.

        Returns:
            None (always returns; reboots if actions taken)
        """
        try:
            # Check for scheduled reboot first (most critical)
            await self._check_for_reboot()

            # Check for update check if update manager available
            if self.update_manager:
                await self._check_for_updates()

        except Exception as e:
            self.logger.error(f"Error in SystemManager.tick(): {e}", exc_info=True)

    async def _check_for_reboot(self) -> None:
        """
        Check if periodic reboot interval has been reached.

        If reboot is needed, logs message and reboots immediately.
        Does not return if reboot occurs.
        """
        # Skip if disabled
        if self.reboot_interval_hours == 0:
            return

        # Calculate uptime
        uptime_seconds = time.monotonic() - self.boot_time
        uptime_hours = uptime_seconds / 3600

        if uptime_hours >= self.reboot_interval_hours:
            self.logger.info("=" * 50)
            self.logger.info("PERIODIC REBOOT")
            self.logger.info(f"Uptime: {uptime_hours:.1f} hours")
            self.logger.info(f"Interval: {self.reboot_interval_hours} hours")
            self.logger.info("Rebooting to refresh system state...")
            self.logger.info("=" * 50)

            # Small delay to allow message to be printed
            await Scheduler.sleep(1)

            # Hard reset to ensure boot.py runs
            microcontroller.reset()

    async def _check_for_updates(self) -> None:
        """
        Check if scheduled update check time has been reached.

        If update is found and downloaded, device will reboot automatically.
        Does not return if reboot occurs.
        """
        if not self.update_manager:
            return

        # Check if it's time for an update check
        if not self.update_manager.should_check_now():
            return

        self.logger.debug("Scheduled update check triggered")
        try:
            # Use centralized update workflow - handles check, download, and reboot
            await self.update_manager.check_download_and_reboot(delay_seconds=1)

            # If we reach here, no update was available or download failed
            # Reschedule next check
            self.update_manager.next_update_check = self.update_manager.schedule_next_update_check()

        except Exception as e:
            self.logger.error(f"Error during scheduled update check: {e}", exc_info=True)
            # Reschedule to retry later
            self.update_manager.next_update_check = self.update_manager.schedule_next_update_check()
