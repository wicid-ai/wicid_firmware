"""
Unit tests for ConfigurationManager.

Tests cover:
- Error message building
- User agent parsing
- Input validation
- Resource cleanup
- State class functionality

Uses mocks from unit_mocks for desktop-only testing.
"""

import asyncio
import json
from unittest.mock import MagicMock, mock_open, patch

from managers.configuration.states import PendingCredentials, PortalState, UpdateState, ValidationState
from managers.configuration_manager import ConfigurationManager
from tests.unit import TestCase


def create_config_manager() -> ConfigurationManager:
    """Create a ConfigurationManager instance with mocked dependencies."""
    ConfigurationManager._instance = None
    with (
        patch("managers.configuration_manager.PixelController"),
        patch("managers.configuration_manager.ConnectionManager"),
    ):
        return ConfigurationManager.instance()


class TestBuildConnectionError(TestCase):
    """Test _build_connection_error error message generation."""

    def setUp(self) -> None:
        """Set up ConfigurationManager for testing."""
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def test_auth_error_maps_to_password_field(self) -> None:
        """Auth errors should suggest password field."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", "Authentication failed")
        self.assertEqual(field, "password")
        self.assertIn("password", message.lower())

    def test_password_error_maps_to_password_field(self) -> None:
        """Password errors should suggest password field."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", "Invalid password")
        self.assertEqual(field, "password")

    def test_not_found_error_maps_to_ssid_field(self) -> None:
        """Network not found should suggest ssid field."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", "Network not found")
        self.assertEqual(field, "ssid")
        self.assertIn("find", message.lower())

    def test_timeout_error_maps_to_password_field(self) -> None:
        """Timeout errors suggest password/signal issue."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", "Connection timeout")
        self.assertEqual(field, "password")
        self.assertIn("timed out", message.lower())

    def test_no_error_returns_generic_message(self) -> None:
        """None error returns generic retry message."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", None)
        self.assertEqual(field, "ssid")
        self.assertIn("try again", message.lower())

    def test_unknown_error_returns_generic_message(self) -> None:
        """Unknown errors return generic message."""
        message, field = self.config_mgr._build_connection_error("MyNetwork", "Some weird error")
        self.assertEqual(field, "ssid")
        self.assertIn("MyNetwork", message)


class TestGetOsFromUserAgent(TestCase):
    """Test _get_os_from_user_agent OS detection."""

    def setUp(self) -> None:
        """Set up ConfigurationManager for testing."""
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def _make_request_with_ua(self, user_agent: str) -> MagicMock:
        """Create a mock request with specified user agent."""
        request = MagicMock()
        request.headers = {"User-Agent": user_agent}
        return request

    def test_android_detection(self) -> None:
        """Detects Android user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (Linux; Android 10)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "android")

    def test_dalvik_detection(self) -> None:
        """Detects Dalvik (Android runtime) user agent."""
        request = self._make_request_with_ua("Dalvik/2.1.0 (Linux; U; Android 10)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "android")

    def test_iphone_detection(self) -> None:
        """Detects iPhone user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "ios")

    def test_ipad_detection(self) -> None:
        """Detects iPad user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (iPad; CPU OS 14_0)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "ios")

    def test_cfnetwork_detection(self) -> None:
        """Detects CFNetwork (iOS system) user agent."""
        request = self._make_request_with_ua("CFNetwork/1220.0")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "ios")

    def test_windows_detection(self) -> None:
        """Detects Windows user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (Windows NT 10.0)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "windows")

    def test_microsoft_ncsi_detection(self) -> None:
        """Detects Microsoft NCSI (connectivity check) user agent."""
        request = self._make_request_with_ua("Microsoft NCSI")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "windows")

    def test_macos_detection(self) -> None:
        """Detects macOS user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "macos")

    def test_darwin_detection(self) -> None:
        """Detects Darwin (macOS kernel) user agent."""
        request = self._make_request_with_ua("Darwin/20.3.0")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "macos")

    def test_linux_detection(self) -> None:
        """Detects Linux (non-Android) user agent."""
        request = self._make_request_with_ua("Mozilla/5.0 (X11; Linux x86_64)")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "linux")

    def test_unknown_user_agent(self) -> None:
        """Unknown user agents return 'unknown'."""
        request = self._make_request_with_ua("SomeRandomBrowser/1.0")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "unknown")

    def test_empty_user_agent(self) -> None:
        """Empty user agent returns 'unknown'."""
        request = self._make_request_with_ua("")
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "unknown")

    def test_missing_headers(self) -> None:
        """Missing headers returns 'unknown'."""
        request = MagicMock()
        request.headers = None
        self.assertEqual(self.config_mgr._get_os_from_user_agent(request), "unknown")


