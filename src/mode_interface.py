"""
Mode Interface - Base class for all user-selectable operating modes.

Defines the contract that all modes must implement and provides
access to shared system resources (WiFiManager, PixelController, etc.).
"""

from logging_helper import get_logger
from wifi_manager import WiFiManager
from pixel_controller import PixelController


class Mode:
    """
    Base class for all user-selectable operating modes.
    
    Modes have access to shared singleton resources:
    - WiFiManager.get_instance() - for connectivity and session management
    - PixelController() - for LED control (singleton via __new__)
    - SystemMonitor.get_instance() - for update checks and periodic reboots
    
    Subclasses must implement:
    - name: str - Mode name for identification
    - requires_wifi: bool - Whether mode needs WiFi connectivity
    - order: int - Display order (0 = primary mode, higher = secondary)
    - initialize() - Setup mode-specific resources
    - run() - Main mode loop
    - cleanup() - Resource cleanup
    
    Mode Ordering:
    - order = 0: Primary mode (exactly one required)
    - order > 0: Secondary modes (order determines sequence)
    - Button press cycles through modes in ascending order
    - After successful setup, returns to primary mode (order=0)
    """
    
    name = "BaseMode"
    requires_wifi = False
    order = 999  # Default high value for base class
    
    def __init__(self, button):
        """
        Initialize mode with access to shared resources.
        
        Args:
            button: Hardware button reference for user input
        """
        self.button = button
        self.wifi_manager = WiFiManager.get_instance()
        self.pixel = PixelController()
        self._running = False
        self.logger = get_logger(f'wicid.modes.{self.name}')
    
    def initialize(self) -> bool:
        """
        Initialize mode-specific services and resources.
        
        Called once before run(). Mode implementations should:
        - Check WiFi if required: self.wifi_manager.is_connected()
        - Initialize mode-specific services (Weather, APIs, etc.)
        - Prepare any required state
        - Return False if prerequisites not met
        
        Returns:
            bool: True if mode can run, False if initialization failed
        """
        # Default implementation - subclasses should override
        if self.requires_wifi:
            is_connected = self.wifi_manager.is_connected()
            if not is_connected:
                self.logger.warning("WiFi required but not connected")
                return False
            self.logger.debug("WiFi connection verified")
        return True
    
    def run(self) -> None:
        """
        Run the mode's main loop.
        
        Should:
        - Run until button press detected
        - Check self.button.value in loop for button press
        - Update display/LEDs as needed
        - Handle mode-specific logic
        
        The loop should be interruptible by button press to allow mode switching.
        """
        # Default implementation - subclasses must override
        raise NotImplementedError(f"{self.name}.run() must be implemented by subclass")
    
    def cleanup(self) -> None:
        """
        Clean up mode-specific resources.
        
        Called when mode exits (button press, error, etc.).
        Should release any mode-specific resources but NOT touch shared
        singletons (WiFiManager, PixelController, etc.).
        """
        # Default implementation - subclasses can override if needed
        self._running = False
        pass

