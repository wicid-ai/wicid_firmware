"""Unit tests for PortalRoutes."""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock adafruit_httpserver before importing portal_routes
mock_httpserver = MagicMock()
sys.modules["adafruit_httpserver"] = mock_httpserver


class TestPortalRoutesConstants(unittest.TestCase):
    """Test PortalRoutes class constants."""

    def test_captive_portal_paths_includes_android(self) -> None:
        """Verify Android captive portal paths are included."""
        from managers.configuration.portal_routes import PortalRoutes

        self.assertIn("/generate_204", PortalRoutes.CAPTIVE_PORTAL_PATHS)
        self.assertIn("/gen_204", PortalRoutes.CAPTIVE_PORTAL_PATHS)

    def test_captive_portal_paths_includes_ios(self) -> None:
        """Verify iOS captive portal paths are included."""
        from managers.configuration.portal_routes import PortalRoutes

        self.assertIn("/hotspot-detect.html", PortalRoutes.CAPTIVE_PORTAL_PATHS)
        self.assertIn("/library/test/success.html", PortalRoutes.CAPTIVE_PORTAL_PATHS)

    def test_captive_portal_paths_includes_windows(self) -> None:
        """Verify Windows captive portal paths are included."""
        from managers.configuration.portal_routes import PortalRoutes

        self.assertIn("/ncsi.txt", PortalRoutes.CAPTIVE_PORTAL_PATHS)
        self.assertIn("/connecttest.txt", PortalRoutes.CAPTIVE_PORTAL_PATHS)


class TestPortalRoutesInit(unittest.TestCase):
    """Test PortalRoutes initialization."""

    def test_init_stores_config_manager(self) -> None:
        """Verify __init__ stores config_manager reference."""
        from managers.configuration.portal_routes import PortalRoutes

        mock_config = MagicMock()
        routes = PortalRoutes(mock_config)
        self.assertIs(routes.config, mock_config)

    def test_init_creates_logger(self) -> None:
        """Verify __init__ creates a logger."""
        from managers.configuration.portal_routes import PortalRoutes

        mock_config = MagicMock()
        routes = PortalRoutes(mock_config)
        self.assertIsNotNone(routes.logger)


class TestMarkUserConnected(unittest.TestCase):
    """Test _mark_user_connected method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = False
        self.mock_config.connection_manager = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_marks_user_connected_first_time(self) -> None:
        """Verify user_connected is set to True on first call."""
        self.routes._mark_user_connected()
        self.assertTrue(self.mock_config.portal.user_connected)

    def test_clears_retry_count_on_first_connection(self) -> None:
        """Verify retry count is cleared on first connection."""
        self.routes._mark_user_connected()
        self.mock_config.connection_manager.clear_retry_count.assert_called_once()

    def test_does_not_clear_retry_count_on_subsequent_calls(self) -> None:
        """Verify retry count is not cleared on subsequent calls."""
        self.mock_config.portal.user_connected = True
        self.routes._mark_user_connected()
        self.mock_config.connection_manager.clear_retry_count.assert_not_called()

    def test_updates_last_request_time(self) -> None:
        """Verify last_request_time is updated."""
        with patch("managers.configuration.portal_routes.time.monotonic", return_value=123.45):
            self.routes._mark_user_connected()
            self.assertEqual(self.mock_config.portal.last_request_time, 123.45)


class TestHandleCaptiveRedirect(unittest.TestCase):
    """Test handle_captive_redirect method."""

    def test_calls_create_captive_redirect_response(self) -> None:
        """Verify handle_captive_redirect delegates to config._create_captive_redirect_response."""
        from managers.configuration.portal_routes import PortalRoutes

        mock_config = MagicMock()
        mock_config.portal.user_connected = True
        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_config._create_captive_redirect_response.return_value = mock_response

        routes = PortalRoutes(mock_config)
        result = routes.handle_captive_redirect(mock_request)

        mock_config._create_captive_redirect_response.assert_called_once_with(mock_request)
        self.assertIs(result, mock_response)


class TestHandleActivate(unittest.TestCase):
    """Test handle_activate method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = True
        self.mock_request = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_rejects_if_validation_not_success(self) -> None:
        """Verify activation is rejected if validation state is not 'success'."""
        self.mock_config.validation.state = "validating_wifi"

        self.routes.handle_activate(self.mock_request)

        self.mock_config._json_error.assert_called_once()
        args = self.mock_config._json_error.call_args
        self.assertIn("validation not complete", args[0][1])

    def test_sets_activation_mode_on_success(self) -> None:
        """Verify activation_mode is set to 'continue' on success."""
        self.mock_config.validation.state = "success"

        with patch("managers.configuration.portal_routes.time.monotonic", return_value=100.0):
            self.routes.handle_activate(self.mock_request)

        self.assertEqual(self.mock_config.validation.activation_mode, "continue")

    def test_sets_pending_ready_at_on_success(self) -> None:
        """Verify pending_ready_at is set on success."""
        self.mock_config.validation.state = "success"

        with patch("managers.configuration.portal_routes.time.monotonic", return_value=100.0):
            self.routes.handle_activate(self.mock_request)

        self.assertEqual(self.mock_config.portal.pending_ready_at, 104.0)


