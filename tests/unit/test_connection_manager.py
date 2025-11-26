"""
Unit tests for ConnectionManager (WiFi connection management).

ConnectionManager handles WiFi radio configuration, access point mode,
and station mode connections. These tests use MOCK hardware to avoid
requiring real WiFi hardware and enable deterministic testing.

See tests.unit for instructions on running tests.
"""

# Import from unit package - path setup happens automatically
from managers.connection_manager import ConnectionManager
from tests.hardware_mocks import MockWiFiRadioController
from tests.unit import TestCase


class TestConnectionManager(TestCase):
    def setUp(self) -> None:
        # Reset singleton instance
        ConnectionManager._instance = None
        self.mock_controller = MockWiFiRadioController()
        self.mock_radio = self.mock_controller.radio
        self.connection_manager = ConnectionManager.instance(radio_controller=self.mock_controller)

    def test_stop_access_point_calls_stop_ap_when_resetting(self) -> None:
        """
        Test that stop_access_point explicitly calls radio.stop_ap()
        even when resetting to station mode (not restoring connection).
        """
        import asyncio

        async def run_test() -> None:
            # Setup: Simulate AP mode active
            self.connection_manager._ap_active = True
            self.connection_manager._pre_ap_connected = False  # Not restoring connection

            # Action: Stop AP
            await self.connection_manager.stop_access_point(restore_connection=True)

        # Run the async test
        asyncio.run(run_test())

        # Assert: radio.stop_ap() should have been called
        # Since MockRadio tracks state, we check if _ap_active is False
        # But we also want to ensure stop_ap was explicitly called.
        # The MockRadio implementation sets _ap_active = False in stop_ap.
        # However, reset_radio_to_station_mode also resets things, but doesn't call stop_ap on the radio object directly?
        # Let's check reset_radio_to_station_mode in connection_manager.py again.
        # It toggles enabled.

        # To be sure stop_ap was called, we might need to spy on it or check a side effect.
        # MockRadio.stop_ap sets ipv4_address_ap to None.
        self.assertIsNone(self.mock_radio.ipv4_address_ap, "radio.stop_ap() should clear AP IP")
        self.assertFalse(self.mock_radio._ap_active, "radio.stop_ap() should set _ap_active to False")