class TestCaptiveRedirectResponse(TestCase):
    """Test captive portal redirect response generation."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def _request(self, user_agent: str) -> MagicMock:
        request = MagicMock()
        request.headers = {"User-Agent": user_agent}
        return request

    def test_ios_returns_html_response(self) -> None:
        """iOS user agents should receive HTML meta refresh."""
        request = self._request("CFNetwork/1220 iPhone")
        with patch("managers.configuration_manager.Response") as mock_response:
            self.config_mgr._create_captive_redirect_response(request, target_url="/setup")

        args, kwargs = mock_response.call_args
        self.assertIn('<meta http-equiv="refresh"', args[1])
        self.assertEqual(kwargs.get("content_type"), "text/html")

    def test_non_ios_returns_302(self) -> None:
        """Other platforms should get HTTP 302 redirect."""
        request = self._request("Mozilla/5.0 (Windows NT 10.0)")
        with patch("managers.configuration_manager.Response") as mock_response:
            self.config_mgr._create_captive_redirect_response(request, target_url="/setup")

        _, kwargs = mock_response.call_args
        self.assertEqual(kwargs.get("status"), (302, "Found"))
        self.assertEqual(kwargs.get("headers"), {"Location": "/setup"})


class TestPendingCredentials(TestCase):
    """Test PendingCredentials state class."""

    def test_initial_state(self) -> None:
        """Credentials start as None."""
        creds = PendingCredentials()
        self.assertIsNone(creds.ssid)
        self.assertIsNone(creds.password)

    def test_set_stores_values(self) -> None:
        """set() stores ssid and password."""
        creds = PendingCredentials()
        creds.set("MyNetwork", "MyPassword123")
        self.assertEqual(creds.ssid, "MyNetwork")
        self.assertEqual(creds.password, "MyPassword123")

    def test_clear_removes_values(self) -> None:
        """clear() resets to None."""
        creds = PendingCredentials()
        creds.set("MyNetwork", "MyPassword123")
        creds.clear()
        self.assertIsNone(creds.ssid)
        self.assertIsNone(creds.password)

    def test_has_credentials_false_when_empty(self) -> None:
        """has_credentials() returns False when empty."""
        creds = PendingCredentials()
        self.assertFalse(creds.has_credentials())

    def test_has_credentials_true_when_set(self) -> None:
        """has_credentials() returns True when set."""
        creds = PendingCredentials()
        creds.set("MyNetwork", "MyPassword123")
        self.assertTrue(creds.has_credentials())

    def test_has_credentials_false_with_partial(self) -> None:
        """has_credentials() returns False with only ssid."""
        creds = PendingCredentials()
        creds.ssid = "MyNetwork"
        self.assertFalse(creds.has_credentials())


class TestValidationState(TestCase):
    """Test ValidationState class."""

    def test_initial_state(self) -> None:
        """ValidationState starts idle."""
        state = ValidationState()
        self.assertEqual(state.state, "idle")
        self.assertIsNone(state.result)
        self.assertIsNone(state.started_at)
        self.assertFalse(state.trigger)
        self.assertIsNone(state.activation_mode)


class TestUpdateState(TestCase):
    """Test UpdateState class."""

    def test_initial_state(self) -> None:
        """UpdateState starts idle."""
        state = UpdateState()
        self.assertEqual(state.state, "idle")
        self.assertFalse(state.trigger)
        self.assertIsNone(state.progress_message)
        self.assertIsNone(state.progress_pct)


class TestPortalState(TestCase):
    """Test PortalState class."""

    def test_initial_state(self) -> None:
        """PortalState starts with defaults."""
        state = PortalState()
        self.assertFalse(state.setup_complete)
        self.assertFalse(state.user_connected)
        self.assertIsNone(state.last_request_time)
        self.assertIsNone(state.pending_ready_at)
        self.assertIsNone(state.last_connection_error)


class TestResourceManagement(TestCase):
    """Test resource management methods."""

    def setUp(self) -> None:
        """Set up ConfigurationManager with mocks."""
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def test_stop_dns_interceptor_when_none(self) -> None:
        """_stop_dns_interceptor handles None gracefully."""
        self.config_mgr.dns_interceptor = None
        self.config_mgr._stop_dns_interceptor()  # Should not raise

    def test_stop_dns_interceptor_calls_stop(self) -> None:
        """_stop_dns_interceptor calls stop() and clears reference."""
        mock_dns = MagicMock()
        self.config_mgr.dns_interceptor = mock_dns

        self.config_mgr._stop_dns_interceptor()

        mock_dns.stop.assert_called_once()
        self.assertIsNone(self.config_mgr.dns_interceptor)

    def test_stop_dns_interceptor_handles_error(self) -> None:
        """_stop_dns_interceptor catches exceptions."""
        mock_dns = MagicMock()
        mock_dns.stop.side_effect = RuntimeError("Stop failed")
        self.config_mgr.dns_interceptor = mock_dns

        self.config_mgr._stop_dns_interceptor()  # Should not raise

        self.assertIsNone(self.config_mgr.dns_interceptor)

    def test_stop_http_server_when_none(self) -> None:
        """_stop_http_server handles None gracefully."""
        self.config_mgr._http_server = None
        self.config_mgr._stop_http_server()  # Should not raise

    def test_stop_http_server_calls_stop(self) -> None:
        """_stop_http_server calls stop() and clears reference."""
        mock_server = MagicMock()
        self.config_mgr._http_server = mock_server

        self.config_mgr._stop_http_server()

        mock_server.stop.assert_called_once()
        self.assertIsNone(self.config_mgr._http_server)

    def test_check_dns_health_when_none(self) -> None:
        """_check_dns_interceptor_health returns False when None."""
        self.config_mgr.dns_interceptor = None
        self.assertFalse(self.config_mgr._check_dns_interceptor_health())

    def test_check_dns_health_returns_status(self) -> None:
        """_check_dns_interceptor_health returns health status."""
        mock_dns = MagicMock()
        mock_dns.get_status.return_value = {"healthy": True}
        self.config_mgr.dns_interceptor = mock_dns

        self.assertTrue(self.config_mgr._check_dns_interceptor_health())

    def test_check_dns_health_handles_exception(self) -> None:
        """_check_dns_interceptor_health returns False on error."""
        mock_dns = MagicMock()
        mock_dns.get_status.side_effect = RuntimeError("Status failed")
        self.config_mgr.dns_interceptor = mock_dns

        self.assertFalse(self.config_mgr._check_dns_interceptor_health())


class TestGetSocketPool(TestCase):
    """Test get_socket_pool method."""

    def setUp(self) -> None:
        """Set up ConfigurationManager with mocks."""
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def test_raises_when_connection_manager_none(self) -> None:
        """get_socket_pool raises when ConnectionManager not set."""
        self.config_mgr.connection_manager = None

        with self.assertRaises(RuntimeError):
            self.config_mgr.get_socket_pool()

    def test_returns_pool_from_connection_manager(self) -> None:
        """get_socket_pool delegates to ConnectionManager."""
        mock_cm = MagicMock()
        mock_pool = MagicMock()
        mock_cm.get_socket_pool.return_value = mock_pool
        self.config_mgr.connection_manager = mock_cm

        result = self.config_mgr.get_socket_pool()

        self.assertIs(result, mock_pool)
        mock_cm.get_socket_pool.assert_called_once()


class TestScanNetworks(TestCase):
    """Test network scanning."""

    def setUp(self) -> None:
        """Set up ConfigurationManager with mocks."""
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def test_returns_empty_when_no_connection_manager(self) -> None:
        """scan_networks returns empty list when no ConnectionManager."""
        self.config_mgr.connection_manager = None
        self.assertEqual(self.config_mgr.scan_networks(), [])

    def test_returns_networks_from_connection_manager(self) -> None:
        """scan_networks returns ConnectionManager results."""
        mock_cm = MagicMock()
        mock_networks = [MagicMock(ssid="Net1"), MagicMock(ssid="Net2")]
        mock_cm.scan_networks.return_value = mock_networks
        self.config_mgr.connection_manager = mock_cm

        result = self.config_mgr.scan_networks()

        self.assertEqual(len(result), 2)


class TestValidateConfigInput(TestCase):
    """Test credential validation helper."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()
        self.request = MagicMock()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def test_empty_ssid_returns_error(self) -> None:
        """Empty SSID returns json error."""
        with patch.object(self.config_mgr, "_json_error", return_value="error") as mock_error:
            result = self.config_mgr._validate_config_input(self.request, "", "password123", "12345")
        self.assertEqual(result, "error")
        mock_error.assert_called_once_with(self.request, self.config_mgr.ERR_EMPTY_SSID, field="ssid")

    def test_invalid_password_length(self) -> None:
        """Passwords outside 8-63 chars return error."""
        with patch.object(self.config_mgr, "_json_error", return_value="pwd_error") as mock_error:
            result = self.config_mgr._validate_config_input(self.request, "ssid", "short", "12345")
        self.assertEqual(result, "pwd_error")
        mock_error.assert_called_once_with(self.request, self.config_mgr.ERR_PWD_LEN, field="password")

    def test_invalid_zip_code(self) -> None:
        """Zip code must be 5 digits."""
        with patch.object(self.config_mgr, "_json_error", return_value="zip_error") as mock_error:
            result = self.config_mgr._validate_config_input(self.request, "ssid", "password123", "12A45")
        self.assertEqual(result, "zip_error")
        mock_error.assert_called_once_with(self.request, self.config_mgr.ERR_INVALID_ZIP, field="zip_code")

    def test_valid_input_returns_none(self) -> None:
        """Valid payload returns None."""
        result = self.config_mgr._validate_config_input(self.request, "ssid", "password123", "12345")
        self.assertIsNone(result)


