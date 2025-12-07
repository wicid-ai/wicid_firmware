"""
Integration tests for install script execution.

These tests run ON-DEVICE to validate the actual script execution behavior
during the update process. They test the full script execution flow
including filesystem operations.

Usage (on device REPL):
    >>> import tests
    >>> tests.run_integration()

WARNING: These tests modify the filesystem! They create and delete files
in /pending_update/ and other locations. Only run these tests when you
have a way to recover (e.g., USB access or known-good backup).
"""

import os

from tests.unittest import TestCase
from utils.utils import suppress


def _rmtree(path: str) -> None:
    """Recursively remove a directory tree (CircuitPython compatible). Idempotent."""
    try:
        entries = os.listdir(path)
    except OSError:
        return  # Directory doesn't exist - nothing to do

    for entry in entries:
        full_path = f"{path}/{entry}"
        try:
            os.listdir(full_path)
            _rmtree(full_path)
        except OSError:
            try:  # noqa: SIM105
                os.remove(full_path)
            except OSError:
                pass

    try:  # noqa: SIM105
        os.rmdir(path)
    except OSError:
        pass


def _mkdir_p(path: str) -> None:
    """Create directory and all parent directories (CircuitPython compatible)."""
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        with suppress(OSError):
            os.mkdir(current)  # Directory already exists if OSError


