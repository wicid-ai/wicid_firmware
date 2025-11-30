"""Unit tests for ButtonActionRouterService."""

import unittest
from unittest.mock import MagicMock, patch

from core.app_typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from services.button_action_router_service import (
        ButtonActionRouterService,
        _ButtonActionSession,
    )


class TestButtonAction(unittest.TestCase):
    """Test ButtonAction constants."""

    def test_action_values(self) -> None:
        from services.button_action_router_service import ButtonAction

        self.assertEqual(ButtonAction.NEXT, "next")
        self.assertEqual(ButtonAction.SETUP, "setup")
        self.assertEqual(ButtonAction.SAFE, "safe")


class TestButtonActionRouterServiceSingleton(unittest.TestCase):
    """Test ButtonActionRouterService singleton pattern."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def test_instance_returns_same_object(self) -> None:
        mock_input_mgr = MagicMock()
        mock_input_mgr.register_callback = MagicMock()
        mock_pixel = MagicMock()

        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            instance1 = ButtonActionRouterService.instance()
            instance2 = ButtonActionRouterService.instance()
            self.assertIs(instance1, instance2)


class TestButtonActionRouterServiceQueue(unittest.TestCase):
    """Test action queue management."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None
        self.mock_input_mgr = MagicMock()
        self.mock_input_mgr.register_callback = MagicMock()
        self.mock_pixel = MagicMock()

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def _create_router(self) -> "ButtonActionRouterService":
        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=self.mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=self.mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            return ButtonActionRouterService.instance()

    def test_pop_actions_returns_and_clears_queue(self) -> None:
        router = self._create_router()
        router._default_queue = ["next", "setup"]
        actions = router.pop_actions()
        self.assertEqual(actions, ["next", "setup"])
        self.assertEqual(router._default_queue, [])

    def test_enqueue_action_adds_to_default_queue(self) -> None:
        router = self._create_router()
        router._enqueue_action("next")
        self.assertEqual(router._default_queue, ["next"])

    def test_enqueue_setup_removes_previous_setup(self) -> None:
        router = self._create_router()
        router._default_queue = ["next", "setup", "next"]
        router._enqueue_action("setup")
        self.assertEqual(router._default_queue.count("setup"), 1)
        self.assertEqual(router._default_queue[-1], "setup")

    def test_enqueue_safe_removes_pending_setup(self) -> None:
        router = self._create_router()
        router._default_queue = ["next", "setup"]
        router._enqueue_action("safe")
        self.assertNotIn("setup", router._default_queue)
        self.assertIn("safe", router._default_queue)

    def test_remove_action_from_queue(self) -> None:
        from services.button_action_router_service import ButtonActionRouterService

        queue = ["next", "setup", "next", "setup"]
        ButtonActionRouterService._remove_action_from_queue("setup", queue)
        self.assertEqual(queue, ["next", "next"])


