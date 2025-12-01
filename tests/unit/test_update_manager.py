"""
Unit tests for UpdateManager (OTA firmware update management).

UpdateManager handles checking for updates, downloading packages, and managing the update process.
These tests verify core functionality including disk space checking, release channels,
scheduling, and HTTP header building.

See tests.unit for instructions on running tests.
"""

import asyncio
import os
import tempfile
from _hashlib import openssl_sha256
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

from core.app_typing import Any, cast
from managers.update_manager import UpdateManager
from tests.unit import TestCase


def run_async(coro: Any) -> Any:
    """Helper to run async coroutines inside synchronous tests."""
    return asyncio.run(coro)


_REAL_SHA256 = openssl_sha256


class TestUpdateManagerSingleton(TestCase):
    """Test UpdateManager singleton behavior."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_instance_returns_same_object(self) -> None:
        """Multiple calls to instance() return the same object."""
        instance1 = UpdateManager.instance()
        instance2 = UpdateManager.instance()
        self.assertIs(instance1, instance2)

    def test_instance_creates_manager(self) -> None:
        """instance() creates a valid UpdateManager."""
        instance = UpdateManager.instance()
        self.assertIsInstance(instance, UpdateManager)


class TestBuildRequestHeaders(TestCase):
    """Test _build_request_headers method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_headers_include_connection_close(self) -> None:
        """Headers always include Connection: close."""
        manager = cast(UpdateManager, UpdateManager.instance())
        headers = manager._build_request_headers()
        self.assertEqual(headers.get("Connection"), "close")

    def test_headers_without_user_agent(self) -> None:
        """Headers without user_agent only have Connection."""
        manager = cast(UpdateManager, UpdateManager.instance())
        headers = manager._build_request_headers()
        self.assertEqual(len(headers), 1)
        self.assertNotIn("User-Agent", headers)

    def test_headers_with_user_agent(self) -> None:
        """Headers with user_agent include both fields."""
        manager = cast(UpdateManager, UpdateManager.instance())
        headers = manager._build_request_headers(user_agent="TestAgent/1.0")
        self.assertEqual(headers.get("Connection"), "close")
        self.assertEqual(headers.get("User-Agent"), "TestAgent/1.0")
        self.assertEqual(len(headers), 2)

    def test_headers_with_empty_user_agent(self) -> None:
        """Empty string user_agent is not included."""
        manager = cast(UpdateManager, UpdateManager.instance())
        headers = manager._build_request_headers(user_agent="")
        self.assertEqual(len(headers), 1)
        self.assertNotIn("User-Agent", headers)


class TestCheckDiskSpace(TestCase):
    """Test check_disk_space static method."""

    def test_sufficient_space_returns_true(self) -> None:
        """Returns True when free space exceeds required."""
        # Mock statvfs to return plenty of space
        mock_stat = (4096, 0, 0, 1000, 0, 0, 0, 0, 0, 0)  # f_bsize=4096, f_bavail=1000
        with patch("os.statvfs", return_value=mock_stat):
            result, message = UpdateManager.check_disk_space(1024)
            self.assertTrue(result)
            self.assertIn("Sufficient space", message)

    def test_insufficient_space_returns_false(self) -> None:
        """Returns False when free space is less than required."""
        # Mock statvfs to return limited space (4096 * 10 = 40960 bytes)
        mock_stat = (4096, 0, 0, 10, 0, 0, 0, 0, 0, 0)
        with patch("os.statvfs", return_value=mock_stat):
            result, message = UpdateManager.check_disk_space(100000)
            self.assertFalse(result)
            self.assertIn("Insufficient space", message)

    def test_statvfs_error_returns_false(self) -> None:
        """Returns False when statvfs raises an exception."""
        with patch("os.statvfs", side_effect=OSError("Disk error")):
            result, message = UpdateManager.check_disk_space(1024)
            self.assertFalse(result)
            self.assertIn("Could not check disk space", message)

    def test_exact_space_match_returns_true(self) -> None:
        """Returns True when free space equals required."""
        # 4096 * 25 = 102400 bytes
        mock_stat = (4096, 0, 0, 25, 0, 0, 0, 0, 0, 0)
        with patch("os.statvfs", return_value=mock_stat):
            result, message = UpdateManager.check_disk_space(102400)
            self.assertTrue(result)


