"""
InputManager - Event-driven button handling using ButtonController polling.

Responsibilities:
- Single press detection
- Long press detection (3s for setup, 10s for safe mode)
- Callback registration for button events
- Integration with scheduler for async monitoring

Only this module (and `button_controller.py`) should interact with the physical button
hardware. Other components register callbacks for button events via InputManager.

Architecture: See docs/SCHEDULER_ARCHITECTURE.md
"""

import time

from button_controller import ButtonController
from logging_helper import logger
from manager_base import ManagerBase
from scheduler import Scheduler
from utils import suppress


class ButtonEvent:
    """Button event types (CircuitPython-compatible enum)."""

    class _EventType:
        def __init__(self, name):
            self.name = name

        def __repr__(self):
            return self.name

    PRESS = _EventType("PRESS")
    RELEASE = _EventType("RELEASE")
    SINGLE_CLICK = _EventType("SINGLE_CLICK")
    DOUBLE_CLICK = _EventType("DOUBLE_CLICK")
    TRIPLE_CLICK = _EventType("TRIPLE_CLICK")
    LONG_PRESS = _EventType("LONG_PRESS")
    SETUP_MODE = _EventType("SETUP_MODE")  # 3+ seconds
    SAFE_MODE = _EventType("SAFE_MODE")  # 10+ seconds