class TestButtonActionRouterServiceCallbacks(unittest.TestCase):
    """Test InputManager callback handling."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None
        self.mock_input_mgr = MagicMock()
        self.registered_callbacks: dict[Any, Callable[..., Any]] = {}

        def capture_callback(event: Any, callback: Callable[..., Any]) -> None:
            self.registered_callbacks[event] = callback

        self.mock_input_mgr.register_callback = capture_callback
        self.mock_pixel = MagicMock()

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def _create_router(self) -> "ButtonActionRouterService":
        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=self.mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=self.mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            return ButtonActionRouterService.instance()

    def test_single_click_enqueues_next(self) -> None:
        from managers.input_manager import ButtonEvent

        router = self._create_router()
        callback = self.registered_callbacks[ButtonEvent.SINGLE_CLICK]
        callback(MagicMock())
        self.assertIn("next", router._default_queue)

    def test_setup_mode_hold_enqueues_setup(self) -> None:
        from managers.input_manager import ButtonEvent

        router = self._create_router()
        callback = self.registered_callbacks[ButtonEvent.SETUP_MODE]
        callback(MagicMock())
        self.assertIn("setup", router._default_queue)
        self.mock_pixel.indicate_setup_mode.assert_called_once()

    def test_safe_mode_hold_enqueues_safe(self) -> None:
        from managers.input_manager import ButtonEvent

        router = self._create_router()
        callback = self.registered_callbacks[ButtonEvent.SAFE_MODE]
        callback(MagicMock())
        self.assertIn("safe", router._default_queue)
        self.mock_pixel.indicate_safe_mode.assert_called_once()


class TestButtonActionRouterServiceSession(unittest.TestCase):
    """Test session acquisition and release."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None
        self.mock_input_mgr = MagicMock()
        self.mock_input_mgr.register_callback = MagicMock()
        self.mock_pixel = MagicMock()

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def _create_router(self) -> "ButtonActionRouterService":
        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=self.mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=self.mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            return ButtonActionRouterService.instance()

    def test_acquire_session_returns_session(self) -> None:
        router = self._create_router()
        session = router.acquire_session()
        self.assertIsNotNone(session)
        self.assertEqual(router._session, session)

    def test_acquire_session_twice_raises(self) -> None:
        router = self._create_router()
        router.acquire_session()
        with self.assertRaises(RuntimeError):
            router.acquire_session()

    def test_release_session_clears_session(self) -> None:
        router = self._create_router()
        session = router.acquire_session()
        router.release_session(session)
        self.assertIsNone(router._session)

    def test_release_session_moves_queue_to_default(self) -> None:
        router = self._create_router()
        session = router.acquire_session()
        session._queue = ["next", "setup"]
        router.release_session(session)
        self.assertEqual(router._default_queue, ["next", "setup"])
        self.assertEqual(session._queue, [])

    def test_session_routes_actions(self) -> None:
        router = self._create_router()
        session = router.acquire_session()
        router._enqueue_action("next")
        self.assertIn("next", session._queue)
        self.assertEqual(router._default_queue, [])


class TestButtonActionSession(unittest.TestCase):
    """Test _ButtonActionSession behavior."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None
        self.mock_input_mgr = MagicMock()
        self.mock_input_mgr.register_callback = MagicMock()
        self.mock_input_mgr.is_pressed.return_value = False
        self.mock_pixel = MagicMock()

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.input_manager import InputManager
        from services.button_action_router_service import ButtonActionRouterService

        ButtonActionRouterService._instance = None
        PixelController._instance = None
        InputManager._instance = None

    def _create_session(self) -> "_ButtonActionSession":
        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=self.mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=self.mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            router = ButtonActionRouterService.instance()
            return router.acquire_session()

    def test_reset_clears_queue(self) -> None:
        session = self._create_session()
        session._queue = ["next", "setup"]
        session._pending_setup_release = True
        session.reset()
        self.assertEqual(session._queue, [])
        self.assertFalse(session._pending_setup_release)

    def test_safe_mode_ready_when_in_queue_and_released(self) -> None:
        session = self._create_session()
        session._queue = ["safe"]
        self.mock_input_mgr.is_pressed.return_value = False
        self.assertTrue(session.safe_mode_ready())

    def test_safe_mode_not_ready_when_pressed(self) -> None:
        session = self._create_session()
        session._queue = ["safe"]
        self.mock_input_mgr.is_pressed.return_value = True
        self.assertFalse(session.safe_mode_ready())

    def test_consume_exit_request_returns_single_for_next(self) -> None:
        session = self._create_session()
        session._queue = ["next"]
        result = session.consume_exit_request()
        self.assertEqual(result, "single")
        self.assertNotIn("next", session._queue)

    def test_consume_exit_request_returns_hold_for_setup(self) -> None:
        session = self._create_session()
        session._queue = ["setup"]
        self.mock_input_mgr.is_pressed.return_value = False
        result = session.consume_exit_request()
        self.assertEqual(result, "hold")

    def test_consume_exit_request_returns_none_when_safe_pending(self) -> None:
        session = self._create_session()
        session._queue = ["safe", "setup"]
        result = session.consume_exit_request()
        self.assertIsNone(result)

    def test_close_releases_session(self) -> None:
        with (
            patch("services.button_action_router_service.InputManager.instance", return_value=self.mock_input_mgr),
            patch("services.button_action_router_service.PixelController", return_value=self.mock_pixel),
            patch("core.logging_helper.logger"),
        ):
            from services.button_action_router_service import ButtonActionRouterService

            router = ButtonActionRouterService.instance()
            session = router.acquire_session()
            session.close()
            self.assertIsNone(router._session)


if __name__ == "__main__":
    unittest.main()
