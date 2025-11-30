"""Unit tests for ModeManager."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestModeManagerSingleton(unittest.TestCase):
    """Test ModeManager singleton behavior."""

    def setUp(self) -> None:
        # Reset singleton before each test
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def tearDown(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def test_instance_creates_singleton(self) -> None:
        """Verify instance() creates and returns singleton."""
        with (
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager") as mock_input,
            patch("managers.mode_manager.ButtonActionRouterService") as mock_router,
        ):
            mock_input.instance.return_value = MagicMock()
            mock_router.instance.return_value = MagicMock()

            from managers.mode_manager import ModeManager

            mgr1 = ModeManager.instance()
            mgr2 = ModeManager.instance()
            self.assertIs(mgr1, mgr2)

    def test_init_sets_attributes(self) -> None:
        """Verify _init sets required attributes."""
        with (
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager") as mock_input,
            patch("managers.mode_manager.ButtonActionRouterService") as mock_router,
        ):
            mock_input.instance.return_value = MagicMock()
            mock_router.instance.return_value = MagicMock()

            from managers.mode_manager import ModeManager

            mgr = ModeManager.instance()

            self.assertEqual(mgr.modes, [])
            self.assertEqual(mgr.current_mode_index, 0)
            self.assertIsNotNone(mgr.pixel)
            self.assertIsNotNone(mgr.input_mgr)
            self.assertIsNotNone(mgr.button_router)
            self.assertTrue(mgr._initialized)


class TestModeRegistration(unittest.TestCase):
    """Test mode registration and validation."""

    def setUp(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

        self.patches = [
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager"),
            patch("managers.mode_manager.ButtonActionRouterService"),
        ]
        for p in self.patches:
            mock = p.start()
            if hasattr(mock, "instance"):
                mock.instance.return_value = MagicMock()

        self.mgr = ModeManager.instance()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def _create_mock_mode(self, name: str, order: int) -> MagicMock:
        """Create a mock mode class with name and order."""
        mode = MagicMock()
        mode.name = name
        mode.order = order
        return mode

    def test_register_modes_sorts_by_order(self) -> None:
        """Verify modes are sorted by order attribute."""
        mode_a = self._create_mock_mode("ModeA", order=2)
        mode_b = self._create_mock_mode("ModeB", order=0)
        mode_c = self._create_mock_mode("ModeC", order=1)

        self.mgr.register_modes([mode_a, mode_b, mode_c])

        self.assertEqual(self.mgr.modes[0].name, "ModeB")  # order=0
        self.assertEqual(self.mgr.modes[1].name, "ModeC")  # order=1
        self.assertEqual(self.mgr.modes[2].name, "ModeA")  # order=2

    def test_register_modes_requires_primary_mode(self) -> None:
        """Verify ValueError if no primary mode (order=0) exists."""
        mode_a = self._create_mock_mode("ModeA", order=1)
        mode_b = self._create_mock_mode("ModeB", order=2)

        with self.assertRaises(ValueError) as ctx:
            self.mgr.register_modes([mode_a, mode_b])

        self.assertIn("No primary mode found", str(ctx.exception))

    def test_register_modes_rejects_multiple_primary_modes(self) -> None:
        """Verify ValueError if multiple modes have order=0."""
        mode_a = self._create_mock_mode("ModeA", order=0)
        mode_b = self._create_mock_mode("ModeB", order=0)

        with self.assertRaises(ValueError) as ctx:
            self.mgr.register_modes([mode_a, mode_b])

        self.assertIn("Multiple primary modes found", str(ctx.exception))

    def test_register_modes_warns_on_duplicate_orders(self) -> None:
        """Verify warning logged for duplicate non-primary orders."""
        mode_a = self._create_mock_mode("ModeA", order=0)
        mode_b = self._create_mock_mode("ModeB", order=1)
        mode_c = self._create_mock_mode("ModeC", order=1)

        with patch.object(self.mgr.logger, "warning") as mock_warn:
            self.mgr.register_modes([mode_a, mode_b, mode_c])
            mock_warn.assert_called_once()
            self.assertIn("Duplicate order=1", mock_warn.call_args[0][0])


class TestModeNavigation(unittest.TestCase):
    """Test mode navigation methods."""

    def setUp(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

        self.patches = [
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager"),
            patch("managers.mode_manager.ButtonActionRouterService"),
        ]
        for p in self.patches:
            mock = p.start()
            if hasattr(mock, "instance"):
                mock.instance.return_value = MagicMock()

        self.mgr = ModeManager.instance()

        # Register test modes
        self.mode_primary = MagicMock(name="Primary", order=0)
        self.mode_primary.name = "Primary"
        self.mode_primary.order = 0
        self.mode_secondary = MagicMock(name="Secondary", order=1)
        self.mode_secondary.name = "Secondary"
        self.mode_secondary.order = 1
        self.mode_tertiary = MagicMock(name="Tertiary", order=2)
        self.mode_tertiary.name = "Tertiary"
        self.mode_tertiary.order = 2

        self.mgr.register_modes([self.mode_primary, self.mode_secondary, self.mode_tertiary])

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def test_next_mode_advances_index(self) -> None:
        """Verify _next_mode advances to next mode."""
        self.assertEqual(self.mgr.current_mode_index, 0)
        self.mgr._next_mode()
        self.assertEqual(self.mgr.current_mode_index, 1)
        self.mgr._next_mode()
        self.assertEqual(self.mgr.current_mode_index, 2)

    def test_next_mode_wraps_around(self) -> None:
        """Verify _next_mode wraps to first mode."""
        self.mgr.current_mode_index = 2
        self.mgr._next_mode()
        self.assertEqual(self.mgr.current_mode_index, 0)

    def test_goto_primary_mode_finds_order_zero(self) -> None:
        """Verify _goto_primary_mode jumps to order=0 mode."""
        self.mgr.current_mode_index = 2
        self.mgr._goto_primary_mode()
        self.assertEqual(self.mgr.current_mode_index, 0)

    def test_goto_primary_mode_handles_reordered_list(self) -> None:
        """Verify _goto_primary_mode works when primary is not first in list."""
        # Re-register with primary not at index 0
        mode_a = MagicMock(name="A", order=1)
        mode_a.name = "A"
        mode_a.order = 1
        mode_b = MagicMock(name="B", order=0)
        mode_b.name = "B"
        mode_b.order = 0

        self.mgr.register_modes([mode_a, mode_b])
        # After sorting, B (order=0) should be at index 0
        self.mgr.current_mode_index = 1
        self.mgr._goto_primary_mode()
        self.assertEqual(self.mgr.current_mode_index, 0)


class TestProcessPendingActions(unittest.TestCase):
    """Test action processing from button router."""

    def setUp(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

        self.mock_router = MagicMock()
        self.patches = [
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager"),
            patch("managers.mode_manager.ButtonActionRouterService"),
        ]
        for p in self.patches:
            mock = p.start()
            if hasattr(mock, "instance"):
                mock.instance.return_value = self.mock_router

        self.mgr = ModeManager.instance()
        self.mgr.button_router = self.mock_router

        # Register test modes
        mode = MagicMock(name="Primary", order=0)
        mode.name = "Primary"
        mode.order = 0
        self.mgr.register_modes([mode])

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def test_process_next_action_advances_mode(self) -> None:
        """Verify NEXT action advances to next mode."""
        import asyncio

        from services.button_action_router_service import ButtonAction

        self.mock_router.pop_actions.side_effect = [[ButtonAction.NEXT], []]
        self.mgr.current_mode_index = 0

        # Add a second mode
        mode2 = MagicMock(name="Secondary", order=1)
        mode2.name = "Secondary"
        mode2.order = 1
        self.mgr.modes.append(mode2)

        asyncio.run(self.mgr._process_pending_actions())

        self.assertEqual(self.mgr.current_mode_index, 1)

    def test_process_safe_action_triggers_safe_mode(self) -> None:
        """Verify SAFE action triggers safe mode."""
        import asyncio

        from services.button_action_router_service import ButtonAction

        self.mock_router.pop_actions.side_effect = [[ButtonAction.SAFE], []]

        with patch("managers.mode_manager.trigger_safe_mode") as mock_trigger:
            asyncio.run(self.mgr._process_pending_actions())
            mock_trigger.assert_called_once()

    def test_process_setup_action_runs_setup_mode(self) -> None:
        """Verify SETUP action runs SetupPortalMode."""
        import asyncio

        from services.button_action_router_service import ButtonAction

        self.mock_router.pop_actions.side_effect = [[ButtonAction.SETUP], []]

        with patch("managers.mode_manager.SetupPortalMode") as mock_setup:
            mock_setup.execute = AsyncMock(return_value=True)
            asyncio.run(self.mgr._process_pending_actions())
            mock_setup.execute.assert_called_once()

    def test_process_empty_actions_does_nothing(self) -> None:
        """Verify empty action queue exits cleanly."""
        import asyncio

        self.mock_router.pop_actions.return_value = []

        # Should not raise
        asyncio.run(self.mgr._process_pending_actions())


class TestRunLoop(unittest.TestCase):
    """Test main run loop behavior."""

    def setUp(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

        self.mock_input = MagicMock()
        self.mock_router = MagicMock()
        self.mock_pixel = MagicMock()

        self.patches = [
            patch("managers.mode_manager.PixelController", return_value=self.mock_pixel),
            patch("managers.mode_manager.InputManager"),
            patch("managers.mode_manager.ButtonActionRouterService"),
            patch("managers.mode_manager.Scheduler"),
        ]
        mocks = []
        for p in self.patches:
            mock = p.start()
            mocks.append(mock)

        mocks[1].instance.return_value = self.mock_input
        mocks[2].instance.return_value = self.mock_router

        self.mgr = ModeManager.instance()
        self.mgr.input_mgr = self.mock_input
        self.mgr.button_router = self.mock_router

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def test_run_raises_without_registered_modes(self) -> None:
        """Verify run() raises ValueError if no modes registered."""
        import asyncio

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(self.mgr.run())

        self.assertIn("No modes registered", str(ctx.exception))

    def test_shutdown_is_noop(self) -> None:
        """Verify shutdown() does nothing (ButtonActionRouter owns callbacks)."""
        # Should not raise
        self.mgr.shutdown()


class TestWaitForButtonRelease(unittest.TestCase):
    """Test button release waiting."""

    def setUp(self) -> None:
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

        self.mock_input = MagicMock()
        self.patches = [
            patch("managers.mode_manager.PixelController"),
            patch("managers.mode_manager.InputManager"),
            patch("managers.mode_manager.ButtonActionRouterService"),
        ]
        for p in self.patches:
            mock = p.start()
            if hasattr(mock, "instance"):
                mock.instance.return_value = self.mock_input

        self.mgr = ModeManager.instance()
        self.mgr.input_mgr = self.mock_input

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        from managers.mode_manager import ModeManager

        ModeManager._instance = None

    def test_wait_for_button_release_exits_when_not_pressed(self) -> None:
        """Verify _wait_for_button_release exits immediately if not pressed."""
        import asyncio

        from core.scheduler import Scheduler

        self.mock_input.is_pressed.return_value = False

        with patch.object(Scheduler, "sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(self.mgr._wait_for_button_release())
            mock_sleep.assert_not_called()

    def test_wait_for_button_release_waits_while_pressed(self) -> None:
        """Verify _wait_for_button_release waits while button is pressed."""
        import asyncio

        from core.scheduler import Scheduler

        # Button pressed twice, then released
        self.mock_input.is_pressed.side_effect = [True, True, False]

        with patch.object(Scheduler, "sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(self.mgr._wait_for_button_release())
            self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
