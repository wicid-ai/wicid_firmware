"""
Unit tests for utils module.

Tests verify:
- suppress context manager
- Version comparison
- OS version matching
- Release compatibility checking
"""

from tests.unit import TestCase
from utils.utils import check_release_compatibility, compare_versions, os_matches_target, suppress


class TestSuppress(TestCase):
    """Test suppress context manager."""

    def test_suppresses_matching_exception(self) -> None:
        """suppress() catches and suppresses matching exceptions."""
        with suppress(ValueError):
            raise ValueError("should be suppressed")
        # If we get here, exception was suppressed

    def test_suppresses_multiple_exception_types(self) -> None:
        """suppress() handles multiple exception types."""
        with suppress(ValueError, TypeError):
            raise TypeError("should be suppressed")

        with suppress(ValueError, TypeError):
            raise ValueError("should also be suppressed")

    def test_does_not_suppress_non_matching(self) -> None:
        """suppress() does not catch non-matching exceptions."""
        with (
            self.assertRaises(RuntimeError),
            suppress(ValueError),
        ):
            raise RuntimeError("should propagate")

    def test_does_nothing_without_exception(self) -> None:
        """suppress() does nothing when no exception occurs."""
        with suppress(ValueError):
            x = 1 + 1
        self.assertEqual(x, 2)

    def test_suppresses_subclass_exceptions(self) -> None:
        """suppress() catches subclass exceptions."""
        # OSError is a subclass of Exception
        with suppress(Exception):
            raise OSError("should be suppressed as subclass")


