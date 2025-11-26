"""
Unit tests for ConfigurationManager (Setup Portal & Resource Management).

ConfigurationManager handles the complete lifecycle of the setup portal including:
- Access Point creation
- DNS & HTTP server management
- Resource cleanup

These tests use custom MOCK objects compatible with CircuitPython's limited stdlib.

See tests.unit for instructions on running tests.
"""

import asyncio

# Import from unit package - path setup happens automatically
from core.app_typing import Any, cast
from managers.configuration_manager import ConfigurationManager
from services.dns_interceptor_service import DNSInterceptorService
from tests.hardware_mocks import (
    MockConnectionManager,
    MockDNSInterceptor,
    MockHTTPServer,
    MockPixelController,
    MockUpdateManager,
)
from tests.unit import TestCase


class TestConfigurationManagerResourceCleanup(TestCase):
    """Test resource cleanup functionality - critical for preventing socket leaks."""

    def setUp(self) -> None:
        """Set up test fixtures with mocked dependencies."""
        # Reset singleton
        ConfigurationManager._instance = None

        # Create mocks
        self.mock_connection_manager = MockConnectionManager()
        self.mock_pixel = MockPixelController()
        self.mock_update_manager = MockUpdateManager()
        self.mock_http_server = MockHTTPServer()
        self.mock_dns_interceptor = MockDNSInterceptor()

        # Create instance
        self.config_mgr = ConfigurationManager.instance()

        # Manually inject dependencies with proper types
        self.config_mgr.connection_manager = cast(Any, self.mock_connection_manager)
        self.config_mgr.pixel = self.mock_pixel
        self.config_mgr._update_manager = self.mock_update_manager
        self.config_mgr._http_server = self.mock_http_server
        self.config_mgr.dns_interceptor = cast(DNSInterceptorService, self.mock_dns_interceptor)

    def test_shutdown_cleans_all_resources(self) -> None:
        """Test that _cleanup_setup_portal calls all cleanup methods."""

        async def run_test() -> None:
            await self.config_mgr._cleanup_setup_portal()

        asyncio.run(run_test())

        # Verify all resources were stopped
        self.assertTrue(self.mock_http_server.stop_called, "HTTP server should be stopped")
        self.assertTrue(self.mock_dns_interceptor.stop_called, "DNS interceptor should be stopped")
        self.assertTrue(self.mock_update_manager.reset_session_called, "Update manager session should be reset")
        self.assertTrue(self.mock_connection_manager.stop_access_point_called, "Access point should be stopped")
        self.assertTrue(self.mock_pixel.clear_called, "Pixel should be cleared")

    def test_shutdown_is_idempotent(self) -> None:
        """Test that calling cleanup multiple times is safe."""

        async def run_test() -> None:
            # First call
            await self.config_mgr._cleanup_setup_portal()

            # Simulate resources cleared (servers set to None by _stop methods)
            self.config_mgr._http_server = None
            self.config_mgr.dns_interceptor = None

            # Second call should not raise
            await self.config_mgr._cleanup_setup_portal()

        asyncio.run(run_test())
        # Should succeed without errors - test passes if no exception raised