class TestHandleUpdateNow(unittest.TestCase):
    """Test handle_update_now method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = True
        self.mock_request = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_rejects_if_validation_not_success(self) -> None:
        """Verify update is rejected if validation state is not 'success'."""
        self.mock_config.validation.state = "validating_wifi"

        self.routes.handle_update_now(self.mock_request)

        self.mock_config._json_error.assert_called_once()

    def test_rejects_if_no_update_available(self) -> None:
        """Verify update is rejected if no update is available."""
        self.mock_config.validation.state = "success"
        self.mock_config.validation.result = {"update_available": False}

        self.routes.handle_update_now(self.mock_request)

        self.mock_config._json_error.assert_called_once()

    def test_triggers_update_on_success(self) -> None:
        """Verify update is triggered when conditions are met."""
        self.mock_config.validation.state = "success"
        self.mock_config.validation.result = {"update_available": True}

        self.routes.handle_update_now(self.mock_request)

        self.assertEqual(self.mock_config.update.state, "downloading")
        self.assertTrue(self.mock_config.update.trigger)
        self.assertEqual(self.mock_config.validation.activation_mode, "update")


class TestHandleValidationStatus(unittest.TestCase):
    """Test handle_validation_status method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = True
        self.mock_request = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_returns_validating_wifi_message(self) -> None:
        """Verify correct message for validating_wifi state."""
        self.mock_config.validation.state = "validating_wifi"
        self.mock_config.validation.started_at = None

        self.routes.handle_validation_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["state"], "validating_wifi")
        self.assertEqual(call_args["message"], "Testing WiFi credentials...")

    def test_returns_checking_updates_message(self) -> None:
        """Verify correct message for checking_updates state."""
        self.mock_config.validation.state = "checking_updates"
        self.mock_config.validation.started_at = None

        self.routes.handle_validation_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["state"], "checking_updates")
        self.assertEqual(call_args["message"], "Checking for updates...")

    def test_handles_timeout(self) -> None:
        """Verify timeout is detected after 2 minutes."""
        self.mock_config.validation.state = "validating_wifi"
        self.mock_config.validation.started_at = 0

        with patch("managers.configuration.portal_routes.time.monotonic", return_value=121):
            self.routes.handle_validation_status(self.mock_request)

        self.assertEqual(self.mock_config.validation.state, "error")

    def test_returns_success_with_update_info(self) -> None:
        """Verify success state includes update info when available."""
        self.mock_config.validation.state = "success"
        self.mock_config.validation.started_at = None
        self.mock_config.validation.result = {
            "update_available": True,
            "update_info": {"version": "1.2.0"},
        }

        self.routes.handle_validation_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["state"], "success")
        self.assertTrue(call_args["update_available"])
        self.assertEqual(call_args["update_info"]["version"], "1.2.0")


