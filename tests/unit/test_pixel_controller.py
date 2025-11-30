import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from controllers.pixel_controller import PixelController
from tests.unit import TestCase


class FakePixel:
    """Minimal NeoPixel replacement for deterministic testing."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, tuple[int, int, int]]] = []
        self.show_call_count = 0
        self.last_value: tuple[int, int, int] | None = None

    def __setitem__(self, idx: int, value: tuple[int, int, int]) -> None:
        self.writes.append((idx, value))
        self.last_value = value

    def show(self) -> None:
        self.show_call_count += 1


class TestPixelController(TestCase):
    def setUp(self) -> None:
        PixelController._instance = None
        PixelController._initialized = False

        self.scheduler_patch = patch("controllers.pixel_controller.Scheduler")
        self.mock_scheduler_cls = self.scheduler_patch.start()
        self.mock_scheduler = MagicMock()
        self.mock_scheduler.schedule_periodic.return_value = MagicMock(name="task-handle")
        self.mock_scheduler_cls.instance.return_value = self.mock_scheduler
        self.scheduler_sleep = AsyncMock()
        self.mock_scheduler_cls.sleep = self.scheduler_sleep

        self.fake_pixel = FakePixel()
        self.neopixel_patch = patch("controllers.pixel_controller.neopixel.NeoPixel", return_value=self.fake_pixel)
        self.mock_neopixel_ctor = self.neopixel_patch.start()

        self.board_patch = patch("controllers.pixel_controller.board")
        self.mock_board = self.board_patch.start()
        self.mock_board.NEOPIXEL = object()

    def tearDown(self) -> None:
        patch.stopall()
        PixelController._instance = None
        PixelController._initialized = False

    def _make_controller(self) -> PixelController:
        return PixelController.instance(pixel=self.fake_pixel)

    def test_instance_initializes_hardware_once(self) -> None:
        first = PixelController.instance()
        second = PixelController.instance()

        self.assertIs(first, second)
        self.mock_neopixel_ctor.assert_called_once_with(self.mock_board.NEOPIXEL, 1, brightness=0.3, auto_write=True)
        self.mock_scheduler_cls.instance.assert_called_once()
        self.mock_scheduler.schedule_periodic.assert_called_once()

    def test_set_color_casts_and_shows(self) -> None:
        controller = self._make_controller()

        controller.set_color((10, 20, 30))

        self.assertEqual(self.fake_pixel.last_value, (10, 20, 30))
        self.assertEqual(self.fake_pixel.show_call_count, 1)

    def test_apply_brightness_clamps_values(self) -> None:
        controller = self._make_controller()

        self.assertEqual(controller._apply_brightness((10, 20, 30), 2.0), (10, 20, 30))
        self.assertEqual(controller._apply_brightness((10, 20, 30), -1.0), (0, 0, 0))

    def test_save_and_restore_state_round_trip(self) -> None:
        controller = self._make_controller()
        controller._start_pulsing(color=(10, 10, 10), min_b=0.2, max_b=0.8, start_brightness=0.5)

        state = controller._save_state()
        controller._mode = controller._MODE_FLASHING
        controller._pulse_color = (1, 1, 1)
        controller._brightness = 0.1

        controller._restore_state(state)

        self.assertEqual(controller._mode, controller._MODE_PULSING)
        self.assertEqual(controller._pulse_color, (10, 10, 10))
        self.assertEqual(controller._brightness, 0.5)
        self.assertEqual(self.fake_pixel.last_value, (5, 5, 5))

    def test_start_flashing_with_custom_colors(self) -> None:
        controller = self._make_controller()

        controller._start_flashing(colors=[(1, 2, 3)], frame_duration=2)

        self.assertEqual(controller._mode, controller._MODE_FLASHING)
        self.assertEqual(controller._flash_colors, [(1, 2, 3)])
        self.assertEqual(controller._frame_counter, 0)
        self.assertEqual(self.fake_pixel.last_value, (1, 2, 3))

    def test_indicate_operation_requires_known_name(self) -> None:
        controller = self._make_controller()

        with self.assertRaises(ValueError):
            controller.indicate_operation("unknown")

    def test_operation_context_restores_state(self) -> None:
        controller = self._make_controller()
        controller._save_state = MagicMock(return_value={"mode": "saved"})  # type: ignore[assignment]
        controller._restore_state = MagicMock()  # type: ignore[assignment]

        async def run_context() -> None:
            async with controller.indicate_operation("setup_mode"):
                self.assertTrue(controller._save_state.called)  # type: ignore[attr-defined]

        asyncio.run(run_context())
        controller._restore_state.assert_called_once_with({"mode": "saved"})  # type: ignore[attr-defined]

    def test_advance_frame_invokes_renderers(self) -> None:
        controller = self._make_controller()

        controller._mode = controller._MODE_PULSING
        with patch.object(controller, "_render_pulse_frame") as pulse:
            controller._advance_frame()
            pulse.assert_called_once()
            self.assertEqual(controller._frame_counter, 1)

        controller._mode = controller._MODE_FLASHING
        controller._frame_counter = 0
        with patch.object(controller, "_render_flash_frame") as flash:
            controller._advance_frame()
            flash.assert_called_once()
            self.assertEqual(controller._frame_counter, 1)

    def test_manual_tick_advances_after_interval(self) -> None:
        controller = self._make_controller()
        with (
            patch.object(controller, "_advance_frame") as advance,
            patch("controllers.pixel_controller.time.monotonic", side_effect=[0.0, 0.02, 0.2]),
        ):
            controller.manual_tick()
            controller.manual_tick()
            controller.manual_tick()
        advance.assert_called_once()

    def test_blink_success_restores_state_and_sleeps(self) -> None:
        controller = self._make_controller()
        controller._save_state = MagicMock(return_value={"mode": "saved"})  # type: ignore[assignment]
        controller._restore_state = MagicMock()  # type: ignore[assignment]

        asyncio.run(controller.blink_success(times=2, restore_previous_state=True))

        self.assertEqual(self.scheduler_sleep.await_count, 4)
        controller._restore_state.assert_called_once_with({"mode": "saved"})  # type: ignore[attr-defined]
        self.assertTrue(any(color == (0, 255, 0) for _, color in self.fake_pixel.writes))

    def test_blink_error_respects_restore_flag(self) -> None:
        controller = self._make_controller()
        controller._save_state = MagicMock(return_value={"mode": "saved"})  # type: ignore[assignment]
        controller._restore_state = MagicMock()  # type: ignore[assignment]

        asyncio.run(controller.blink_error(times=1, restore_previous_state=False))

        self.assertEqual(self.scheduler_sleep.await_count, 2)
        controller._restore_state.assert_not_called()  # type: ignore[attr-defined]
        self.assertTrue(any(color == (255, 0, 0) for _, color in self.fake_pixel.writes))

    def test_flash_blue_green_switches_mode(self) -> None:
        controller = self._make_controller()
        with patch.object(controller, "_indicate_updating") as updater:
            controller._mode = controller._MODE_SOLID
            controller.flash_blue_green(start_time=0.0)
            controller._mode = controller._MODE_FLASHING
            controller.flash_blue_green(start_time=1.0)

        updater.assert_called_once()

    def test_restore_previous_handles_stack_and_empty(self) -> None:
        controller = self._make_controller()
        sentinel_state = {"mode": "sentinel"}
        controller._state_stack = [sentinel_state]  # type: ignore[assignment]

        with patch.object(controller, "_restore_state") as restore:
            controller.restore_previous()
            restore.assert_called_once_with(sentinel_state)

        with patch.object(controller, "clear") as clear:
            controller.restore_previous()
            clear.assert_called_once()