class InputManager(ManagerBase):
    """
    Singleton manager for button input handling.

    Uses ButtonController for event detection and integrates with
    the scheduler for non-blocking button monitoring.
    """

    _instance = None
    BUTTON_MONITOR_PERIOD = 0.01

    # Button hold durations (seconds)
    SETUP_MODE_DURATION = 3.0
    SAFE_MODE_DURATION = 10.0

    _default_controller_factory = ButtonController

    def __new__(cls, *args, **kwargs):
        """
        Ensure direct instantiation (`InputManager()`) honors the singleton contract.

        This redirects constructor calls through ``instance()`` so tests and production
        code both receive the same object regardless of construction style.
        """
        return cls.instance(*args, **kwargs)

    @classmethod
    def instance(cls, button_pin=None, controller_factory=None):
        """
        Get the InputManager singleton instance.

        Supports smart reinitialization: if button_pin changes (e.g., in tests),
        the existing instance will be shut down and reinitialized with the new pin.

        Args:
            button_pin: Optional DigitalInOut pin. If None, ButtonController creates from board.BUTTON
            controller_factory: Optional factory/callable that produces a ButtonController-
                compatible object. Used by tests to inject mock controllers.

        Returns:
            InputManager: The global InputManager instance
        """
        desired_factory = controller_factory or cls._default_controller_factory

        if cls._instance is None:
            obj = super().__new__(cls)
            cls._instance = obj
            obj._initialized = False
            obj._controller_factory = desired_factory

        # If the instance isn't initialized (e.g., after shutdown), run _init() with the
        # requested pin before any compatibility checks.
        if not getattr(cls._instance, "_initialized", False):
            cls._instance._init(button_pin, desired_factory)
            return cls._instance

        # Reinitialize if dependencies changed
        if cls._instance._controller_factory is not desired_factory or not cls._instance._is_compatible_with(
            button_pin=button_pin
        ):
            cls._instance.shutdown()
            cls._instance._init(button_pin, desired_factory)

        return cls._instance

    def __init__(self, button_pin=None, controller_factory=None):
        """
        Initialize input manager (called via singleton pattern or directly).

        Args:
            button_pin: Optional DigitalInOut pin. If None, ButtonController creates from board.BUTTON
            controller_factory: Optional ButtonController factory (see ``instance``)
        """
        # Guard against re-initialization
        if getattr(self, "_initialized", False):
            return
        # If _instance is already set, don't override it
        if InputManager._instance is None:
            InputManager._instance = self
        self._init(button_pin, controller_factory or self._default_controller_factory)

    def _init(self, button_pin=None, controller_factory=None):
        """
        Internal initialization method.

        Args:
            button_pin: Optional DigitalInOut pin. If None, ButtonController creates from board.BUTTON
            controller_factory: Optional ButtonController factory/callable
        """
        self.logger = logger("wicid.input")

        # Store the button_pin that was used for initialization (for compatibility checking)
        self._init_button_pin = button_pin
        # Track the controller factory being used (for dependency comparisons)
        self._controller_factory = controller_factory or getattr(
            self,
            "_controller_factory",
            self._default_controller_factory,
        )

        # Initialize hardware controller
        self._controller = self._controller_factory(self.logger, button_pin)

        # Backwards-compatible attributes for tests/introspection
        self._button_pin = self._controller.button_pin

        self.logger.info("Initializing InputManager")

        # Callback registry: event_type -> list of callbacks
        self._callbacks = {
            ButtonEvent.PRESS: [],
            ButtonEvent.RELEASE: [],
            ButtonEvent.SINGLE_CLICK: [],
            ButtonEvent.DOUBLE_CLICK: [],
            ButtonEvent.TRIPLE_CLICK: [],
            ButtonEvent.LONG_PRESS: [],
            ButtonEvent.SETUP_MODE: [],
            ButtonEvent.SAFE_MODE: [],
        }

        # State tracking
        self._press_start_time = None
        self._is_pressed = False
        self._last_click_time = None
        self._click_count = 0
        self._queued_hold_event = None

        scheduler = Scheduler.instance()
        self._task_handle = self._track_task_handle(
            scheduler.schedule_periodic(
                coroutine=self._monitor_button,
                period=self.BUTTON_MONITOR_PERIOD,
                priority=0,
                name="Button Monitor",
            )
        )

        self._initialized = True
        self.logger.info("InputManager initialized with scheduled monitoring task")

    def _is_compatible_with(self, button_pin=None):
        """
        Check if this instance is compatible with the given button_pin.

        Args:
            button_pin: Optional DigitalInOut pin to check compatibility with

        Returns:
            bool: True if instance is compatible (same button_pin), False if reinit needed
        """
        # If not initialized yet, always compatible (will initialize)
        if not getattr(self, "_initialized", False):
            return True

        # Compare the stored init pin with the requested pin
        # Both None means both use default board.BUTTON, so compatible
        if self._init_button_pin is None and button_pin is None:
            return True

        # Same object reference means compatible
        return self._init_button_pin is button_pin

    def register_callback(self, event_type, callback):
        """
        Register a callback for button events.

        Args:
            event_type: ButtonEvent type to listen for
            callback: Callable(event_type) to invoke on event

        Example:
            def on_setup_mode(event):
                print("Setup mode requested")

            input_mgr = InputManager.instance()
            input_mgr.register_callback(ButtonEvent.SETUP_MODE, on_setup_mode)
        """
        if event_type not in self._callbacks:
            self.logger.warning(f"Unknown event type: {event_type}")
            return

        self._callbacks[event_type].append(callback)
        self.logger.debug(f"Registered callback for {event_type}")

    def unregister_callback(self, event_type, callback):
        """
        Unregister a callback for button events.

        Args:
            event_type: ButtonEvent type
            callback: Callback to remove

        Returns:
            bool: True if callback was found and removed
        """
        if event_type not in self._callbacks:
            return False

        try:
            self._callbacks[event_type].remove(callback)
            self.logger.debug(f"Unregistered callback for {event_type}")
            return True
        except ValueError:
            return False

    def _fire_event(self, event_type):
        """
        Fire callbacks for an event type.

        Args:
            event_type: ButtonEvent type that occurred
        """
        callbacks = self._callbacks.get(event_type, [])

        if callbacks:
            self.logger.debug(f"Firing {len(callbacks)} callback(s) for {event_type}")

        for callback in callbacks:
            try:
                callback(event_type)
            except Exception as e:
                self.logger.error(f"Error in button callback: {e}", exc_info=True)

    async def _monitor_button(self):
        """Async wrapper that delegates to synchronous polling helper."""
        self._monitor_button_tick()

    def _monitor_button_tick(self, now=None):
        """
        Poll button state and fire events.

        Runs at 100Hz via scheduler. Tracks hold durations for setup/safe mode
        and generates click events for short presses.

        Args:
            now: Optional timestamp (monotonic seconds). Tests can inject
                deterministic values; production defaults to time.monotonic().
        """
        pressed = False
        try:
            pressed = bool(self._controller.is_pressed())
        except Exception as exc:
            self.logger.error(f"Button read failed: {exc}")
            return

        if now is None:
            now = time.monotonic()

        if pressed and not self._is_pressed:
            self._is_pressed = True
            self._press_start_time = now
            self._queued_hold_event = None
            self._fire_event(ButtonEvent.PRESS)
            self.logger.debug("Button pressed")
            return

        if pressed and self._is_pressed:
            self._check_hold_thresholds(now)
            return

        if not pressed and self._is_pressed:
            duration = now - self._press_start_time if self._press_start_time is not None else 0.0
            self._is_pressed = False
            self._press_start_time = None
            hold_event = self._queued_hold_event
            self._queued_hold_event = None

            self._fire_event(ButtonEvent.RELEASE)
            self.logger.debug(f"Button released (held {duration:.2f}s)")

            if hold_event is ButtonEvent.SAFE_MODE:
                self.logger.info(f"Safe mode activation (held {duration:.1f}s)")
                self._reset_click_tracking()
                return
            if hold_event is ButtonEvent.SETUP_MODE:
                self.logger.info(f"Setup mode activation (held {duration:.1f}s)")
                self._reset_click_tracking()
                return

            if duration >= 1.5:
                self._fire_event(ButtonEvent.LONG_PRESS)
                self.logger.debug("Long press detected")
                self._reset_click_tracking()
            else:
                self._register_click(now)
            return

        # Handle click timeout grouping (if no new clicks, emit single)
        self._finalize_click_group(now)

    def _register_click(self, timestamp):
        """Track click counts for multi-click detection."""
        self._click_count += 1
        self._last_click_time = timestamp

        if self._click_count == 1:
            self._fire_event(ButtonEvent.SINGLE_CLICK)
            self.logger.debug("Single click detected")
        elif self._click_count == 2:
            self._fire_event(ButtonEvent.DOUBLE_CLICK)
            self.logger.debug("Double click detected")
        elif self._click_count >= 3:
            self._fire_event(ButtonEvent.TRIPLE_CLICK)
            self.logger.debug("Triple click detected")
            self._reset_click_tracking()

    def _finalize_click_group(self, now):
        """Reset click tracking if no clicks occur within grouping window."""
        if self._last_click_time is None:
            return

        if now - self._last_click_time > 0.5:
            self._reset_click_tracking()

    def _reset_click_tracking(self):
        self._last_click_time = None
        self._click_count = 0
        self._queued_hold_event = None

    def _check_hold_thresholds(self, now):
        """Detect setup/safe hold events while button remains pressed."""
        if self._press_start_time is None:
            return

        duration = now - self._press_start_time

        if duration >= self.SAFE_MODE_DURATION:
            self._emit_hold_event(ButtonEvent.SAFE_MODE, duration)
        elif duration >= self.SETUP_MODE_DURATION:
            self._emit_hold_event(ButtonEvent.SETUP_MODE, duration)

    def _emit_hold_event(self, event_type, duration):
        """Fire hold event once when threshold crossed."""
        if self._queued_hold_event is event_type:
            return

        if event_type is ButtonEvent.SAFE_MODE:
            self.logger.info(f"Safe mode hold detected (held {duration:.1f}s)")
        elif event_type is ButtonEvent.SETUP_MODE:
            self.logger.info(f"Setup mode hold detected (held {duration:.1f}s)")

        self._queued_hold_event = event_type
        self._fire_event(event_type)

    def is_pressed(self):
        """
        Check if button is currently pressed (synchronous).

        Returns:
            bool: True if button is pressed
        """
        return self._is_pressed

    def get_raw_value(self):
        """
        Get current button pressed state (synchronous).

        Returns:
            bool: True if button is currently pressed
        """
        return self._is_pressed

    def shutdown(self):
        """
        Release all resources owned by InputManager.

        Cancels the scheduled monitoring task and deinitializes the button controller.
        This is called automatically when reinitializing with different dependencies,
        or can be called explicitly for cleanup.

        This method is idempotent (safe to call multiple times).
        """
        if not getattr(self, "_initialized", False):
            return

        self._task_handle = None

        # Deinitialize button controller (releases DigitalInOut pin)
        if hasattr(self, "_controller") and self._controller is not None:
            with suppress(Exception):
                self._controller.deinit()
            self._controller = None

        # Clear references
        self._button_pin = None
        self._init_button_pin = None
        self._press_start_time = None
        self._is_pressed = False
        self._controller_factory = self._default_controller_factory
        if hasattr(self, "_callbacks") and isinstance(self._callbacks, dict):
            for callbacks in self._callbacks.values():
                callbacks.clear()
            self._callbacks = None

        super().shutdown()
        self.logger.debug("InputManager shut down")
