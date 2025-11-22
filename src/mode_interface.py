"""
Mode Interface - Base class for all user-selectable operating modes.

Defines the contract that all modes must implement and provides
access to shared system resources (connection manager, pixel controller, etc.).
"""

from connection_manager import ConnectionManager
from input_manager import InputManager
from logging_helper import logger
from pixel_controller import PixelController
from scheduler import Scheduler


class Mode:
    """
    Base class for all user-selectable operating modes.

    Modes have access to shared singleton resources:
    - ConnectionManager.instance() - for connectivity and session management
    - PixelController() - for LED control (singleton via __new__)
    - SystemManager.instance() - for update checks and periodic reboots

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

    def __init__(self) -> None:
        """
        Initialize mode with access to shared resources.
        """
        self.connection_manager = ConnectionManager.instance()
        self.pixel = PixelController()
        self.input_mgr = InputManager.instance()
        self._running = False
        self.logger = logger(f"wicid.modes.{self.name}")

    def initialize(self) -> bool:
        """
        Initialize mode-specific services and resources.

        Called once before run(). Mode implementations should:
        - Check WiFi if required: self.connection_manager.is_connected()
        - Initialize mode-specific services (Weather, APIs, etc.)
        - Prepare any required state
        - Return False if prerequisites not met

        Returns:
            bool: True if mode can run, False if initialization failed
        """
        # Default implementation - subclasses should override
        if self.requires_wifi:
            is_connected = self.connection_manager.is_connected()
            if not is_connected:
                self.logger.warning("WiFi required but not connected")
                return False
            self.logger.debug("WiFi connection verified")
        return True

    async def run(self) -> bool | None:
        """
        Run the mode's main loop.

        Should:
        - Run until InputManager signals a button press
        - Call ``self.input_mgr.is_pressed()`` to check for interrupts
        - Update display/LEDs as needed
        - Handle mode-specific logic

        The loop should be interruptible by button press to allow mode switching.

        Returns:
            bool | None: Optionally return status (used by SetupPortalMode), otherwise None
        """
        # Default implementation - subclasses must override
        raise NotImplementedError(f"{self.name}.run() must be implemented by subclass")

    def cleanup(self) -> None:
        """
        Clean up mode-specific resources.

        Called when mode exits (button press, error, etc.).
        Should release any mode-specific resources but NOT touch shared
        singletons (connection manager, pixel controller, etc.).
        """
        # Default implementation - subclasses can override if needed
        self._running = False
        pass

    # Convenience helpers -------------------------------------------------
    def is_button_pressed(self) -> bool:
        """Return True if the physical button is currently pressed."""
        try:
            return self.input_mgr.is_pressed()
        except Exception:
            return False

    async def wait_for_button_release(self, poll_delay: float = 0.05) -> None:
        """Block until the button is released (coarse polling)."""
        while self.is_button_pressed():
            await Scheduler.sleep(poll_delay)
