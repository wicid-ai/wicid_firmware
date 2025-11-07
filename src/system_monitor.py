"""
System Monitor for periodic system maintenance tasks.

Encapsulates update checks and periodic reboot timing. Modes call tick() 
to allow system checks without knowing implementation details.
"""

import os
import time
import microcontroller
import traceback
from logging_helper import get_logger


class SystemMonitor:
    """
    Singleton manager for periodic system maintenance tasks.
    
    Responsibilities:
    - Track boot time and schedule update checks
    - Track uptime for periodic reboots
    - Execute checks when scheduled via tick()
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls, update_manager=None):
        """
        Get singleton SystemMonitor instance.
        
        Args:
            update_manager: Optional UpdateManager for testing (only used on first call)
        
        Returns:
            SystemMonitor: The singleton instance
        """
        if cls._instance is None:
            cls._instance = cls(update_manager)
        return cls._instance
    
    def __init__(self, update_manager=None):
        """
        Private constructor. Use get_instance() instead.
        
        Args:
            update_manager: Optional UpdateManager instance for testing
        """
        if SystemMonitor._instance is not None:
            raise RuntimeError("Use SystemMonitor.get_instance() instead of direct instantiation")
        
        # Encapsulate UpdateManager creation - callers don't need to know about it
        if update_manager is None:
            from update_manager import UpdateManager
            update_manager = UpdateManager()
        
        self.update_manager = update_manager
        self.boot_time = time.monotonic()
        self.logger = get_logger('wicid.system_monitor')
        
        # Load configuration
        try:
            self.reboot_interval_hours = int(os.getenv("PERIODIC_REBOOT_INTERVAL", "0"))
        except (ValueError, TypeError):
            self.reboot_interval_hours = 0
        
        # Schedule next update check on boot
        if self.update_manager:
            self.update_manager.next_update_check = self.update_manager.schedule_next_update_check()
            reboot_status = 'disabled' if self.reboot_interval_hours == 0 else f'{self.reboot_interval_hours}h'
            self.logger.info(f"SystemMonitor initialized - periodic reboot: {reboot_status}")
    
    def tick(self):
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
            self._check_for_reboot()
            
            # Check for update check if update manager available
            if self.update_manager:
                self._check_for_updates()
                
        except Exception as e:
            self.logger.error(f"Error in SystemMonitor.tick(): {e}")
            traceback.print_exception(e)
    
    def _check_for_reboot(self):
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
            time.sleep(1)
            
            # Hard reset to ensure boot.py runs
            microcontroller.reset()
    
    def _check_for_updates(self):
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
        
        self.logger.info("Scheduled update check triggered")
        try:
            # Use centralized update workflow - handles check, download, and reboot
            self.update_manager.check_download_and_reboot(delay_seconds=1)
            
            # If we reach here, no update was available or download failed
            # Reschedule next check
            self.update_manager.next_update_check = self.update_manager.schedule_next_update_check()
            
        except Exception as e:
            self.logger.error(f"Error during scheduled update check: {e}")
            traceback.print_exception(e)
            # Reschedule to retry later
            self.update_manager.next_update_check = self.update_manager.schedule_next_update_check()

