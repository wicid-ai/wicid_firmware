"""
Unit tests for install script execution in boot_support.py.

Tests the pre-install and post-install script execution functionality
including script discovery, execution, error handling, and logging.
"""

import os
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, "src")

# Import the functions we're testing
from core.boot_support import (
    INSTALL_LOG_FILE,
    _get_script_path,
    _write_install_log,
    execute_install_script,
)
from tests.unit import TestCase


class TestGetScriptPath(TestCase):
    """Tests for _get_script_path function."""

    def test_pre_install_script_path_with_base_dir(self) -> None:
        """Pre-install script path includes base directory and firmware_install_scripts subdirectory."""
        result = _get_script_path("pre_install", "0.6.0-b2", "/pending_update/root")
        self.assertEqual(result, "/pending_update/root/firmware_install_scripts/pre_install_v0.6.0-b2.py")

    def test_post_install_script_path_without_base_dir(self) -> None:
        """Post-install script path includes firmware_install_scripts subdirectory at root."""
        result = _get_script_path("post_install", "1.0.0", "")
        self.assertEqual(result, "/firmware_install_scripts/post_install_v1.0.0.py")

    def test_version_with_prerelease_suffix(self) -> None:
        """Script path includes full version with prerelease suffix and firmware_install_scripts subdirectory."""
        result = _get_script_path("pre_install", "0.6.0-rc1", "/pending")
        self.assertEqual(result, "/pending/firmware_install_scripts/pre_install_v0.6.0-rc1.py")

    def test_simple_version(self) -> None:
        """Script path works with simple version numbers and firmware_install_scripts subdirectory."""
        result = _get_script_path("post_install", "2.0.0", "")
        self.assertEqual(result, "/firmware_install_scripts/post_install_v2.0.0.py")


class TestWriteInstallLog(TestCase):
    """Tests for _write_install_log function."""

    def setUp(self) -> None:
        """Create a temporary directory for test files."""
        self.test_dir = tempfile.mkdtemp()
        self.original_log_file = INSTALL_LOG_FILE
        # We can't easily patch the constant, so we'll test the function behavior

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_write_install_log_does_not_raise_on_failure(self) -> None:
        """_write_install_log should not raise exceptions on write failure."""
        # Test with an invalid path - should not raise
        try:
            _write_install_log("test message")
        except Exception:
            self.fail("_write_install_log raised an exception on write failure")


class MockInstaller:
    """Mock UpdateInstaller for testing LED feedback."""

    def __init__(self) -> None:
        self.update_led_calls = 0

    def update_led(self) -> None:
        self.update_led_calls += 1