class TestDetermineReleaseChannel(TestCase):
    """Test _determine_release_channel method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_development_channel_when_file_exists(self) -> None:
        """Returns 'development' when /DEVELOPMENT file exists."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch("builtins.open", mock_open(read_data="")):
            channel = manager._determine_release_channel()
            self.assertEqual(channel, "development")

    def test_production_channel_when_file_missing(self) -> None:
        """Returns 'production' when /DEVELOPMENT file doesn't exist."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch("builtins.open", side_effect=OSError("File not found")):
            channel = manager._determine_release_channel()
            self.assertEqual(channel, "production")


class TestShouldCheckNow(TestCase):
    """Test should_check_now method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_returns_false_when_no_check_scheduled(self) -> None:
        """Returns False when next_update_check is None."""
        manager = cast(UpdateManager, UpdateManager.instance())
        manager.next_update_check = None
        self.assertFalse(manager.should_check_now())

    def test_returns_true_when_time_has_passed(self) -> None:
        """Returns True when current time >= scheduled time."""
        manager = cast(UpdateManager, UpdateManager.instance())
        manager.next_update_check = 100.0
        with patch("time.monotonic", return_value=150.0):
            self.assertTrue(manager.should_check_now())

    def test_returns_false_when_time_not_reached(self) -> None:
        """Returns False when current time < scheduled time."""
        manager = cast(UpdateManager, UpdateManager.instance())
        manager.next_update_check = 200.0
        with patch("time.monotonic", return_value=100.0):
            self.assertFalse(manager.should_check_now())

    def test_returns_true_at_exact_time(self) -> None:
        """Returns True when current time equals scheduled time."""
        manager = cast(UpdateManager, UpdateManager.instance())
        manager.next_update_check = 100.0
        with patch("time.monotonic", return_value=100.0):
            self.assertTrue(manager.should_check_now())


class TestScheduleNextUpdateCheck(TestCase):
    """Test schedule_next_update_check method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_schedules_in_hours(self) -> None:
        """Schedules check at correct time based on hours."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch("time.monotonic", return_value=1000.0):
            result = manager.schedule_next_update_check(interval_hours=2)
            # 2 hours = 7200 seconds
            self.assertEqual(result, 1000.0 + 7200)

    def test_returns_correct_timestamp(self) -> None:
        """Returns the correct timestamp for the scheduled check."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch("time.monotonic", return_value=500.0):
            result = manager.schedule_next_update_check(interval_hours=1)
            self.assertEqual(result, 500.0 + 3600)

    def test_fractional_hours(self) -> None:
        """Handles fractional hours correctly."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch("time.monotonic", return_value=0.0):
            result = manager.schedule_next_update_check(interval_hours=0.5)
            # 0.5 hours = 1800 seconds
            self.assertEqual(result, 1800.0)


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


class TestCleanupPendingRoot(TestCase):
    """Test _cleanup_pending_root method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_removes_file_if_exists(self) -> None:
        """Removes pending_update/root if it's a file."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("os.remove") as mock_remove:
            mock_remove.return_value = None  # Success
            manager._cleanup_pending_root()
            mock_remove.assert_called_once()

    def test_handles_directory_case(self) -> None:
        """Handles case where pending_update/root is a directory."""
        manager = cast(UpdateManager, UpdateManager.instance())

        # os.remove fails (it's a directory), listdir succeeds
        with patch("os.remove", side_effect=OSError("Is a directory")), patch("os.listdir", return_value=[]):
            manager._cleanup_pending_root()
            # Should not raise

    def test_handles_missing_directory(self) -> None:
        """Handles case where directory doesn't exist."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("os.remove", side_effect=OSError("Not found")), patch(
            "os.listdir", side_effect=OSError("Not found")
        ):
            manager._cleanup_pending_root()
            # Should not raise


class TestRecordFailedUpdate(TestCase):
    """Test _record_failed_update method."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_writes_failure_record(self) -> None:
        """Writes failure record to file."""
        manager = cast(UpdateManager, UpdateManager.instance())

        m = mock_open()
        with patch("builtins.open", m):
            manager._record_failed_update("Download failed", version="2.0.0")
            m.assert_called()

    def test_handles_write_error(self) -> None:
        """Handles error when writing failure record."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("builtins.open", side_effect=OSError("Disk full")):
            # Should not raise
            manager._record_failed_update("Download failed")


class TestUpdateManagerInit(TestCase):
    """Test UpdateManager initialization."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_init_sets_default_values(self) -> None:
        """Initialization sets expected default values."""
        manager = cast(UpdateManager, UpdateManager.instance())
        self.assertIsNone(manager.next_update_check)
        self.assertIsNone(manager._cached_update_info)

    def test_has_logger(self) -> None:
        """Manager has a logger."""
        manager = cast(UpdateManager, UpdateManager.instance())
        self.assertIsNotNone(manager.logger)

    def test_has_constants(self) -> None:
        """Manager has required constants."""
        self.assertTrue(hasattr(UpdateManager, "PENDING_UPDATE_DIR"))
        self.assertTrue(hasattr(UpdateManager, "PENDING_ROOT_DIR"))