class TestHandleUpdateStatus(unittest.TestCase):
    """Test handle_update_status method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = True
        self.mock_request = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_uses_progress_message_if_available(self) -> None:
        """Verify progress_message is used when available."""
        self.mock_config.update.state = "downloading"
        self.mock_config.update.progress_message = "Downloaded 50%"
        self.mock_config.update.progress_pct = None

        self.routes.handle_update_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["message"], "Downloaded 50%")

    def test_uses_fallback_message_for_downloading(self) -> None:
        """Verify fallback message for downloading state."""
        self.mock_config.update.state = "downloading"
        self.mock_config.update.progress_message = None
        self.mock_config.update.progress_pct = None

        self.routes.handle_update_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["message"], "Downloading update...")

    def test_includes_progress_percentage(self) -> None:
        """Verify progress percentage is included when available."""
        self.mock_config.update.state = "downloading"
        self.mock_config.update.progress_message = None
        self.mock_config.update.progress_pct = 75

        self.routes.handle_update_status(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        self.assertEqual(call_args["progress"], 75)


class TestHandleScan(unittest.TestCase):
    """Test handle_scan method."""

    def setUp(self) -> None:
        from managers.configuration.portal_routes import PortalRoutes

        self.mock_config = MagicMock()
        self.mock_config.portal.user_connected = True
        self.mock_request = MagicMock()
        self.routes = PortalRoutes(self.mock_config)

    def test_returns_error_if_no_connection_manager(self) -> None:
        """Verify error is returned if connection_manager is None."""
        self.mock_config.connection_manager = None

        self.routes.handle_scan(self.mock_request)

        self.mock_config._json_error.assert_called_once()

    def test_returns_sorted_networks(self) -> None:
        """Verify networks are sorted by RSSI (descending)."""
        mock_network1 = MagicMock(ssid="Network1", rssi=-50, channel=6, authmode="WPA2")
        mock_network2 = MagicMock(ssid="Network2", rssi=-30, channel=11, authmode="WPA2")
        mock_network3 = MagicMock(ssid="Network3", rssi=-70, channel=1, authmode="WPA2")

        self.mock_config.connection_manager.scan_networks.return_value = [
            mock_network1,
            mock_network2,
            mock_network3,
        ]

        self.routes.handle_scan(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        networks = call_args["networks"]

        # Should be sorted by RSSI (highest first)
        self.assertEqual(networks[0]["ssid"], "Network2")  # -30
        self.assertEqual(networks[1]["ssid"], "Network1")  # -50
        self.assertEqual(networks[2]["ssid"], "Network3")  # -70

    def test_skips_hidden_networks(self) -> None:
        """Verify networks without SSID are skipped."""
        mock_visible = MagicMock(ssid="Visible", rssi=-50, channel=6, authmode="WPA2")
        mock_hidden = MagicMock(ssid="", rssi=-30, channel=11, authmode="WPA2")

        self.mock_config.connection_manager.scan_networks.return_value = [
            mock_visible,
            mock_hidden,
        ]

        self.routes.handle_scan(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        networks = call_args["networks"]

        self.assertEqual(len(networks), 1)
        self.assertEqual(networks[0]["ssid"], "Visible")

    def test_removes_duplicate_ssids(self) -> None:
        """Verify duplicate SSIDs are removed."""
        mock_network1 = MagicMock(ssid="Network", rssi=-50, channel=6, authmode="WPA2")
        mock_network2 = MagicMock(ssid="Network", rssi=-30, channel=11, authmode="WPA2")

        self.mock_config.connection_manager.scan_networks.return_value = [
            mock_network1,
            mock_network2,
        ]

        self.routes.handle_scan(self.mock_request)

        call_args = self.mock_config._json_ok.call_args[0][1]
        networks = call_args["networks"]

        self.assertEqual(len(networks), 1)


class TestRegisterRoutes(unittest.TestCase):
    """Test register_routes method."""

    def test_registers_all_routes(self) -> None:
        """Verify all routes are registered with the server."""
        from managers.configuration.portal_routes import PortalRoutes

        mock_config = MagicMock()
        mock_server = MagicMock()
        routes = PortalRoutes(mock_config)

        routes.register_routes(mock_server)

        # Verify main routes are registered
        mock_server.route.assert_any_call("/")
        mock_server.route.assert_any_call("/system-info", "GET")
        mock_server.route.assert_any_call("/scan", "GET")
        mock_server.route.assert_any_call("/configure", "POST")
        mock_server.route.assert_any_call("/validation-status", "GET")
        mock_server.route.assert_any_call("/activate", "POST")
        mock_server.route.assert_any_call("/update-now", "POST")
        mock_server.route.assert_any_call("/update-status", "GET")

    def test_registers_captive_portal_paths(self) -> None:
        """Verify all captive portal paths are registered."""
        from managers.configuration.portal_routes import PortalRoutes

        mock_config = MagicMock()
        mock_server = MagicMock()
        routes = PortalRoutes(mock_config)

        routes.register_routes(mock_server)

        for path in PortalRoutes.CAPTIVE_PORTAL_PATHS:
            mock_server.route.assert_any_call(path, "GET")


if __name__ == "__main__":
    unittest.main()