class TestCleanupSetupPortal(TestCase):
    """Test _cleanup_setup_portal async method."""

    def setUp(self) -> None:
        """Set up ConfigurationManager with mocks."""
        self.config_mgr = create_config_manager()

        # Set up mocks for cleanup
        self.mock_http = MagicMock()
        self.mock_dns = MagicMock()
        self.mock_update = MagicMock()
        self.mock_cm = MagicMock()
        self.mock_pixel = MagicMock()

        self.config_mgr._http_server = self.mock_http
        self.config_mgr.dns_interceptor = self.mock_dns
        self.config_mgr._update_manager = self.mock_update
        self.config_mgr.connection_manager = self.mock_cm
        self.config_mgr.pixel = self.mock_pixel

    def tearDown(self) -> None:
        """Clean up singleton."""
        ConfigurationManager._instance = None

    def test_cleanup_stops_all_services(self) -> None:
        """_cleanup_setup_portal stops HTTP, DNS, and clears pixel."""

        async def run_test() -> None:
            await self.config_mgr._cleanup_setup_portal()

        asyncio.run(run_test())

        self.mock_http.stop.assert_called()
        self.mock_dns.stop.assert_called()
        self.mock_pixel.clear.assert_called()

    def test_cleanup_handles_missing_services(self) -> None:
        """_cleanup_setup_portal handles None services."""
        self.config_mgr._http_server = None
        self.config_mgr.dns_interceptor = None
        self.config_mgr._update_manager = None

        async def run_test() -> None:
            await self.config_mgr._cleanup_setup_portal()

        asyncio.run(run_test())  # Should not raise


