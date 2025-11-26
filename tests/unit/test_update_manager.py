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

    def test_reset_session_clears_session(self) -> None:
        """Test that reset_session clears the cached HTTP session."""
        # Create instance with explicit type
        update_manager: UpdateManager = cast(UpdateManager, UpdateManager.instance())

        # Manually set a session (simulating _get_session having been called)
        update_manager._session = "mock_session_object"

        # Reset session
        update_manager.reset_session()

        # Verify session is cleared
        self.assertIsNone(update_manager._session, "reset_session() should clear _session to None")

    def test_reset_session_is_idempotent(self) -> None:
        """Test that reset_session can be called multiple times safely."""
        update_manager: UpdateManager = cast(UpdateManager, UpdateManager.instance())

        # Reset when session is already None
        update_manager.reset_session()
        self.assertIsNone(update_manager._session)

        # Set a session and reset
        update_manager._session = "mock_session"
        update_manager.reset_session()
        self.assertIsNone(update_manager._session)

        # Reset again when None
        update_manager.reset_session()
        self.assertIsNone(update_manager._session)