class TestCompareVersions(TestCase):
    """Test semantic version comparison."""

    def test_major_version_comparison(self) -> None:
        """Major version differences are detected."""
        self.assertEqual(compare_versions("2.0.0", "1.0.0"), 1)
        self.assertEqual(compare_versions("1.0.0", "2.0.0"), -1)

    def test_minor_version_comparison(self) -> None:
        """Minor version differences are detected."""
        self.assertEqual(compare_versions("1.2.0", "1.1.0"), 1)
        self.assertEqual(compare_versions("1.1.0", "1.2.0"), -1)

    def test_patch_version_comparison(self) -> None:
        """Patch version differences are detected."""
        self.assertEqual(compare_versions("1.0.2", "1.0.1"), 1)
        self.assertEqual(compare_versions("1.0.1", "1.0.2"), -1)

    def test_equal_versions(self) -> None:
        """Equal versions return 0."""
        self.assertEqual(compare_versions("1.2.3", "1.2.3"), 0)
        self.assertEqual(compare_versions("0.0.0", "0.0.0"), 0)

    def test_prerelease_versions(self) -> None:
        """Prerelease versions are compared correctly."""
        # Release > prerelease
        self.assertEqual(compare_versions("1.0.0", "1.0.0-beta"), 1)
        self.assertEqual(compare_versions("1.0.0-alpha", "1.0.0"), -1)

    def test_prerelease_comparison(self) -> None:
        """Prerelease tags are compared lexicographically."""
        self.assertEqual(compare_versions("1.0.0-beta", "1.0.0-alpha"), 1)
        self.assertEqual(compare_versions("1.0.0-alpha", "1.0.0-beta"), -1)
        self.assertEqual(compare_versions("1.0.0-alpha", "1.0.0-alpha"), 0)

    def test_partial_versions(self) -> None:
        """Partial version strings are handled."""
        self.assertEqual(compare_versions("1", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.2", "1.2.0"), 0)
        self.assertEqual(compare_versions("2", "1.9.9"), 1)


class TestOsMatchesTarget(TestCase):
    """Test OS version matching logic."""

    def test_exact_match(self) -> None:
        """Exact version match returns True."""
        result = os_matches_target("circuitpython_10_1_0", ["circuitpython_10_1"])
        self.assertTrue(result)

    def test_newer_minor_matches(self) -> None:
        """Device with newer minor version matches older target."""
        result = os_matches_target("circuitpython_10_2_0", ["circuitpython_10_1"])
        self.assertTrue(result)

    def test_newer_major_matches(self) -> None:
        """Device with newer major version matches older target."""
        result = os_matches_target("circuitpython_11_0_0", ["circuitpython_10_1"])
        self.assertTrue(result)

    def test_older_version_no_match(self) -> None:
        """Device with older version does not match newer target."""
        result = os_matches_target("circuitpython_10_0_0", ["circuitpython_10_1"])
        self.assertFalse(result)

    def test_different_os_no_match(self) -> None:
        """Different OS name does not match."""
        result = os_matches_target("micropython_10_1_0", ["circuitpython_10_1"])
        self.assertFalse(result)

    def test_multiple_targets(self) -> None:
        """Matches any compatible target in array."""
        result = os_matches_target(
            "circuitpython_10_1_0",
            ["circuitpython_9_0", "circuitpython_10_1", "circuitpython_11_0"],
        )
        self.assertTrue(result)

    def test_empty_target_array(self) -> None:
        """Empty target array returns False."""
        result = os_matches_target("circuitpython_10_1_0", [])
        self.assertFalse(result)


class TestCheckReleaseCompatibility(TestCase):
    """Test release compatibility checking."""

    def test_compatible_release(self) -> None:
        """Compatible release returns True."""
        release = {
            "version": "2.0.0",
            "target_machine_types": ["test_machine"],
            "target_operating_systems": ["circuitpython_10_0"],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertTrue(is_compat)
        self.assertIsNone(error)

    def test_incompatible_machine_type(self) -> None:
        """Incompatible machine type returns False."""
        release = {
            "version": "2.0.0",
            "target_machine_types": ["other_machine"],
            "target_operating_systems": ["circuitpython_10_0"],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("Incompatible hardware", error)

    def test_incompatible_os(self) -> None:
        """Incompatible OS returns False."""
        release = {
            "version": "2.0.0",
            "target_machine_types": ["test_machine"],
            "target_operating_systems": ["circuitpython_11_0"],  # Requires 11.x
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_0_0",  # Device has 10.x
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("Incompatible OS", error)

    def test_version_not_newer(self) -> None:
        """Same or older version returns False."""
        release = {
            "version": "1.0.0",
            "target_machine_types": ["test_machine"],
            "target_operating_systems": ["circuitpython_10_0"],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("not newer", error)

    def test_older_version_rejected(self) -> None:
        """Older version returns False."""
        release = {
            "version": "0.9.0",
            "target_machine_types": ["test_machine"],
            "target_operating_systems": ["circuitpython_10_0"],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("not newer", error)

    def test_empty_machine_types_rejected(self) -> None:
        """Empty target machine types list rejects all."""
        release = {
            "version": "2.0.0",
            "target_machine_types": [],
            "target_operating_systems": ["circuitpython_10_0"],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("Incompatible hardware", error)

    def test_empty_os_list_rejected(self) -> None:
        """Empty target OS list rejects all."""
        release = {
            "version": "2.0.0",
            "target_machine_types": ["test_machine"],
            "target_operating_systems": [],
        }
        is_compat, error = check_release_compatibility(
            release,
            current_version="1.0.0",
            device_machine="test_machine",
            device_os="circuitpython_10_1_0",
        )
        self.assertFalse(is_compat)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("Incompatible OS", error)


class TestMarkIncompatibleRelease(TestCase):
    """Test incompatible release marking."""

    def test_marks_new_release(self) -> None:
        """New release is marked with reason."""
        from unittest.mock import mock_open, patch

        from utils.utils import mark_incompatible_release

        mock_file = mock_open(read_data='{"releases": {}}')
        with (
            patch("builtins.open", mock_file),
            patch("json.dump") as mock_dump,
            patch("os.sync"),
            patch("core.logging_helper.logger"),
        ):
            mark_incompatible_release("2.0.0", "Test reason")
            # Check that json.dump was called with the version
            call_args = mock_dump.call_args[0][0]
            self.assertIn("2.0.0", call_args["releases"])

    def test_increments_attempt_counter(self) -> None:
        """Existing release increments attempt counter."""
        from unittest.mock import mock_open, patch

        from utils.utils import mark_incompatible_release

        existing_data = '{"releases": {"2.0.0": {"reason": "old", "attempts": 1}}}'
        mock_file = mock_open(read_data=existing_data)
        with (
            patch("builtins.open", mock_file),
            patch("json.load", return_value={"releases": {"2.0.0": {"reason": "old", "attempts": 1}}}),
            patch("json.dump") as mock_dump,
            patch("os.sync"),
            patch("core.logging_helper.logger"),
        ):
            mark_incompatible_release("2.0.0", "New reason")
            call_args = mock_dump.call_args[0][0]
            self.assertEqual(call_args["releases"]["2.0.0"]["attempts"], 2)

    def test_handles_missing_file(self) -> None:
        """Missing file creates new structure."""
        from unittest.mock import mock_open, patch

        from utils.utils import mark_incompatible_release

        mock_file = mock_open()
        mock_file.side_effect = [OSError("missing"), mock_open()()]
        with (
            patch("builtins.open", mock_file),
            patch("json.dump") as mock_dump,
            patch("os.sync"),
            patch("core.logging_helper.logger"),
        ):
            mark_incompatible_release("2.0.0", "Test")
            # Should still write successfully
            self.assertTrue(mock_dump.called)


class TestIsReleaseIncompatible(TestCase):
    """Test incompatible release checking."""

    def test_unknown_release_is_compatible(self) -> None:
        """Unknown release returns compatible."""
        from unittest.mock import mock_open, patch

        from utils.utils import is_release_incompatible

        with patch("builtins.open", mock_open(read_data='{"releases": {}}')):
            is_incompat, reason, attempts = is_release_incompatible("2.0.0")
            self.assertFalse(is_incompat)
            self.assertIsNone(reason)
            self.assertEqual(attempts, 0)

    def test_known_release_is_incompatible(self) -> None:
        """Known release returns incompatible with reason."""
        from unittest.mock import mock_open, patch

        from utils.utils import is_release_incompatible

        data = '{"releases": {"2.0.0": {"reason": "Bad checksum", "attempts": 1}}}'
        with patch("builtins.open", mock_open(read_data=data)):
            is_incompat, reason, attempts = is_release_incompatible("2.0.0")
            self.assertTrue(is_incompat)
            self.assertEqual(reason, "Bad checksum")
            self.assertEqual(attempts, 1)

    def test_handles_missing_file(self) -> None:
        """Missing file returns compatible."""
        from unittest.mock import patch

        from utils.utils import is_release_incompatible

        with patch("builtins.open", side_effect=OSError("missing")):
            is_incompat, reason, attempts = is_release_incompatible("2.0.0")
            self.assertFalse(is_incompat)