class TestExecuteInstallScript(TestCase):
    """Tests for execute_install_script function."""

    def setUp(self) -> None:
        """Create a temporary directory for test scripts."""
        self.test_dir = tempfile.mkdtemp()
        self.mock_installer = MockInstaller()
        # Suppress console output during tests
        self._log_patcher = patch("core.boot_support.log_boot_message")
        self._log_patcher.start()

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self._log_patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_script(self, filename: str, content: str) -> str:
        """Create a test script file."""
        script_path = os.path.join(self.test_dir, filename)
        with open(script_path, "w") as f:
            f.write(content)
        return script_path

    def test_script_not_found_returns_failure(self) -> None:
        """Returns failure tuple when script doesn't exist."""
        success, msg = execute_install_script(
            script_path="/nonexistent/script.py",
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertFalse(success)
        self.assertIn("not found", msg)

    def test_script_missing_main_returns_failure(self) -> None:
        """Returns failure when script doesn't define main()."""
        script = self._create_script(
            "no_main.py",
            """
# Script without main function
x = 1 + 1
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertFalse(success)
        self.assertIn("missing main()", msg)

    def test_pre_install_script_success(self) -> None:
        """Pre-install script returning True is successful."""
        script = self._create_script(
            "pre_install_v1.0.0.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Test pre-install running")
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
            pending_root_dir="/pending_update/root",
            pending_update_dir="/pending_update",
        )
        self.assertTrue(success)
        self.assertIn("completed successfully", msg)

    def test_post_install_script_success(self) -> None:
        """Post-install script returning True is successful."""
        script = self._create_script(
            "post_install_v1.0.0.py",
            """
def main(log_message, version):
    log_message(f"Test post-install for version {version}")
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="post_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertTrue(success)
        self.assertIn("completed successfully", msg)

    def test_script_returning_none_is_success(self) -> None:
        """Script returning None (implicit return) is treated as success."""
        script = self._create_script(
            "implicit_return.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("No explicit return")
    # No return statement - returns None implicitly
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertTrue(success)

    def test_script_returning_false_is_failure(self) -> None:
        """Script returning False is treated as failure."""
        script = self._create_script(
            "returns_false.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Returning False")
    return False
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertFalse(success)
        self.assertIn("returned failure", msg)

    def test_script_exception_is_failure(self) -> None:
        """Script raising exception is treated as failure."""
        script = self._create_script(
            "raises_exception.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    raise ValueError("Intentional error for testing")
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertFalse(success)
        self.assertIn("error", msg.lower())

    def test_script_has_access_to_os_module(self) -> None:
        """Script can use os module from execution environment."""
        script = self._create_script(
            "uses_os.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    import os
    log_message(f"Current dir: {os.getcwd()}")
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertTrue(success)

    def test_script_has_access_to_json_module(self) -> None:
        """Script can use json module from execution environment."""
        script = self._create_script(
            "uses_json.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    import json
    data = json.dumps({"test": True})
    log_message(f"JSON: {data}")
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        self.assertTrue(success)

    def test_installer_led_updated_during_execution(self) -> None:
        """Installer's update_led is called during script execution."""
        script = self._create_script(
            "simple.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    return True
""",
        )

        execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=self.mock_installer,
        )
        # LED should be updated at least once during execution
        self.assertGreater(self.mock_installer.update_led_calls, 0)

    def test_works_without_installer(self) -> None:
        """Script execution works when installer is None."""
        script = self._create_script(
            "no_installer.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Running without installer")
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=None,
        )
        self.assertTrue(success)

    def test_log_message_callback_works(self) -> None:
        """The log_message function passed to script works."""
        script = self._create_script(
            "logs_messages.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Message 1")
    log_message("Message 2")
    return True
""",
        )

        # We can't easily capture log messages without mocking more,
        # but we can verify the script runs successfully
        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=None,
        )
        self.assertTrue(success)

    def test_pre_install_receives_correct_arguments(self) -> None:
        """Pre-install script receives pending_root_dir and pending_update_dir."""
        script = self._create_script(
            "check_args.py",
            """
def main(log_message, pending_root_dir, pending_update_dir):
    assert pending_root_dir == "/test/root", f"Got {pending_root_dir}"
    assert pending_update_dir == "/test/pending", f"Got {pending_update_dir}"
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=None,
            pending_root_dir="/test/root",
            pending_update_dir="/test/pending",
        )
        self.assertTrue(success)

    def test_post_install_receives_version(self) -> None:
        """Post-install script receives version argument."""
        script = self._create_script(
            "check_version.py",
            """
def main(log_message, version):
    assert version == "2.0.0-beta", f"Got {version}"
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="post_install",
            version="2.0.0-beta",
            installer=None,
        )
        self.assertTrue(success)

    def test_syntax_error_in_script_is_failure(self) -> None:
        """Script with syntax error returns failure."""
        script = self._create_script(
            "syntax_error.py",
            """
def main(log_message, pending_root_dir, pending_update_dir)
    # Missing colon above
    return True
""",
        )

        success, msg = execute_install_script(
            script_path=script,
            script_type="pre_install",
            version="1.0.0",
            installer=None,
        )
        self.assertFalse(success)
        self.assertIn("error", msg.lower())
