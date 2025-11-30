"""Unit tests for SystemManager."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSystemManagerSingleton(unittest.TestCase):
    """Test SystemManager singleton pattern."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_instance_returns_same_object(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 12345.0

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance1 = SystemManager.instance(update_manager=mock_update_mgr)
            instance2 = SystemManager.instance()
            self.assertIs(instance1, instance2)

    def test_instance_initializes_with_update_manager(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 12345.0

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=100.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            self.assertEqual(instance.update_manager, mock_update_mgr)
            self.assertEqual(instance.boot_time, 100.0)


class TestSystemManagerConfiguration(unittest.TestCase):
    """Test SystemManager configuration loading."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_loads_reboot_interval_from_env(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value="24"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            self.assertEqual(instance.reboot_interval_hours, 24)

    def test_invalid_reboot_interval_defaults_to_zero(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value="invalid"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            self.assertEqual(instance.reboot_interval_hours, 0)

    def test_missing_reboot_interval_defaults_to_zero(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value=None),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            self.assertEqual(instance.reboot_interval_hours, 0)


class TestSystemManagerTick(unittest.TestCase):
    """Test SystemManager tick method."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_tick_calls_check_for_reboot(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0
        mock_update_mgr.should_check_now.return_value = False

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            mock_check_reboot = AsyncMock()
            mock_check_updates = AsyncMock()

            with (
                patch.object(instance, "_check_for_reboot", mock_check_reboot),
                patch.object(instance, "_check_for_updates", mock_check_updates),
            ):
                asyncio.run(instance.tick())

                mock_check_reboot.assert_called_once()
                mock_check_updates.assert_called_once()

    def test_tick_handles_exceptions(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            mock_check_reboot = AsyncMock(side_effect=Exception("test error"))

            with patch.object(instance, "_check_for_reboot", mock_check_reboot):
                asyncio.run(instance.tick())


class TestSystemManagerRebootCheck(unittest.TestCase):
    """Test periodic reboot checking."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_check_for_reboot_skips_when_disabled(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            asyncio.run(instance._check_for_reboot())

    def test_check_for_reboot_triggers_when_interval_reached(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        # Need to provide enough return values for all monotonic() calls
        monotonic_values = [0.0] + [3700.0] * 10

        with (
            patch("os.getenv", return_value="1"),
            patch("time.monotonic", side_effect=monotonic_values),
            patch("core.logging_helper.logger"),
            patch("managers.system_manager.Scheduler.sleep", new=AsyncMock(return_value=None)),
            patch("microcontroller.reset") as mock_reset,
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            asyncio.run(instance._check_for_reboot())
            mock_reset.assert_called_once()


class TestSystemManagerUpdateCheck(unittest.TestCase):
    """Test update checking."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_check_for_updates_skips_when_not_time(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0
        mock_update_mgr.should_check_now.return_value = False

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            asyncio.run(instance._check_for_updates())
            mock_update_mgr.check_download_and_reboot.assert_not_called()

    def test_check_for_updates_calls_update_manager(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0
        mock_update_mgr.should_check_now.return_value = True
        mock_update_mgr.check_download_and_reboot = AsyncMock()

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            asyncio.run(instance._check_for_updates())
            mock_update_mgr.check_download_and_reboot.assert_called_once_with(delay_seconds=1)

    def test_check_for_updates_reschedules_on_error(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 99999.0
        mock_update_mgr.should_check_now.return_value = True
        mock_update_mgr.check_download_and_reboot = AsyncMock(side_effect=Exception("Network error"))

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            asyncio.run(instance._check_for_updates())
            self.assertEqual(mock_update_mgr.schedule_next_update_check.call_count, 2)


class TestSystemManagerShutdown(unittest.TestCase):
    """Test shutdown behavior."""

    def setUp(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def tearDown(self) -> None:
        from managers.system_manager import SystemManager

        SystemManager._instance = None

    def test_shutdown_is_idempotent(self) -> None:
        mock_update_mgr = MagicMock()
        mock_update_mgr.schedule_next_update_check.return_value = 0.0

        with (
            patch("os.getenv", return_value="0"),
            patch("time.monotonic", return_value=0.0),
            patch("core.logging_helper.logger"),
        ):
            from managers.system_manager import SystemManager

            instance = SystemManager.instance(update_manager=mock_update_mgr)
            instance.shutdown()
            instance.shutdown()


if __name__ == "__main__":
    unittest.main()
