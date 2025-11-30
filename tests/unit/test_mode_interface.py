"""Unit tests for Mode base class."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestModeBaseClass(unittest.TestCase):
    """Test Mode base class behavior."""

    def test_mode_has_required_class_attributes(self) -> None:
        from modes.mode_interface import Mode

        self.assertEqual(Mode.name, "BaseMode")
        self.assertFalse(Mode.requires_wifi)
        self.assertEqual(Mode.order, 999)


class TestModeInitialization(unittest.TestCase):
    """Test Mode initialization."""

    def setUp(self) -> None:
        # Reset singletons
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def test_init_sets_running_false(self) -> None:
        mock_conn_mgr = MagicMock()
        mock_pixel = MagicMock()
        mock_input_mgr = MagicMock()

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=mock_conn_mgr),
            patch("modes.mode_interface.PixelController", return_value=mock_pixel),
            patch("modes.mode_interface.InputManager.instance", return_value=mock_input_mgr),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            self.assertFalse(mode._running)


class TestModeInitialize(unittest.TestCase):
    """Test Mode.initialize() method."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def test_initialize_returns_true_when_wifi_not_required(self) -> None:
        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=MagicMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            mode.requires_wifi = False
            self.assertTrue(mode.initialize())

    def test_initialize_returns_true_when_wifi_connected(self) -> None:
        mock_conn_mgr = MagicMock()
        mock_conn_mgr.is_connected.return_value = True

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=mock_conn_mgr),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=MagicMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            mode.requires_wifi = True
            result = mode.initialize()
            self.assertTrue(result)

    def test_initialize_returns_false_when_wifi_not_connected(self) -> None:
        mock_conn_mgr = MagicMock()
        mock_conn_mgr.is_connected.return_value = False

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=mock_conn_mgr),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=MagicMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            mode.requires_wifi = True
            self.assertFalse(mode.initialize())


class TestModeRun(unittest.TestCase):
    """Test Mode.run() method."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def test_run_raises_not_implemented(self) -> None:
        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=MagicMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            with self.assertRaises(NotImplementedError):
                asyncio.run(mode.run())


class TestModeCleanup(unittest.TestCase):
    """Test Mode.cleanup() method."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def test_cleanup_sets_running_false(self) -> None:
        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=MagicMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            mode._running = True
            mode.cleanup()
            self.assertFalse(mode._running)


class TestModeHelpers(unittest.TestCase):
    """Test Mode convenience helper methods."""

    def setUp(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def tearDown(self) -> None:
        from controllers.pixel_controller import PixelController
        from managers.connection_manager import ConnectionManager
        from managers.input_manager import InputManager

        PixelController._instance = None
        ConnectionManager._instance = None
        InputManager._instance = None

    def test_is_button_pressed_returns_input_mgr_state(self) -> None:
        mock_input_mgr = MagicMock()
        mock_input_mgr.is_pressed.return_value = True

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=mock_input_mgr),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            self.assertTrue(mode.is_button_pressed())

    def test_is_button_pressed_returns_false_on_exception(self) -> None:
        mock_input_mgr = MagicMock()
        mock_input_mgr.is_pressed.side_effect = Exception("Hardware error")

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=mock_input_mgr),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            self.assertFalse(mode.is_button_pressed())

    def test_wait_for_button_release_polls_until_released(self) -> None:
        mock_input_mgr = MagicMock()
        mock_input_mgr.is_pressed.side_effect = [True, True, False]

        with (
            patch("modes.mode_interface.ConnectionManager.instance", return_value=MagicMock()),
            patch("modes.mode_interface.PixelController", return_value=MagicMock()),
            patch("modes.mode_interface.InputManager.instance", return_value=mock_input_mgr),
            patch("modes.mode_interface.Scheduler.sleep", new=AsyncMock()),
            patch("core.logging_helper.logger"),
        ):
            from modes.mode_interface import Mode

            mode = Mode()
            asyncio.run(mode.wait_for_button_release(poll_delay=0.01))
            self.assertEqual(mock_input_mgr.is_pressed.call_count, 3)


if __name__ == "__main__":
    unittest.main()