class TestJsonHelpers(TestCase):
    """Test JSON response helpers."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()
        self.request = MagicMock()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def test_json_ok_uses_jsonresponse(self) -> None:
        """_json_ok should delegate to JSONResponse."""
        with patch("managers.configuration_manager.JSONResponse") as mock_json_response:
            result = self.config_mgr._json_ok(self.request, {"status": "ok"})
        mock_json_response.assert_called_once()
        self.assertIs(result, mock_json_response.return_value)

    def test_json_error_builds_response(self) -> None:
        """_json_error should construct Response with custom status."""
        with patch("managers.configuration_manager.Response") as mock_response:
            result = self.config_mgr._json_error(self.request, "Bad", field="ssid", code=418, text="I'm a teapot")
        mock_response.assert_called_once()
        args, kwargs = mock_response.call_args
        body = json.loads(args[1])
        self.assertEqual(body["error"]["field"], "ssid")
        self.assertEqual(kwargs.get("status"), (418, "I'm a teapot"))
        self.assertEqual(kwargs.get("content_type"), "application/json")
        self.assertIs(result, mock_response.return_value)


class TestConfigurationLoaders(TestCase):
    """Test helpers that load configuration from disk."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()
        self.config_mgr.logger = MagicMock()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def test_load_saved_configuration_returns_tuple(self) -> None:
        """Helper should return tuple of credentials."""
        secrets = {"ssid": "MyWiFi", "password": "pw12345678", "weather_zip": "12345"}
        with patch("builtins.open", mock_open(read_data="{}")), patch("json.load", return_value=secrets):
            result = self.config_mgr._load_saved_configuration()
        self.assertEqual(result, ("MyWiFi", "pw12345678", "12345"))

    def test_load_saved_configuration_handles_error(self) -> None:
        """Helper should return None and log on error."""
        with patch("builtins.open", side_effect=OSError("missing")):
            result = self.config_mgr._load_saved_configuration()
        self.assertIsNone(result)
        self.config_mgr.logger.info.assert_called()  # type: ignore[attr-defined]

    def test_has_complete_configuration(self) -> None:
        """Static helper validates completeness."""
        self.assertTrue(ConfigurationManager._has_complete_configuration("a", "b", "12345"))
        self.assertFalse(ConfigurationManager._has_complete_configuration("", "b", "12345"))
        self.assertFalse(ConfigurationManager._has_complete_configuration("a", "", "12345"))
        self.assertFalse(ConfigurationManager._has_complete_configuration("a", "b", ""))


