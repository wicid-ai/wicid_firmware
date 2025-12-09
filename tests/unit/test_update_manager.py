import os
from unittest.mock import MagicMock, patch

from core.app_typing import cast
from managers.update_manager import UpdateManager
from tests.unit import TestCase


class TestCheckForUpdates(TestCase):
    """Test check_for_updates method."""

    def setUp(self) -> None:
        UpdateManager._instance = None
        self._orig_env = os.environ.get("SYSTEM_UPDATE_MANIFEST_URL")
        self._orig_version = os.environ.get("VERSION")

    def tearDown(self) -> None:
        UpdateManager._instance = None
        if self._orig_env is not None:
            os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = self._orig_env
        elif "SYSTEM_UPDATE_MANIFEST_URL" in os.environ:
            del os.environ["SYSTEM_UPDATE_MANIFEST_URL"]
        if self._orig_version is not None:
            os.environ["VERSION"] = self._orig_version
        elif "VERSION" in os.environ:
            del os.environ["VERSION"]

    def test_returns_none_when_no_manifest_url(self) -> None:
        """Returns None when SYSTEM_UPDATE_MANIFEST_URL is not set."""
        if "SYSTEM_UPDATE_MANIFEST_URL" in os.environ:
            del os.environ["SYSTEM_UPDATE_MANIFEST_URL"]

        manager = cast(UpdateManager, UpdateManager.instance())
        manager.connection_manager = MagicMock()
        result = manager.check_for_updates()
        self.assertIsNone(result)

    def test_returns_none_when_no_releases(self) -> None:
        """Returns None when manifest has no releases."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"releases": []}
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        result = manager.check_for_updates()
        self.assertIsNone(result)

    def test_uses_connection_close_header(self) -> None:
        """Verifies Connection: close header is used."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"releases": []}
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        manager.check_for_updates()

        # Verify headers were used
        self.assertTrue(mock_session.get.called)
        _, kwargs = mock_session.get.call_args
        headers = kwargs.get("headers", {})
        self.assertEqual(headers.get("Connection"), "close")

    def test_no_archive_key_backward_compatible(self) -> None:
        """Releases without archive key work as before (backward compatible)."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["version"], "2.0.0")

    def test_production_eligible_no_archive_search(self) -> None:
        """When production release is eligible, archive is not searched."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.5.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.0.0",
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.8.0",
                            "release_type": "production",
                            "minimum_prior_version": "1.0.0",
                            "release_notes": "Archive",
                            "zip_url": "http://example.com/v1.8.0.zip",
                            "sha256": "def456",
                            "release_date": "2024-12-01T00:00:00Z",
                        }
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["version"], "2.0.0")

    def test_production_not_eligible_falls_back_to_archive(self) -> None:
        """When production not eligible due to MPV, search archive for newest eligible."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Device at 1.0.0, not eligible
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.8.0",
                            "release_type": "production",
                            "minimum_prior_version": "1.5.0",  # Not eligible
                            "release_notes": "Archive 1",
                            "zip_url": "http://example.com/v1.8.0.zip",
                            "sha256": "def456",
                            "release_date": "2024-12-15T00:00:00Z",
                        },
                        {
                            "version": "1.3.0",
                            "release_type": "production",
                            "minimum_prior_version": None,  # Eligible!
                            "release_notes": "Archive 2",
                            "zip_url": "http://example.com/v1.3.0.zip",
                            "sha256": "ghi789",
                            "release_date": "2024-12-01T00:00:00Z",
                        },
                        {
                            "version": "1.2.0",
                            "release_type": "production",
                            "minimum_prior_version": None,  # Also eligible, but older
                            "release_notes": "Archive 3",
                            "zip_url": "http://example.com/v1.2.0.zip",
                            "sha256": "jkl012",
                            "release_date": "2024-11-01T00:00:00Z",
                        },
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            # Should find newest eligible: 1.3.0 (not 1.2.0)
            self.assertEqual(result["version"], "1.3.0")

    def test_archive_search_finds_nothing_eligible(self) -> None:
        """When archive has no eligible releases, returns None."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Not eligible
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.8.0",
                            "release_type": "production",
                            "minimum_prior_version": "1.5.0",  # Not eligible
                            "release_notes": "Archive",
                            "zip_url": "http://example.com/v1.8.0.zip",
                            "sha256": "def456",
                            "release_date": "2024-12-01T00:00:00Z",
                        }
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNone(result)

    def test_empty_archive_array(self) -> None:
        """Empty archive array is handled gracefully."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Not eligible
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNone(result)

    def test_archive_respects_release_type(self) -> None:
        """Archive search only considers releases matching the channel."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Not eligible
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.3.0",
                            "release_type": "development",  # Wrong channel
                            "minimum_prior_version": None,
                            "release_notes": "Dev archive",
                            "zip_url": "http://example.com/v1.3.0.zip",
                            "sha256": "def456",
                            "release_date": "2024-12-01T00:00:00Z",
                        },
                        {
                            "version": "1.2.0",
                            "release_type": "production",  # Correct channel, eligible
                            "minimum_prior_version": None,
                            "release_notes": "Prod archive",
                            "zip_url": "http://example.com/v1.2.0.zip",
                            "sha256": "ghi789",
                            "release_date": "2024-11-01T00:00:00Z",
                        },
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            # Should find production release, not development
            self.assertEqual(result["version"], "1.2.0")

    def test_minimum_prior_version_enforced_during_archive_search(self) -> None:
        """Archive search enforces MPV eligibility."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.0.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Not eligible
                        "release_notes": "Test",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "abc123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.4.0",
                            "release_type": "production",
                            "minimum_prior_version": "1.2.0",  # Eligible: current 1.0.0 < 1.2.0, so not eligible
                            "release_notes": "Archive 1",
                            "zip_url": "http://example.com/v1.4.0.zip",
                            "sha256": "def456",
                            "release_date": "2024-12-01T00:00:00Z",
                        },
                        {
                            "version": "1.3.0",
                            "release_type": "production",
                            "minimum_prior_version": "0.9.0",  # Eligible
                            "release_notes": "Archive 2",
                            "zip_url": "http://example.com/v1.3.0.zip",
                            "sha256": "ghi789",
                            "release_date": "2024-11-01T00:00:00Z",
                        },
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            # Should select the eligible archive with MPV satisfied: 1.3.0
            self.assertEqual(result["version"], "1.3.0")

    def test_dev_mode_archive_search_considers_prod_and_dev(self) -> None:
        """In development mode, archive fallback considers both production and development releases."""
        os.environ["SYSTEM_UPDATE_MANIFEST_URL"] = "http://example.com/manifest.json"
        os.environ["VERSION"] = "1.2.0"

        manager = cast(UpdateManager, UpdateManager.instance())

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": [
                {
                    "target_machine_types": ["test_machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",  # Not eligible
                        "release_notes": "Prod current",
                        "zip_url": "http://example.com/v2.0.0.zip",
                        "sha256": "prodcurrent",
                        "release_date": "2025-01-02T00:00:00Z",
                    },
                    "development": {
                        "version": "1.9.0-b1",
                        "minimum_prior_version": "1.6.0",  # Not eligible
                        "release_notes": "Dev current",
                        "zip_url": "http://example.com/v1.9.0-b1.zip",
                        "sha256": "devcurrent",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "1.5.0",
                            "release_type": "production",
                            "minimum_prior_version": "1.0.0",  # Eligible
                            "release_notes": "Prod archive eligible",
                            "zip_url": "http://example.com/v1.5.0.zip",
                            "sha256": "prodarchive",
                            "release_date": "2024-12-15T00:00:00Z",
                        },
                        {
                            "version": "1.4.0-b1",
                            "release_type": "development",
                            "minimum_prior_version": "1.3.0",  # Eligible but older
                            "release_notes": "Dev archive older",
                            "zip_url": "http://example.com/v1.4.0-b1.zip",
                            "sha256": "devolder",
                            "release_date": "2024-12-01T00:00:00Z",
                        },
                    ],
                }
            ]
        }
        mock_response.close.return_value = None
        mock_session.get.return_value = mock_response

        mock_conn_mgr = MagicMock()
        mock_conn_mgr.get_session.return_value = mock_session
        manager.connection_manager = mock_conn_mgr

        with (
            patch("utils.utils.get_machine_type", return_value="test_machine"),
            patch("utils.utils.get_os_version_string", return_value="circuitpython_10_1_0"),
            patch("utils.utils.is_release_incompatible", return_value=(False, None, 0)),
            patch.object(manager, "_determine_release_channel", return_value="development"),
        ):
            result = manager.check_for_updates()
            self.assertIsNotNone(result)
            assert result is not None
            # Should pick newest eligible across prod+dev archive: 1.5.0 (production) over 1.4.0-b1 (development)
            self.assertEqual(result["version"], "1.5.0")
