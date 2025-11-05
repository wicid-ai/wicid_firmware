"""
Mode Manager - Manages user-selectable operating modes and mode switching.

Handles:
- Mode registration and lifecycle
- Button-based mode switching
- Special mode entry (setup, safe mode)
"""

import time
from logging_helper import get_logger
from pixel_controller import PixelController
from utils import check_button_hold_duration, trigger_safe_mode
from configuration_manager import ConfigurationManager


class ModeManager:
    """
    Manages the lifecycle and switching of user-selectable modes.
    
    Responsibilities:
    - Register available modes
    - Handle mode selection via button press
    - Run mode loop with button monitoring
    - Handle setup mode re-entry (3s button hold)
    - Handle safe mode entry (10s button hold)
    """
    
    def __init__(self, button):
        """
        Initialize ModeManager.
        
        Args:
            button: Hardware button reference
        """
        self.button = button
        self.modes = []
        self.current_mode_index = 0
        self.pixel = PixelController()
        self.logger = get_logger('wicid.mode_mgr')
    
    def register_modes(self, mode_classes):
        """
        Register available modes and validate ordering.
        
        Args:
            mode_classes: List of Mode classes (not instances)
            
        Raises:
            ValueError: If no primary mode (order=0) exists or multiple primary modes exist
            
        Warns:
            If duplicate order values exist (non-deterministic ordering)
        """
        # Sort modes by order attribute
        self.modes = sorted(mode_classes, key=lambda m: m.order)
        
        # Validate exactly one primary mode (order=0)
        primary_modes = [m for m in self.modes if m.order == 0]
        if len(primary_modes) == 0:
            raise ValueError("No primary mode found. Exactly one mode must have order=0")
        if len(primary_modes) > 1:
            names = [m.name for m in primary_modes]
            raise ValueError(f"Multiple primary modes found: {names}. Only one mode can have order=0")
        
        # Warn about duplicate orders (non-deterministic)
        orders = [m.order for m in self.modes]
        duplicates = set([order for order in orders if orders.count(order) > 1])
        if duplicates:
            for dup_order in duplicates:
                dup_modes = [m.name for m in self.modes if m.order == dup_order]
                self.logger.warning(f"Duplicate order={dup_order} found for modes: {dup_modes}. Order is non-deterministic.")
        
        mode_info = [(m.name, m.order) for m in self.modes]
        self.logger.info(f"Registered {len(self.modes)} mode(s): {mode_info}")
    
    def run(self):
        """
        Main mode loop - never returns normally.
        
        Handles:
        - Mode initialization
        - Mode execution
        - Button press detection for mode switching
        - Special button holds (setup, safe mode)
        - Mode cleanup on exit
        """
        if not self.modes:
            raise ValueError("No modes registered. Call register_modes() first.")
        
        while True:
            # Get current mode class
            mode_class = self.modes[self.current_mode_index]
            
            # Create mode instance
            mode = mode_class(self.button)
            
            self.logger.info(f"Starting {mode.name}")
            
            # Initialize mode
            try:
                if not mode.initialize():
                    self.logger.warning(f"{mode.name} initialization failed")
                    # Try next mode
                    self._next_mode()
                    time.sleep(1)
                    continue
            except Exception as e:
                self.logger.error(f"Error initializing {mode.name}: {e}")
                self.pixel.blink_error()
                self._next_mode()
                time.sleep(1)
                continue
            
            self.logger.info(f"{mode.name} initialized")
            
            # Run mode
            try:
                mode.run()
            except KeyboardInterrupt:
                self.logger.debug(f"Button interrupt in {mode.name}")
            except Exception as e:
                self.logger.error(f"Error in {mode.name}: {e}")
                self.pixel.blink_error()
                time.sleep(1)
            finally:
                # Cleanup mode
                try:
                    mode.cleanup()
                except Exception as e:
                    self.logger.warning(f"Error cleaning up {mode.name}: {e}")
            
            # Check button state for mode switching
            if not self.button.value:  # Button is pressed
                hold_result = check_button_hold_duration(self.button, self.pixel)
                
                if hold_result == 'safe_mode':
                    self.logger.info("Safe Mode requested (10 second hold)")
                    trigger_safe_mode()
                    # Never returns
                
                elif hold_result == 'setup':
                    self.logger.info("Setup Mode requested (3 second hold)")
                    # Enter setup mode through ConfigurationManager
                    config_mgr = ConfigurationManager.get_instance(self.button)
                    setup_success = config_mgr.run_portal()
                    
                    if setup_success:
                        # Configuration saved successfully - return to primary mode
                        self.logger.info("Setup complete - returning to primary mode")
                        self._goto_primary_mode()
                    else:
                        # User cancelled - advance to next mode
                        self.logger.info("Setup cancelled - advancing to next mode")
                        self._next_mode()
                
                else:
                    # Short press - switch to next mode
                    self.logger.info("Switching to next mode")
                    self._next_mode()
                
                # Debounce
                while not self.button.value:
                    time.sleep(0.1)
                time.sleep(0.3)
            
            # Small delay before restarting mode loop
            time.sleep(0.1)
    
    def _next_mode(self):
        """Advance to next mode (wraps around to first mode)."""
        self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)
    
    def _goto_primary_mode(self):
        """Jump to primary mode (order=0)."""
        for idx, mode_class in enumerate(self.modes):
            if mode_class.order == 0:
                self.current_mode_index = idx
                return
        # Should never happen due to validation in register_modes
        self.logger.error("Primary mode not found - this should not happen")
        self.current_mode_index = 0

