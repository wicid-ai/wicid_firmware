"""
Centralized routing of button events into high-level actions.

Provides a shared queue used by ModeManager and temporary sessions
(e.g., setup portal) so button semantics stay consistent across modes.
"""

from app_typing import Any
from input_manager import ButtonEvent, InputManager
from logging_helper import logger
from pixel_controller import PixelController


class ButtonAction:
    """Enum-like constants for button-driven actions."""

    NEXT = "next"
    SETUP = "setup"
    SAFE = "safe"


class ButtonActionRouter:
    """
    Singleton that listens to InputManager events and translates them into
    high-level actions (next/setup/safe). Actions are queued either for the
    default consumer (ModeManager) or for an exclusive session (setup portal).
    """

    _instance = None

    def __init__(self) -> None:
        self.logger = logger("wicid.button_router")
        self.input_mgr = InputManager.instance()
        self.pixel = PixelController()

        self._default_queue: list[str] = []
        self._session: _ButtonActionSession | None = None
        self._callbacks = [
            (ButtonEvent.SINGLE_CLICK, self._on_single_click),
            (ButtonEvent.SETUP_MODE, self._on_setup_mode_hold),
            (ButtonEvent.SAFE_MODE, self._on_safe_mode_hold),
        ]

        for event, callback in self._callbacks:
            self.input_mgr.register_callback(event, callback)

    @classmethod
    def instance(cls) -> "ButtonActionRouter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def acquire_session(self, session_logger: Any = None) -> "_ButtonActionSession":
        """
        Acquire exclusive routing session. While a session is active,
        all actions are delivered to it instead of the default queue.
        """
        if self._session is not None:
            raise RuntimeError("ButtonActionRouter session already active")

        session = _ButtonActionSession(self, session_logger)
        self._session = session
        return session

    def release_session(self, session: "_ButtonActionSession") -> None:
        if self._session is session:
            if session._queue:
                self._default_queue.extend(session._queue)
                session._queue.clear()
            self._session = None

    def pop_actions(self) -> list[str]:
        """Pop pending actions for the default consumer (ModeManager)."""
        actions = self._default_queue
        self._default_queue = []
        return actions

    # Internal helpers -------------------------------------------------
    def _target_queue(self) -> list[str]:
        if self._session is not None:
            return self._session._queue  # noqa: SLF001 (internal wiring)
        return self._default_queue

    @staticmethod
    def _remove_action_from_queue(action: str, queue: list[str]) -> None:
        queue[:] = [a for a in queue if a != action]

    def _enqueue_action(self, action: str) -> None:
        queue = self._target_queue()

        if action == ButtonAction.SETUP:
            self._remove_action_from_queue(ButtonAction.SETUP, queue)
        elif action == ButtonAction.SAFE:
            # Safe mode supersedes pending setup actions
            self._remove_action_from_queue(ButtonAction.SETUP, queue)

        queue.append(action)

    # InputManager callbacks -------------------------------------------
    def _on_single_click(self, event: Any) -> None:
        self._enqueue_action(ButtonAction.NEXT)

    def _on_setup_mode_hold(self, event: Any) -> None:
        self.pixel.indicate_setup_mode()
        self._enqueue_action(ButtonAction.SETUP)

    def _on_safe_mode_hold(self, event: Any) -> None:
        self.pixel.indicate_safe_mode()
        self._enqueue_action(ButtonAction.SAFE)


class _ButtonActionSession:
    """
    Exclusive action consumer used during setup portal. Provides the same
    interface expected by ConfigurationManager (reset/consume_* methods)
    so setup behavior stays identical to the primary mode loop.
    """

    def __init__(self, router: ButtonActionRouter, session_logger: Any = None) -> None:
        self._router = router
        self._queue: list[str] = []
        self._pending_setup_release = False
        self._input_mgr = InputManager.instance()
        self._logger = session_logger or logger("wicid.button_session")

    # API consumed by ConfigurationManager -----------------------------
    def reset(self) -> None:
        self._queue.clear()
        self._pending_setup_release = False

    def safe_mode_ready(self) -> bool:
        """Return True once safe mode hold is released."""
        return ButtonAction.SAFE in self._queue and not self._input_mgr.is_pressed()

    def consume_exit_request(self) -> str | None:
        # Handle pending setup exit once user releases the button
        if self._pending_setup_release and not self._input_mgr.is_pressed():
            self._pending_setup_release = False
            return "hold"

        if ButtonAction.SAFE in self._queue:
            # Safe mode takes precedence; let caller handle via consume_safe_mode_request
            return None

        if ButtonAction.SETUP in self._queue:
            if self._input_mgr.is_pressed():
                self._pending_setup_release = True
            else:
                ButtonActionRouter._remove_action_from_queue(ButtonAction.SETUP, self._queue)
                return "hold"

        if ButtonAction.NEXT in self._queue:
            ButtonActionRouter._remove_action_from_queue(ButtonAction.NEXT, self._queue)
            return "single"

        return None

    def close(self) -> None:
        self._pending_setup_release = False
        self._router.release_session(self)
