"""
Unit tests for modes module.

Tests cover:
- temperature_color function
- blink_for_precip function logic
- Mode classes
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from modes.modes import temperature_color
from tests.unit import TestCase


class TestTemperatureColor(TestCase):
    """Test temperature_color mapping function."""

    def test_none_returns_gray(self) -> None:
        """None temperature returns neutral gray."""
        self.assertEqual(temperature_color(None), (128, 128, 128))

    def test_very_cold_returns_white(self) -> None:
        """Very cold temperatures (0°F or below) return white."""
        self.assertEqual(temperature_color(0), (55, 55, 55))
        self.assertEqual(temperature_color(-10), (55, 55, 55))

    def test_very_hot_returns_red(self) -> None:
        """Very hot temperatures (100°F or above) return red."""
        self.assertEqual(temperature_color(100), (235, 0, 0))
        self.assertEqual(temperature_color(110), (235, 0, 0))

    def test_cold_returns_purple(self) -> None:
        """Cold temperature (15°F) returns purple."""
        self.assertEqual(temperature_color(15), (54, 1, 63))

    def test_cool_returns_blue(self) -> None:
        """Cool temperature (35°F) returns blue."""
        self.assertEqual(temperature_color(35), (0, 0, 220))

    def test_mild_returns_teal(self) -> None:
        """Mild temperature (60°F) returns teal."""
        self.assertEqual(temperature_color(60), (0, 160, 100))

    def test_warm_returns_green(self) -> None:
        """Warm temperature (70°F) returns greenish."""
        self.assertEqual(temperature_color(70), (10, 220, 10))

    def test_hot_returns_orange(self) -> None:
        """Hot temperature (90°F) returns orange."""
        self.assertEqual(temperature_color(90), (255, 60, 0))

    def test_interpolates_between_steps(self) -> None:
        """Temperatures between steps are interpolated."""
        color = temperature_color(52.5)
        self.assertEqual(color[0], 0)
        self.assertGreater(color[1], 100)
        self.assertLess(color[2], 220)

    def test_freezing_point_is_cold(self) -> None:
        """32°F (freezing) returns a cold blue color."""
        color = temperature_color(32)
        self.assertGreater(color[2], color[0])

    def test_room_temperature_is_comfortable(self) -> None:
        """72°F (room temp) returns a comfortable color."""
        color = temperature_color(72)
        self.assertGreater(color[1], 100)


class TestBlinkForPrecip(TestCase):
    """Test blink_for_precip function."""

    def test_none_precip_holds_color(self) -> None:
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, None))

        self.assertTrue(result)
        mock_pixel.set_color.assert_called_with(color)

    def test_zero_precip_no_blinks(self) -> None:
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, 0))

        self.assertTrue(result)
        # Should not call off() for blinks (only holds color)
        mock_pixel.off.assert_not_called()

    def test_precip_clamps_above_100(self) -> None:
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, 150))

        self.assertTrue(result)
        # 150% should clamp to 10 blinks
        self.assertEqual(mock_pixel.off.call_count, 10)

    def test_interrupt_returns_false(self) -> None:
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        def is_pressed() -> bool:
            return True

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, 50, is_pressed))

        self.assertFalse(result)


class TestWeatherModeClass(TestCase):
    """Test WeatherMode class attributes."""

    def test_weather_mode_attributes(self) -> None:
        from modes.modes import WeatherMode

        self.assertEqual(WeatherMode.name, "Weather")
        self.assertTrue(WeatherMode.requires_wifi)
        self.assertEqual(WeatherMode.order, 0)


class TestTempDemoModeClass(TestCase):
    """Test TempDemoMode class attributes."""

    def test_temp_demo_mode_attributes(self) -> None:
        from modes.modes import TempDemoMode

        self.assertEqual(TempDemoMode.name, "TempDemo")
        self.assertFalse(TempDemoMode.requires_wifi)
        self.assertEqual(TempDemoMode.order, 10)


class TestPrecipDemoModeClass(TestCase):
    """Test PrecipDemoMode class attributes."""

    def test_precip_demo_mode_attributes(self) -> None:
        from modes.modes import PrecipDemoMode

        self.assertEqual(PrecipDemoMode.name, "PrecipDemo")
        self.assertFalse(PrecipDemoMode.requires_wifi)
        self.assertEqual(PrecipDemoMode.order, 20)


class TestSetupPortalModeClass(TestCase):
    """Test SetupPortalMode class attributes."""

    def test_setup_portal_mode_attributes(self) -> None:
        from modes.modes import SetupPortalMode

        self.assertEqual(SetupPortalMode.name, "SetupPortal")
        self.assertFalse(SetupPortalMode.requires_wifi)
        self.assertEqual(SetupPortalMode.order, 1000)


class TestWeatherModeInit(TestCase):
    """Test WeatherMode initialization."""

    def test_init_sets_defaults(self) -> None:
        """Verify __init__ sets default values."""
        with (
            patch("modes.mode_interface.ConnectionManager"),
            patch("modes.mode_interface.InputManager"),
            patch("modes.mode_interface.PixelController"),
        ):
            from modes.modes import WeatherMode

            mode = WeatherMode()

            self.assertIsNone(mode.weather)
            self.assertIsNone(mode.system_manager)
            self.assertIsNone(mode.current_temp)
            self.assertIsNone(mode.precip_chance)
            self.assertIsNone(mode._weather_refresh_handle)


class TestWeatherModeCleanup(TestCase):
    """Test WeatherMode cleanup."""

    def test_cleanup_clears_references(self) -> None:
        """Verify cleanup clears weather and system_manager references."""
        with (
            patch("modes.mode_interface.ConnectionManager"),
            patch("modes.mode_interface.InputManager"),
            patch("modes.mode_interface.PixelController"),
            patch("modes.modes.Scheduler"),
        ):
            from modes.modes import WeatherMode

            mode = WeatherMode()
            mode.weather = MagicMock()
            mode.system_manager = MagicMock()
            mode._weather_refresh_handle = MagicMock()

            mode.cleanup()

            self.assertIsNone(mode.weather)
            self.assertIsNone(mode.system_manager)


class TestSetupPortalModeInit(TestCase):
    """Test SetupPortalMode initialization."""

    def test_init_stores_error(self) -> None:
        """Verify __init__ stores error parameter."""
        with (
            patch("modes.modes.ConfigurationManager") as mock_cfg,
            patch("modes.modes.ButtonActionRouterService") as mock_router,
            patch("modes.mode_interface.ConnectionManager"),
            patch("modes.mode_interface.InputManager"),
            patch("modes.mode_interface.PixelController"),
        ):
            mock_cfg.instance.return_value = MagicMock()
            mock_router.instance.return_value = MagicMock()

            from modes.modes import SetupPortalMode

            error = {"message": "Test error"}
            mode = SetupPortalMode(error=error)

            self.assertEqual(mode._error, error)

    def test_initialize_acquires_session(self) -> None:
        """Verify initialize acquires button session."""
        with (
            patch("modes.modes.ConfigurationManager") as mock_cfg,
            patch("modes.modes.ButtonActionRouterService") as mock_router,
            patch("modes.mode_interface.ConnectionManager"),
            patch("modes.mode_interface.InputManager"),
            patch("modes.mode_interface.PixelController"),
        ):
            mock_session = MagicMock()
            mock_router.instance.return_value.acquire_session.return_value = mock_session
            mock_cfg.instance.return_value = MagicMock()

            from modes.modes import SetupPortalMode

            mode = SetupPortalMode()
            result = mode.initialize()

            self.assertTrue(result)
            mock_session.reset.assert_called_once()


class TestSetupPortalModeCleanup(TestCase):
    """Test SetupPortalMode cleanup."""

    def test_cleanup_closes_session(self) -> None:
        """Verify cleanup closes the button session."""
        with (
            patch("modes.modes.ConfigurationManager") as mock_cfg,
            patch("modes.modes.ButtonActionRouterService") as mock_router,
            patch("modes.mode_interface.ConnectionManager"),
            patch("modes.mode_interface.InputManager"),
            patch("modes.mode_interface.PixelController"),
        ):
            mock_session = MagicMock()
            mock_router.instance.return_value.acquire_session.return_value = mock_session
            mock_cfg.instance.return_value = MagicMock()

            from modes.modes import SetupPortalMode

            mode = SetupPortalMode()
            mode.initialize()
            mode.cleanup()

            mock_session.close.assert_called_once()
            self.assertIsNone(mode._session)


class TestBlinkForPrecipEdgeCases(TestCase):
    """Test blink_for_precip edge cases."""

    def test_negative_precip_clamps_to_zero(self) -> None:
        """Verify negative precipitation clamps to zero blinks."""
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, -10))

        self.assertTrue(result)
        mock_pixel.off.assert_not_called()

    def test_interrupt_function_exception_handled(self) -> None:
        """Verify exception in is_pressed_fn is caught."""
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        def bad_is_pressed() -> bool:
            raise RuntimeError("Test error")

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, 10, bad_is_pressed))

        # Should complete normally despite exception
        self.assertTrue(result)

    def test_fifty_percent_gives_five_blinks(self) -> None:
        """Verify 50% precipitation gives 5 blinks."""
        from modes.modes import blink_for_precip

        mock_pixel = MagicMock()
        color = (255, 0, 0)

        with patch("modes.modes.Scheduler.sleep", new=AsyncMock(return_value=None)):
            result = asyncio.run(blink_for_precip(mock_pixel, color, 50))

        self.assertTrue(result)
        self.assertEqual(mock_pixel.off.call_count, 5)