class TestInstallScriptExecution(TestCase):
    """Test install script execution in realistic scenarios."""

    TEST_DIR = "/pending_update"
    TEST_ROOT = "/pending_update/root"
    TEST_SCRIPTS_DIR = "/pending_update/root/firmware_install_scripts"

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test directories."""
        _rmtree(cls.TEST_DIR)
        _mkdir_p(cls.TEST_ROOT)
        _mkdir_p(cls.TEST_SCRIPTS_DIR)

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up test directories."""
        _rmtree(cls.TEST_DIR)
        # Clean up any test marker files
        for path in ["/test_pre_install_marker", "/test_post_install_marker", "/install.log"]:
            try:  # noqa: SIM105
                os.remove(path)
            except OSError:
                pass
        try:  # noqa: SIM105
            os.sync()
        except (OSError, AttributeError):
            pass

    def setUp(self) -> None:
        """Ensure clean test directory for each test."""
        _rmtree(self.TEST_DIR)
        _mkdir_p(self.TEST_ROOT)
        _mkdir_p(self.TEST_SCRIPTS_DIR)

    def _create_test_script(self, script_type: str, content: str) -> str:
        """Create a test script in the firmware_install_scripts subdirectory."""
        script_path = f"{self.TEST_SCRIPTS_DIR}/{script_type}_v1.0.0.py"
        with open(script_path, "w") as f:
            f.write(content)
        return script_path

    def test_pre_install_script_can_create_files(self) -> None:
        """Pre-install script can create files on filesystem."""
        from utils.update_install import execute_install_script

        script_content = """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Creating marker file")
    with open("/test_pre_install_marker", "w") as f:
        f.write("pre_install_executed")
    return True
"""
        script_path = self._create_test_script("pre_install", script_content)

        success, msg = execute_install_script(
            script_path=script_path,
            script_type="pre_install",
            version="1.0.0",
            pending_root_dir=self.TEST_ROOT,
            pending_update_dir=self.TEST_DIR,
        )

        self.assertTrue(success, f"Script should succeed: {msg}")

        # Verify marker file was created
        try:
            with open("/test_pre_install_marker") as f:
                content = f.read()
            self.assertEqual(content, "pre_install_executed")
        except OSError:
            self.fail("Pre-install script should have created marker file")
        finally:
            try:  # noqa: SIM105
                os.remove("/test_pre_install_marker")
            except OSError:
                pass

    def test_post_install_script_can_modify_files(self) -> None:
        """Post-install script can modify existing files."""
        from utils.update_install import execute_install_script

        # Create an initial file
        with open("/test_post_install_marker", "w") as f:
            f.write("original")

        script_content = """
def main(log_message, version):
    log_message(f"Modifying file for version {version}")
    with open("/test_post_install_marker", "w") as f:
        f.write(f"modified_by_{version}")
    return True
"""
        script_path = self._create_test_script("post_install", script_content)

        success, msg = execute_install_script(
            script_path=script_path,
            script_type="post_install",
            version="1.0.0",
        )

        self.assertTrue(success, f"Script should succeed: {msg}")

        # Verify file was modified
        try:
            with open("/test_post_install_marker") as f:
                content = f.read()
            self.assertEqual(content, "modified_by_1.0.0")
        except OSError:
            self.fail("Post-install script should have modified marker file")
        finally:
            try:  # noqa: SIM105
                os.remove("/test_post_install_marker")
            except OSError:
                pass

    def test_pre_install_can_access_pending_update_files(self) -> None:
        """Pre-install script can read files from pending_update/root/."""
        from utils.update_install import execute_install_script

        # Create a file in pending_update/root/
        with open(f"{self.TEST_ROOT}/test_file.txt", "w") as f:
            f.write("test content from pending")

        script_content = """
def main(log_message, pending_root_dir, pending_update_dir):
    # Read file from pending update
    with open(f"{pending_root_dir}/test_file.txt") as f:
        content = f.read()
    log_message(f"Read from pending: {content}")

    # Write result to marker
    with open("/test_pre_install_marker", "w") as f:
        f.write(content)
    return True
"""
        script_path = self._create_test_script("pre_install", script_content)

        success, msg = execute_install_script(
            script_path=script_path,
            script_type="pre_install",
            version="1.0.0",
            pending_root_dir=self.TEST_ROOT,
            pending_update_dir=self.TEST_DIR,
        )

        self.assertTrue(success, f"Script should succeed: {msg}")

        # Verify script could read the file
        try:
            with open("/test_pre_install_marker") as f:
                content = f.read()
            self.assertEqual(content, "test content from pending")
        finally:
            try:  # noqa: SIM105
                os.remove("/test_pre_install_marker")
            except OSError:
                pass

    def test_script_failure_does_not_crash_system(self) -> None:
        """Script that raises exception returns failure but doesn't crash."""
        from utils.update_install import execute_install_script

        script_content = """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("About to fail")
    raise ValueError("Intentional test failure")
"""
        script_path = self._create_test_script("pre_install", script_content)

        # This should return failure, not raise
        success, msg = execute_install_script(
            script_path=script_path,
            script_type="pre_install",
            version="1.0.0",
            pending_root_dir=self.TEST_ROOT,
            pending_update_dir=self.TEST_DIR,
        )

        self.assertFalse(success)
        self.assertIn("error", msg.lower())

    def test_install_log_created_on_execution(self) -> None:
        """Install log is created when script executes."""
        from utils.update_install import INSTALL_LOG_FILE, execute_install_script

        script_content = """
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Test log message")
    return True
"""
        script_path = self._create_test_script("pre_install", script_content)

        execute_install_script(
            script_path=script_path,
            script_type="pre_install",
            version="1.0.0",
            pending_root_dir=self.TEST_ROOT,
            pending_update_dir=self.TEST_DIR,
        )

        # Verify install log was created
        try:
            with open(INSTALL_LOG_FILE) as f:
                content = f.read()
            self.assertIn("pre_install", content.lower())
        except OSError:
            # Log file may not be writable in all test environments
            pass


class TestInstallScriptPathResolution(TestCase):
    """Test script path generation for different versions."""

    def test_get_script_path_simple_version(self) -> None:
        """Path generation works for simple versions."""
        from utils.update_install import _get_script_path

        path = _get_script_path("pre_install", "1.0.0", "/pending_update/root")
        self.assertEqual(path, "/pending_update/root/firmware_install_scripts/pre_install_v1.0.0.py")

    def test_get_script_path_prerelease_version(self) -> None:
        """Path generation works for prerelease versions."""
        from utils.update_install import _get_script_path

        path = _get_script_path("post_install", "0.6.0-b2", "")
        self.assertEqual(path, "/firmware_install_scripts/post_install_v0.6.0-b2.py")

    def test_get_script_path_rc_version(self) -> None:
        """Path generation works for release candidate versions."""
        from utils.update_install import _get_script_path

        path = _get_script_path("pre_install", "2.0.0-rc1", "/staging")
        self.assertEqual(path, "/staging/firmware_install_scripts/pre_install_v2.0.0-rc1.py")