class TestCalculateSha256(TestCase):
    """Test calculate_sha256 helper."""

    def setUp(self) -> None:
        UpdateManager._instance = None
        self.manager = cast(UpdateManager, UpdateManager.instance())
        self.manager.pixel_controller = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_calculates_checksum_and_updates_progress(self) -> None:
        """calculate_sha256 returns expected digest and invokes callbacks."""
        data = b"hello world" * 2
        expected_digest = _REAL_SHA256(data).hexdigest()

        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            tmp.write(data)
            tmp.close()

            progress_calls: list[tuple[str, str, float | None]] = []
            service_calls: list[str] = []

            def progress(state: str, msg: str, pct: float | None) -> None:
                progress_calls.append((state, msg, pct))

            def service() -> None:
                service_calls.append("tick")

            with patch(
                "managers.update_manager.Scheduler.yield_control", new=AsyncMock(return_value=None)
            ) as mock_yield, patch("hashlib.sha256", openssl_sha256), patch(
                "managers.update_manager.hashlib.sha256", openssl_sha256
            ):
                digest = run_async(
                    self.manager.calculate_sha256(
                        tmp.name, chunk_size=4, progress_callback=progress, service_callback=service
                    )
                )

            self.assertEqual(digest, expected_digest)
            self.assertGreater(len(progress_calls), 0)
            self.assertGreater(len(service_calls), 0)
            mock_yield.assert_awaited()
        finally:
            Path(tmp.name).unlink(missing_ok=True)  # type: ignore[arg-type]


class TestVerifyChecksum(TestCase):
    """Test verify_checksum async helper."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_requires_expected_checksum(self) -> None:
        """Returns failure when expected checksum missing."""
        manager = cast(UpdateManager, UpdateManager.instance())
        success, message = run_async(manager.verify_checksum("file.bin", ""))
        self.assertFalse(success)
        self.assertIn("No checksum provided", message)

    def test_handles_calculate_failure(self) -> None:
        """Propagates failure when calculate_sha256 returns None."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch.object(manager, "calculate_sha256", new=AsyncMock(return_value=None)):
            success, message = run_async(manager.verify_checksum("file.bin", "abcd"))
        self.assertFalse(success)
        self.assertIn("Failed to calculate checksum", message)

    def test_returns_success_when_match(self) -> None:
        """Returns success when checksums match (case-insensitive)."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch.object(manager, "calculate_sha256", new=AsyncMock(return_value="ABCDEF")):
            success, message = run_async(manager.verify_checksum("file.bin", "abcdef"))
        self.assertTrue(success)
        self.assertIn("Checksum verified", message)

    def test_returns_failure_when_mismatch(self) -> None:
        """Returns failure when checksums differ."""
        manager = cast(UpdateManager, UpdateManager.instance())
        with patch.object(manager, "calculate_sha256", new=AsyncMock(return_value="1111")):
            success, message = run_async(manager.verify_checksum("file.bin", "2222"))
        self.assertFalse(success)
        self.assertIn("Checksum mismatch", message)


class TestCleanupPendingUpdate(TestCase):
    """Test _cleanup_pending_update method for full staging directory cleanup."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_cleans_entire_pending_update_directory(self) -> None:
        """Removes the entire /pending_update directory tree."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("os.listdir", return_value=["root", ".staging", "update.zip"]), patch(
            "os.remove"
        ) as mock_remove, patch("os.rmdir") as mock_rmdir:
            manager._cleanup_pending_update()
            # Should attempt to remove files and directories
            self.assertTrue(mock_remove.called or mock_rmdir.called)

    def test_handles_missing_directory(self) -> None:
        """Handles case where /pending_update doesn't exist."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("os.listdir", side_effect=OSError("Not found")):
            # Should not raise
            manager._cleanup_pending_update()

    def test_removes_staging_directory_on_failure(self) -> None:
        """Ensures .staging directory is removed during cleanup."""
        manager = cast(UpdateManager, UpdateManager.instance())

        # Simulate .staging exists
        def listdir_side_effect(path: str) -> list[str]:
            if path == UpdateManager.PENDING_UPDATE_DIR:
                return [".staging", "root"]
            return []

        with patch("os.listdir", side_effect=listdir_side_effect), patch("os.remove"), patch("os.rmdir") as mock_rmdir:
            manager._cleanup_pending_update()
            # Should attempt cleanup
            self.assertTrue(mock_rmdir.called)


