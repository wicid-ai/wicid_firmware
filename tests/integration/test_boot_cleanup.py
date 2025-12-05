"""
Integration tests for boot.py cleanup operations.

These tests run ON-DEVICE to validate filesystem cleanup behavior,
including handling of hidden files, nested directories, and FAT quirks.

Usage (on device REPL):
    >>> import tests
    >>> tests.run_integration()

WARNING: These tests modify the filesystem! They create and delete
test directories. Only run when you have USB access for recovery.
"""

import os

from tests.unittest import TestCase
from utils.utils import suppress


def _create_test_structure(base_path: str) -> None:
    """
    Create a test directory structure with files and hidden artifacts.

    Args:
        base_path: Base directory path to create structure in
    """
    # Create directory structure
    os.mkdir(base_path)
    os.mkdir(f"{base_path}/subdir1")
    os.mkdir(f"{base_path}/subdir1/nested")
    os.mkdir(f"{base_path}/subdir2")

    # Create regular files
    with open(f"{base_path}/file1.txt", "w") as f:
        f.write("test content 1")
    with open(f"{base_path}/subdir1/file2.txt", "w") as f:
        f.write("test content 2")
    with open(f"{base_path}/subdir1/nested/file3.txt", "w") as f:
        f.write("test content 3")

    # Create hidden files (like macOS creates)
    with open(f"{base_path}/._hidden1", "w") as f:
        f.write("hidden content")
    with open(f"{base_path}/subdir1/._hidden2", "w") as f:
        f.write("hidden content")
    with open(f"{base_path}/subdir1/nested/._hidden3", "w") as f:
        f.write("hidden content")

    # Sync to ensure everything is written
    with suppress(OSError, AttributeError):
        os.sync()


def _count_items(path: str) -> int:
    """
    Recursively count all items (files + directories) under path.

    Args:
        path: Directory path to count items in

    Returns:
        Total count of files and directories
    """
    try:
        items = os.listdir(path)
    except OSError:
        return 0

    count = len(items)
    for item in items:
        item_path = f"{path}/{item}"
        try:
            # If it's a directory, recurse
            os.listdir(item_path)
            count += _count_items(item_path)
        except OSError:
            # It's a file, already counted
            pass

    return count


class TestBootCleanup(TestCase):
    """Test boot.py cleanup operations handle all filesystem artifacts."""

    def setUp(self) -> None:
        """Set up test directory before each test."""
        self.test_dir = "/test_cleanup_temp"
        # Clean up any leftover test directory
        self._cleanup()

    def tearDown(self) -> None:
        """Clean up test directory after each test."""
        self._cleanup()

    def _cleanup(self) -> None:
        """Remove test directory if it exists."""
        try:
            from core.boot_support import remove_directory_recursive

            remove_directory_recursive(self.test_dir)
            os.sync()
        except (OSError, ImportError):
            pass

    def test_remove_empty_directory(self) -> None:
        """Remove an empty directory."""
        from core.boot_support import remove_directory_recursive

        os.mkdir(self.test_dir)
        self.assertTrue(self._dir_exists(self.test_dir), "Test directory should exist")

        remove_directory_recursive(self.test_dir)

        self.assertFalse(self._dir_exists(self.test_dir), "Directory should be removed")

    def test_remove_directory_with_files(self) -> None:
        """Remove directory containing regular files."""
        from core.boot_support import remove_directory_recursive

        os.mkdir(self.test_dir)
        with open(f"{self.test_dir}/file1.txt", "w") as f:
            f.write("test content")
        with open(f"{self.test_dir}/file2.txt", "w") as f:
            f.write("test content")

        remove_directory_recursive(self.test_dir)

        self.assertFalse(self._dir_exists(self.test_dir), "Directory should be removed")

    def test_remove_directory_with_hidden_files(self) -> None:
        """Remove directory containing hidden files (._*)."""
        from core.boot_support import remove_directory_recursive

        os.mkdir(self.test_dir)
        with open(f"{self.test_dir}/regular.txt", "w") as f:
            f.write("regular content")
        with open(f"{self.test_dir}/._hidden", "w") as f:
            f.write("hidden content")

        remove_directory_recursive(self.test_dir)

        self.assertFalse(self._dir_exists(self.test_dir), "Directory with hidden files should be removed")

    def test_remove_nested_directory_structure(self) -> None:
        """Remove deeply nested directory structure."""
        from core.boot_support import remove_directory_recursive

        _create_test_structure(self.test_dir)

        # Verify structure was created
        count_before = _count_items(self.test_dir)
        self.assertGreater(count_before, 0, "Test structure should have items")

        remove_directory_recursive(self.test_dir)

        self.assertFalse(self._dir_exists(self.test_dir), "Nested structure should be completely removed")

    def test_remove_nonexistent_directory(self) -> None:
        """Remove non-existent directory (should not raise error)."""
        from core.boot_support import remove_directory_recursive

        # Should not raise - idempotent operation
        remove_directory_recursive("/nonexistent_test_dir_12345")

    def test_cleanup_pending_update_with_artifacts(self) -> None:
        """Test cleanup_pending_update removes all artifacts."""
        from core.boot_support import cleanup_pending_update

        # Create a mock pending_update structure
        pending_dir = "/pending_update"
        try:
            from core.boot_support import remove_directory_recursive

            remove_directory_recursive(pending_dir)
        except (OSError, ImportError):
            pass

        _create_test_structure(pending_dir)

        # Verify it exists
        self.assertTrue(self._dir_exists(pending_dir), "Pending update should exist")

        cleanup_pending_update()

        self.assertFalse(self._dir_exists(pending_dir), "Pending update should be completely removed")

    def _dir_exists(self, path: str) -> bool:
        """Check if directory exists."""
        try:
            os.listdir(path)
            return True
        except OSError:
            return False


class TestBootCleanupWithHiddenFiles(TestCase):
    """Test that hidden files are properly cleaned up (macOS ._* issue)."""

    def test_hidden_files_in_root_are_removed(self) -> None:
        """Hidden files at root level are removed."""
        from core.boot_support import remove_directory_recursive

        test_dir = "/test_hidden_cleanup"
        with suppress(OSError, ImportError):
            remove_directory_recursive(test_dir)

        os.mkdir(test_dir)

        # Create multiple hidden files
        for i in range(5):
            with open(f"{test_dir}/._hidden{i}", "w") as f:
                f.write("x" * 100)  # Make them non-empty

        remove_directory_recursive(test_dir)

        self.assertFalse(
            self._dir_exists(test_dir), "Directory with multiple hidden files should be completely removed"
        )

    def test_mixed_hidden_and_regular_files(self) -> None:
        """Mixed hidden and regular files are all removed."""
        from core.boot_support import remove_directory_recursive

        test_dir = "/test_mixed_cleanup"
        with suppress(OSError, ImportError):
            remove_directory_recursive(test_dir)

        os.mkdir(test_dir)
        os.mkdir(f"{test_dir}/subdir")

        # Create mixed files
        with open(f"{test_dir}/regular.txt", "w") as f:
            f.write("regular")
        with open(f"{test_dir}/._hidden", "w") as f:
            f.write("hidden")
        with open(f"{test_dir}/subdir/file.txt", "w") as f:
            f.write("nested regular")
        with open(f"{test_dir}/subdir/._nested_hidden", "w") as f:
            f.write("nested hidden")

        remove_directory_recursive(test_dir)

        self.assertFalse(self._dir_exists(test_dir), "Mixed file structure should be completely removed")

    def _dir_exists(self, path: str) -> bool:
        """Check if directory exists."""
        try:
            os.listdir(path)
            return True
        except OSError:
            return False
