"""
Mode Manager - Manages user-selectable operating modes and mode switching.

Handles:
- Mode registration and lifecycle
- Button-based mode switching
- Special mode entry (setup, safe mode)
"""

from controllers.pixel_controller import PixelController
from core.logging_helper import logger
from core.scheduler import Scheduler
from managers.input_manager import InputManager
from managers.manager_base import ManagerBase
from modes.mode_interface import Mode
from modes.modes import SetupPortalMode
from services.button_action_router_service import ButtonAction, ButtonActionRouterService
from utils.utils import trigger_safe_mode


class ModeManager(ManagerBase):
    """
    Manages the lifecycle and switching of user-selectable modes.

    Responsibilities:
    - Register available modes
    - Handle mode selection via button press
    - Run mode loop with button monitoring
    - Handle setup mode re-entry (3s button hold)
    - Handle safe mode entry (10s button hold)
    """

    _instance = None

    @classmethod
    def instance(cls) -> "ModeManager":
        """Get the ModeManager singleton instance."""
        return super().instance()  # type: ignore[return-value]

    def _init(self) -> None:
        """
        Initialize ModeManager.
        """
        self.modes: list[type[Mode]] = []
        self.current_mode_index = 0
        self.pixel = PixelController()
        self.logger = logger("wicid.mode_mgr")
        self.input_mgr = InputManager.instance()
        self.button_router = ButtonActionRouterService.instance()
        self._initialized = True

    def register_modes(self, mode_classes: list[type[Mode]]) -> None:
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
        duplicates = {order for order in orders if orders.count(order) > 1}
        if duplicates:
            for dup_order in duplicates:
                dup_modes = [m.name for m in self.modes if m.order == dup_order]
                self.logger.warning(
                    f"Duplicate order={dup_order} found for modes: {dup_modes}. Order is non-deterministic."
                )

        mode_info = [(m.name, m.order) for m in self.modes]
        self.logger.info(f"Registered {len(self.modes)} mode(s): {mode_info}")

    async def run(self) -> None:
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
            await self._wait_for_button_release()
            await self._process_pending_actions()

            # Get current mode class
            mode_class = self.modes[self.current_mode_index]

            # Create mode instance (modes use InputManager singleton, not button parameter)
            mode = mode_class()

            self.logger.debug(f"Starting {mode.name}")

            # Initialize mode
            try:
                if not mode.initialize():
                    self.logger.warning(f"{mode.name} initialization failed")
                    # Try next mode
                    self._next_mode()
                    await Scheduler.sleep(1)
                    continue
            except Exception as e:
                self.logger.error(f"Error initializing {mode.name}: {e}")
                await self.pixel.blink_error()
                self._next_mode()
                await Scheduler.sleep(1)
                continue

            self.logger.info(f"{mode.name} initialized")

            # Run mode
            try:
                await mode.run()
            except KeyboardInterrupt:
                self.logger.debug(f"Button interrupt in {mode.name}")
            except Exception as e:
                self.logger.error(f"Error in {mode.name}: {e}")
                await self.pixel.blink_error()
                await Scheduler.sleep(1)
            finally:
                # Cleanup mode
                try:
                    mode.cleanup()
                except Exception as e:
                    self.logger.warning(f"Error cleaning up {mode.name}: {e}")

            await self._wait_for_button_release()
            await self._process_pending_actions()
            await Scheduler.sleep(0.1)

    def _next_mode(self) -> None:
        """Advance to next mode (wraps around to first mode)."""
        self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)

    def _goto_primary_mode(self) -> None:
        """Jump to primary mode (order=0)."""
        for idx, mode_class in enumerate(self.modes):
            if mode_class.order == 0:
                self.current_mode_index = idx
                return
        # Should never happen due to validation in register_modes
        self.logger.error("Primary mode not found - this should not happen")
        self.current_mode_index = 0

    async def _process_pending_actions(self) -> None:
        while True:
            actions = self.button_router.pop_actions()
            if not actions:
                break
            for action in actions:
                if action == ButtonAction.SAFE:
                    self.logger.debug("Safe Mode requested (callback)")
                    trigger_safe_mode()
                elif action == ButtonAction.SETUP:
                    self.logger.debug("Setup Mode requested (callback)")
                    setup_success = await SetupPortalMode.execute()
                    self._goto_primary_mode()
                    if setup_success:
                        self.logger.debug("Setup complete - returning to primary mode")
                    else:
                        self.logger.debug("Setup cancelled - returning to primary mode")
                elif action == ButtonAction.NEXT:
                    self.logger.debug("Switching to next mode")
                    self._next_mode()
                else:
                    self.logger.debug(f"Unhandled button action: {action}")

    def shutdown(self) -> None:
        # ButtonActionRouter owns callback lifecycle
        pass

    async def _wait_for_button_release(self) -> None:
        while self.input_mgr.is_pressed():
            await Scheduler.sleep(0.05)