class TestWriteReadyMarker(TestCase):
    """Test _write_ready_marker method for atomic staging verification."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_writes_marker_with_manifest_hash(self) -> None:
        """Writes .ready marker containing manifest hash."""
        manager = cast(UpdateManager, UpdateManager.instance())

        m = mock_open()
        with patch("builtins.open", m), patch("os.sync"):
            manager._write_ready_marker("abc123def456")
            m.assert_called()
            # Verify we wrote to the .ready file
            write_calls = [call for call in m.mock_calls if "write" in str(call)]
            self.assertTrue(len(write_calls) > 0)

    def test_marker_file_location(self) -> None:
        """Marker file is written to /pending_update/.ready."""
        manager = cast(UpdateManager, UpdateManager.instance())

        m = mock_open()
        with patch("builtins.open", m), patch("os.sync"):
            manager._write_ready_marker("abc123")
            # Check the file path
            open_call = m.call_args_list[0]
            self.assertIn(".ready", str(open_call))


class TestValidateReadyMarker(TestCase):
    """Test _validate_ready_marker method for boot-time verification."""

    def setUp(self) -> None:
        UpdateManager._instance = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_returns_true_when_marker_matches(self) -> None:
        """Returns True when .ready marker hash matches manifest."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("builtins.open", mock_open(read_data="abc123")):
            result = manager._validate_ready_marker("abc123")
            self.assertTrue(result)

    def test_returns_false_when_marker_missing(self) -> None:
        """Returns False when .ready marker doesn't exist."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("builtins.open", side_effect=OSError("File not found")):
            result = manager._validate_ready_marker("abc123")
            self.assertFalse(result)

    def test_returns_false_when_hash_mismatch(self) -> None:
        """Returns False when marker hash doesn't match expected."""
        manager = cast(UpdateManager, UpdateManager.instance())

        with patch("builtins.open", mock_open(read_data="different_hash")):
            result = manager._validate_ready_marker("abc123")
            self.assertFalse(result)


class TestAtomicStaging(TestCase):
    """Test atomic staging workflow with .staging directory."""

    def setUp(self) -> None:
        UpdateManager._instance = None
        self.manager = cast(UpdateManager, UpdateManager.instance())
        self.manager.pixel_controller = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_extracts_to_staging_first(self) -> None:
        """Files are extracted to .staging before being moved to root."""
        # This test verifies the staging directory pattern is used
        self.assertEqual(UpdateManager.PENDING_STAGING_DIR, "/pending_update/.staging")

    def test_staging_renamed_to_root_on_success(self) -> None:
        """On successful extraction, .staging is renamed to root."""
        # Verify the constant exists for the rename target
        self.assertEqual(UpdateManager.PENDING_ROOT_DIR, "/pending_update/root")