class TestSaveCredentials(TestCase):
    """Test credential persistence."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def test_save_credentials_persists_and_caches(self) -> None:
        """Successful save writes file, syncs, and caches credentials."""
        m = mock_open()
        with patch("builtins.open", m), patch("json.dump") as mock_dump, patch("os.sync") as mock_sync:
            success, error = self.config_mgr.save_credentials("ssid", "password123", "12345")
        self.assertTrue(success)
        self.assertIsNone(error)
        mock_dump.assert_called_once()
        mock_sync.assert_called_once()
        self.assertEqual(self.config_mgr.credentials.ssid, "ssid")

    def test_save_credentials_handles_error(self) -> None:
        """Filesystem errors should be reported."""
        with patch("builtins.open", side_effect=OSError("disk full")):
            success, error = self.config_mgr.save_credentials("ssid", "password123", "12345")
        self.assertFalse(success)
        self.assertIn("disk full", error or "")

    def test_save_credentials_clears_connection_manager_cache(self) -> None:
        """
        save_credentials should clear ConnectionManager's credentials cache.

        This ensures that when credentials are updated (e.g., zip code changed),
        ConnectionManager will reload from secrets.json instead of using stale cached values.
        Without this fix, WeatherMode would use the old zip code after setup mode exits.
        """
        # Set up mock ConnectionManager with cached credentials
        mock_cm = MagicMock()
        mock_cm._credentials = {"ssid": "OldNetwork", "password": "oldpass", "weather_zip": "11111"}
        self.config_mgr.connection_manager = mock_cm

        # Save new credentials with different zip code
        m = mock_open()
        with patch("builtins.open", m), patch("json.dump"), patch("os.sync"):
            success, error = self.config_mgr.save_credentials("NewNetwork", "newpass123", "99999")

        # Verify save succeeded
        self.assertTrue(success)
        self.assertIsNone(error)

        # Verify ConnectionManager's cache was cleared
        mock_cm.clear_credentials_cache.assert_called_once()

    def test_save_credentials_handles_missing_connection_manager(self) -> None:
        """save_credentials should handle None connection_manager gracefully."""
        self.config_mgr.connection_manager = None

        m = mock_open()
        with patch("builtins.open", m), patch("json.dump"), patch("os.sync"):
            success, error = self.config_mgr.save_credentials("ssid", "password123", "12345")

        # Should still succeed even without ConnectionManager
        self.assertTrue(success)
        self.assertIsNone(error)


class TestProgressHelpers(TestCase):
    """Test progress normalization and delta logic."""

    def setUp(self) -> None:
        self.config_mgr = create_config_manager()

    def tearDown(self) -> None:
        ConfigurationManager._instance = None

    def test_normalize_progress_bounds(self) -> None:
        """_normalize_progress clamps values and handles invalid input."""
        self.assertEqual(self.config_mgr._normalize_progress(105.7), 100)
        self.assertEqual(self.config_mgr._normalize_progress(-10), 0)
        self.assertIsNone(self.config_mgr._normalize_progress(None))  # type: ignore[arg-type]
        self.assertIsNone(self.config_mgr._normalize_progress("abc"))  # type: ignore[arg-type]

    def test_progress_delta_trigger_determinate(self) -> None:
        """Delta trigger fires on transitions exceeding PROGRESS_STEP_PERCENT."""
        self.config_mgr.update._last_pct_value = 10
        self.assertTrue(self.config_mgr._progress_delta_trigger(15))
        self.config_mgr.update._last_pct_value = 20
        self.assertFalse(self.config_mgr._progress_delta_trigger(21))  # less than step

    def test_progress_delta_trigger_indeterminate(self) -> None:
        """Delta trigger for indeterminate progress compares raw values."""
        self.config_mgr.update._last_pct_value = None
        self.config_mgr.update._last_notify_pct = None
        self.assertFalse(self.config_mgr._progress_delta_trigger(None))  # type: ignore[arg-type]
        self.config_mgr.update._last_notify_pct = "loading"  # type: ignore[assignment]
        self.assertTrue(self.config_mgr._progress_delta_trigger("verifying"))  # type: ignore[arg-type]
