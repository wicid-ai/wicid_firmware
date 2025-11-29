"""
Unit tests for UpdateManager (OTA firmware update management).

UpdateManager handles checking for updates, downloading packages, and managing the update process.
These tests verify resource cleanup functionality.

See tests.unit for instructions on running tests.
"""

from core.app_typing import cast

# Import from unit package - path setup happens automatically
from managers.update_manager import UpdateManager
from tests.unit import TestCase


class TestUpdateManagerResourceCleanup(TestCase):
    """Test UpdateManager resource cleanup functionality."""

    def setUp(self) -> None:
        # Reset singleton instance
        UpdateManager._instance = None

    def test_requests_use_connection_close(self) -> None:
        """Verify that HTTP requests include Connection: close header."""
        try:
            from unittest.mock import MagicMock
        except ImportError:
            print("Skipping test_requests_use_connection_close: unittest.mock not available")
            return

        import os

        update_manager = cast(UpdateManager, UpdateManager.instance())

        # Mock connection manager and session
        mock_conn_mgr = MagicMock()
        mock_session = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        update_manager.connection_manager = mock_conn_mgr

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"releases": []}
        mock_session.get.return_value = mock_response

        # Set environment variable for manifest URL
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"

        try:
            update_manager.check_for_updates()

            # Verify headers in get call
            if mock_session.get.called:
                args, kwargs = mock_session.get.call_args
                headers = kwargs.get("headers", {})
                self.assertEqual(headers.get("Connection"), "close", "check_for_updates should use Connection: close")
        finally:
            del os.environ["SYSTEM_UPDATE_MANIFEST_URL"]