class TestCheckDownloadAndReboot(TestCase):
    """Test high-level check_download_and_reboot workflow."""

    def setUp(self) -> None:
        UpdateManager._instance = None
        self.manager = cast(UpdateManager, UpdateManager.instance())
        self.manager.pixel_controller = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_no_update_skips_download(self) -> None:
        """When no update is available, download_update is not called."""
        with patch.object(self.manager, "check_for_updates", return_value=None) as mock_check, patch.object(
            self.manager, "download_update", new=AsyncMock()
        ) as mock_download:
            run_async(self.manager.check_download_and_reboot())

        mock_check.assert_called_once()
        mock_download.assert_not_called()

    def test_successful_download_triggers_reset(self) -> None:
        """Successful download waits then resets the microcontroller."""
        update_info = {"version": "2.0.0", "zip_url": "http://example.com/update.zip"}
        with patch.object(self.manager, "check_for_updates", return_value=update_info), patch.object(
            self.manager, "download_update", new=AsyncMock(return_value=True)
        ) as mock_download, patch(
            "managers.update_manager.Scheduler.sleep", new=AsyncMock(return_value=None)
        ) as mock_sleep, patch("managers.update_manager.microcontroller.reset") as mock_reset:
            run_async(self.manager.check_download_and_reboot(delay_seconds=3))

        mock_download.assert_awaited_once()
        mock_sleep.assert_awaited_once_with(3)
        mock_reset.assert_called_once()


class TestDownloadUpdate(TestCase):
    """Test download_update cooperative workflow."""

    def setUp(self) -> None:
        UpdateManager._instance = None
        self.manager = cast(UpdateManager, UpdateManager.instance())
        self.manager.pixel_controller = None

    def tearDown(self) -> None:
        UpdateManager._instance = None

    def test_requires_cached_info_when_no_params(self) -> None:
        """Raises ValueError when no cached info and zip_url omitted."""
        self.manager._cached_update_info = None
        with self.assertRaises(ValueError):
            run_async(self.manager.download_update())

    def test_disk_space_failure_records_and_cleans(self) -> None:
        """Disk space failure should trigger cleanup and recorded failure."""
        fake_session = MagicMock()
        with patch.object(self.manager, "_get_session", return_value=fake_session), patch.object(
            self.manager, "check_disk_space", return_value=(False, "No space")
        ), patch.object(self.manager, "_cleanup_pending_update") as mock_cleanup, patch.object(
            self.manager, "_record_failed_update"
        ) as mock_record:
            success, message = run_async(self.manager.download_update(zip_url="http://example.com/update.zip"))

        self.assertFalse(success)
        self.assertEqual(message, "Insufficient disk space for update")
        self.assertGreaterEqual(mock_cleanup.call_count, 1)
        mock_record.assert_called_once_with("Insufficient disk space")

    def test_checksum_failure_triggers_cleanup(self) -> None:
        """Checksum mismatch should delete zip, cleanup, and record failure."""
        session = MagicMock()
        head_response = MagicMock()
        head_response.headers = {"Content-Length": "6"}
        get_response = MagicMock()
        get_response.headers = {"Content-Length": "6"}
        get_response.iter_content.return_value = [b"abc", b"def"]
        session.head.return_value = head_response
        session.get.return_value = get_response

        verify_mock = AsyncMock(return_value=(False, "Checksum mismatch"))

        with patch.object(self.manager, "_get_session", return_value=session), patch.object(
            self.manager, "check_disk_space", return_value=(True, "ok")
        ), patch.object(self.manager, "_cleanup_pending_update") as mock_cleanup, patch.object(
            self.manager, "_record_failed_update"
        ) as mock_record, patch("builtins.open", mock_open()), patch("os.mkdir"), patch("os.sync"), patch(
            "os.remove"
        ), patch("time.monotonic", return_value=0.0), patch.object(
            self.manager, "verify_checksum", new=verify_mock
        ), patch("core.scheduler.Scheduler.yield_control", new=AsyncMock(return_value=None)):
            success, message = run_async(
                self.manager.download_update(zip_url="http://example.com/update.zip", expected_checksum="deadbeef")
            )

        self.assertFalse(success)
        self.assertIn("Checksum mismatch", message)
        verify_mock.assert_awaited()
        # Cleanup is called at least once (on checksum failure)
        self.assertGreaterEqual(mock_cleanup.call_count, 1)
        mock_record.assert_called()
        self.assertIn("Checksum mismatch", mock_record.call_args[0][0])
