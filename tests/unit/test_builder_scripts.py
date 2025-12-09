"""
Unit tests for install script discovery and inclusion in builder.py.

Tests the discover_install_scripts function and manifest creation
with script flags, including script-only releases.
"""

import os
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, ".")

# Import the functions we're testing
from builder import (
    create_manifest,
    discover_install_scripts,
    is_script_only_release,
    parse_version,
    update_releases_json,
)

from core.app_typing import Any, cast
from tests.unit import TestCase


class TestDiscoverInstallScripts(TestCase):
    """Tests for discover_install_scripts function."""

    def setUp(self) -> None:
        """Create a temporary directory structure for testing."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        os.makedirs("firmware_install_scripts", exist_ok=True)
        # Suppress console output during tests
        self._print_patcher = patch("builder.print_success")
        self._print_patcher.start()

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self._print_patcher.stop()
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_script(self, filename: str) -> str:
        """Create an empty script file in firmware_install_scripts/."""
        script_path = os.path.join("firmware_install_scripts", filename)
        with open(script_path, "w") as f:
            f.write("# Test script\ndef main(*args): pass\n")
        return script_path

    def test_no_scripts_directory_returns_empty(self) -> None:
        """Returns empty flags when scripts directory doesn't exist."""
        # Remove the directory we created in setUp
        shutil.rmtree("firmware_install_scripts")

        result = discover_install_scripts("1.0.0")

        self.assertFalse(result["has_pre_install_script"])
        self.assertFalse(result["has_post_install_script"])
        self.assertIsNone(result["pre_install_path"])
        self.assertIsNone(result["post_install_path"])

    def test_no_matching_scripts_returns_empty(self) -> None:
        """Returns empty flags when no scripts match the version."""
        # Create scripts for a different version
        self._create_script("pre_install_v2.0.0.py")

        result = discover_install_scripts("1.0.0")

        self.assertFalse(result["has_pre_install_script"])
        self.assertFalse(result["has_post_install_script"])

    def test_discovers_pre_install_script(self) -> None:
        """Discovers pre-install script matching version."""
        self._create_script("pre_install_v1.0.0.py")

        result = discover_install_scripts("1.0.0")

        self.assertTrue(result["has_pre_install_script"])
        self.assertFalse(result["has_post_install_script"])
        self.assertIsNotNone(result["pre_install_path"])
        self.assertEqual(result["pre_install_path"].name, "pre_install_v1.0.0.py")

    def test_discovers_post_install_script(self) -> None:
        """Discovers post-install script matching version."""
        self._create_script("post_install_v1.0.0.py")

        result = discover_install_scripts("1.0.0")

        self.assertFalse(result["has_pre_install_script"])
        self.assertTrue(result["has_post_install_script"])
        self.assertIsNotNone(result["post_install_path"])
        self.assertEqual(result["post_install_path"].name, "post_install_v1.0.0.py")

    def test_discovers_both_scripts(self) -> None:
        """Discovers both pre-install and post-install scripts."""
        self._create_script("pre_install_v1.0.0.py")
        self._create_script("post_install_v1.0.0.py")

        result = discover_install_scripts("1.0.0")

        self.assertTrue(result["has_pre_install_script"])
        self.assertTrue(result["has_post_install_script"])
        self.assertIsNotNone(result["pre_install_path"])
        self.assertIsNotNone(result["post_install_path"])

    def test_version_with_prerelease_suffix(self) -> None:
        """Discovers scripts with prerelease version suffix."""
        self._create_script("pre_install_v0.6.0-b2.py")
        self._create_script("post_install_v0.6.0-b2.py")

        result = discover_install_scripts("0.6.0-b2")

        self.assertTrue(result["has_pre_install_script"])
        self.assertTrue(result["has_post_install_script"])
        self.assertEqual(result["pre_install_path"].name, "pre_install_v0.6.0-b2.py")
        self.assertEqual(result["post_install_path"].name, "post_install_v0.6.0-b2.py")

    def test_version_with_rc_suffix(self) -> None:
        """Discovers scripts with rc prerelease suffix."""
        self._create_script("pre_install_v1.0.0-rc1.py")

        result = discover_install_scripts("1.0.0-rc1")

        self.assertTrue(result["has_pre_install_script"])
        self.assertEqual(result["pre_install_path"].name, "pre_install_v1.0.0-rc1.py")

    def test_ignores_example_files(self) -> None:
        """Example files (without version) are not discovered."""
        self._create_script("pre_install.py.example")
        self._create_script("post_install.py.example")

        result = discover_install_scripts("1.0.0")

        self.assertFalse(result["has_pre_install_script"])
        self.assertFalse(result["has_post_install_script"])

    def test_different_version_not_discovered(self) -> None:
        """Scripts for different versions are not discovered."""
        self._create_script("pre_install_v2.0.0.py")
        self._create_script("post_install_v2.0.0.py")

        result = discover_install_scripts("1.0.0")

        self.assertFalse(result["has_pre_install_script"])
        self.assertFalse(result["has_post_install_script"])


class TestCreateManifestWithScripts(TestCase):
    """Tests for create_manifest with install_scripts parameter."""

    def test_manifest_without_scripts(self) -> None:
        """Manifest created without scripts has no script flags."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts=None,
        )

        self.assertNotIn("has_pre_install_script", manifest)
        self.assertNotIn("has_post_install_script", manifest)

    def test_manifest_with_pre_install_script(self) -> None:
        """Manifest includes pre-install script flag when present."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts={
                "has_pre_install_script": True,
                "has_post_install_script": False,
            },
        )

        self.assertTrue(manifest["has_pre_install_script"])
        self.assertFalse(manifest["has_post_install_script"])

    def test_manifest_with_post_install_script(self) -> None:
        """Manifest includes post-install script flag when present."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts={
                "has_pre_install_script": False,
                "has_post_install_script": True,
            },
        )

        self.assertFalse(manifest["has_pre_install_script"])
        self.assertTrue(manifest["has_post_install_script"])

    def test_manifest_with_both_scripts(self) -> None:
        """Manifest includes both script flags when present."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts={
                "has_pre_install_script": True,
                "has_post_install_script": True,
            },
        )

        self.assertTrue(manifest["has_pre_install_script"])
        self.assertTrue(manifest["has_post_install_script"])

    def test_manifest_with_no_scripts_explicit(self) -> None:
        """Manifest with explicit no scripts has false flags."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts={
                "has_pre_install_script": False,
                "has_post_install_script": False,
            },
        )

        self.assertFalse(manifest["has_pre_install_script"])
        self.assertFalse(manifest["has_post_install_script"])

    def test_manifest_contains_required_fields(self) -> None:
        """Manifest contains all required fields regardless of scripts."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            install_scripts={"has_pre_install_script": True, "has_post_install_script": True},
        )

        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["target_machine_types"], ["Test Machine"])
        self.assertEqual(manifest["target_operating_systems"], ["circuitpython_10_1"])
        self.assertEqual(manifest["release_type"], "production")
        self.assertEqual(manifest["release_notes"], "Test release")
        self.assertIn("release_date", manifest)
        self.assertIn("schema_version", manifest)

    def test_manifest_with_script_only_flag(self) -> None:
        """Manifest includes script_only_release flag when set."""
        manifest = create_manifest(
            version="1.0.0-s1",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Script-only patch",
            install_scripts={"has_pre_install_script": True, "has_post_install_script": False},
            script_only=True,
        )

        self.assertTrue(manifest["script_only_release"])

    def test_manifest_without_script_only_flag(self) -> None:
        """Manifest does not include script_only_release when not set."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Normal release",
        )

        self.assertNotIn("script_only_release", manifest)

    def test_manifest_with_minimum_prior_version(self) -> None:
        """Manifest includes minimum_prior_version when provided."""
        manifest = create_manifest(
            version="2.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Test release",
            minimum_prior_version="1.5.0",
        )

        self.assertEqual(manifest["minimum_prior_version"], "1.5.0")

    def test_manifest_without_minimum_prior_version(self) -> None:
        """Manifest does not include minimum_prior_version when not provided."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Normal release",
        )

        self.assertNotIn("minimum_prior_version", manifest)

    def test_manifest_with_none_minimum_prior_version(self) -> None:
        """Manifest does not include minimum_prior_version when explicitly None."""
        manifest = create_manifest(
            version="1.0.0",
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_1"],
            release_type="production",
            release_notes="Normal release",
            minimum_prior_version=None,
        )

        self.assertNotIn("minimum_prior_version", manifest)


class TestIsScriptOnlyRelease(TestCase):
    """Tests for is_script_only_release function."""

    def test_simple_version_is_not_script_only(self) -> None:
        """Simple version without suffix is not script-only."""
        self.assertFalse(is_script_only_release("1.0.0"))

    def test_beta_version_is_not_script_only(self) -> None:
        """Beta version is not script-only."""
        self.assertFalse(is_script_only_release("1.0.0-b2"))

    def test_rc_version_is_not_script_only(self) -> None:
        """Release candidate is not script-only."""
        self.assertFalse(is_script_only_release("1.0.0-rc1"))

    def test_s_suffix_is_script_only(self) -> None:
        """Version with -s suffix is script-only."""
        self.assertTrue(is_script_only_release("1.0.0-s"))

    def test_s_with_number_is_script_only(self) -> None:
        """Version with -s[N] suffix is script-only."""
        self.assertTrue(is_script_only_release("1.0.0-s1"))
        self.assertTrue(is_script_only_release("0.7.2-s3"))
        self.assertTrue(is_script_only_release("2.0.0-s10"))

    def test_empty_version_is_not_script_only(self) -> None:
        """Empty version string is not script-only."""
        self.assertFalse(is_script_only_release(""))
        self.assertFalse(is_script_only_release(None))


class TestParseVersionWithScriptSuffix(TestCase):
    """Tests for parse_version with script-only suffix."""

    def test_parse_version_with_s_suffix(self) -> None:
        """parse_version accepts -s suffix."""
        result = parse_version("1.0.0-s")
        self.assertIsNotNone(result)
        if result:
            version_tuple, has_prerelease = result
            self.assertEqual(version_tuple, (1, 0, 0))
            self.assertTrue(has_prerelease)

    def test_parse_version_with_s_and_number(self) -> None:
        """parse_version accepts -s[N] suffix."""
        result = parse_version("0.7.2-s1")
        self.assertIsNotNone(result)
        if result:
            version_tuple, has_prerelease = result
            self.assertEqual(version_tuple, (0, 7, 2))
            self.assertTrue(has_prerelease)

    def test_parse_version_with_s3(self) -> None:
        """parse_version accepts -s3 suffix."""
        result = parse_version("1.2.3-s3")
        self.assertIsNotNone(result)
        if result:
            version_tuple, has_prerelease = result
            self.assertEqual(version_tuple, (1, 2, 3))
            self.assertTrue(has_prerelease)


class TestUpdateReleasesJson(TestCase):
    """Tests for update_releases_json with archive handling."""

    def test_first_release_creates_empty_archive(self) -> None:
        """First release for a platform creates empty archive."""
        releases_data = {"schema_version": "1.0.0", "last_updated": "", "releases": []}
        manifest = {
            "version": "1.0.0",
            "release_notes": "First release",
            "release_date": "2025-01-01T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="1.0.0",
            sha256_checksum="abc123",
        )

        self.assertEqual(len(releases_data["releases"]), 1)
        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        self.assertIn("production", release_entry)
        self.assertIn("archive", release_entry)
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        self.assertEqual(archive, [])

    def test_new_release_moves_previous_to_archive(self) -> None:
        """New release moves previous production/development to archive."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "1.0.0",
                        "release_notes": "Old release",
                        "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                        "sha256": "old123",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [],
                }
            ],
        }
        manifest = {
            "version": "2.0.0",
            "release_notes": "New release",
            "release_date": "2025-01-02T00:00:00Z",
            "minimum_prior_version": "1.0.0",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="2.0.0",
            sha256_checksum="new456",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        # New release is in production
        self.assertEqual(cast(dict[str, Any], release_entry["production"])["version"], "2.0.0")
        self.assertEqual(cast(dict[str, Any], release_entry["production"])["minimum_prior_version"], "1.0.0")
        # Old release is in archive
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        self.assertEqual(len(archive), 1)
        archived = archive[0]
        self.assertEqual(archived["version"], "1.0.0")
        self.assertEqual(archived["release_type"], "production")

    def test_archive_maintains_sort_order_newest_first(self) -> None:
        """Archive maintains newest-to-oldest sort order."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "3.0.0",
                        "release_notes": "Current",
                        "zip_url": "https://www.wicid.ai/releases/v3.0.0",
                        "sha256": "current",
                        "release_date": "2025-01-03T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "2.0.0",
                            "release_type": "production",
                            "release_notes": "Archive 2",
                            "zip_url": "https://www.wicid.ai/releases/v2.0.0",
                            "sha256": "arch2",
                            "release_date": "2025-01-02T00:00:00Z",
                        },
                        {
                            "version": "1.0.0",
                            "release_type": "production",
                            "release_notes": "Archive 1",
                            "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                            "sha256": "arch1",
                            "release_date": "2025-01-01T00:00:00Z",
                        },
                    ],
                }
            ],
        }
        manifest = {
            "version": "4.0.0",
            "release_notes": "Newest",
            "release_date": "2025-01-04T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="4.0.0",
            sha256_checksum="newest",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        # Archive should have 3.0.0, 2.0.0, 1.0.0 in that order (newest first)
        self.assertEqual(len(archive), 3)
        self.assertEqual(archive[0]["version"], "3.0.0")
        self.assertEqual(archive[1]["version"], "2.0.0")
        self.assertEqual(archive[2]["version"], "1.0.0")

    def test_development_release_archives_previous_development(self) -> None:
        """Development release archives previous development, not production."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "1.0.0",
                        "release_notes": "Prod",
                        "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                        "sha256": "prod",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "development": {
                        "version": "1.1.0-b1",
                        "release_notes": "Old dev",
                        "zip_url": "https://www.wicid.ai/releases/v1.1.0-b1",
                        "sha256": "olddev",
                        "release_date": "2025-01-02T00:00:00Z",
                    },
                    "archive": [],
                }
            ],
        }
        manifest = {
            "version": "1.2.0-b1",
            "release_notes": "New dev",
            "release_date": "2025-01-03T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="development",
            version="1.2.0-b1",
            sha256_checksum="newdev",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        # Production should remain unchanged
        self.assertEqual(cast(dict[str, Any], release_entry["production"])["version"], "1.0.0")
        # New development release
        self.assertEqual(cast(dict[str, Any], release_entry["development"])["version"], "1.2.0-b1")
        # Archive should have old development
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0]["version"], "1.1.0-b1")
        self.assertEqual(archive[0]["release_type"], "development")

    def test_minimum_prior_version_included_in_release(self) -> None:
        """minimum_prior_version from manifest is included in release entry."""
        releases_data = {"schema_version": "1.0.0", "last_updated": "", "releases": []}
        manifest = {
            "version": "2.0.0",
            "release_notes": "Test",
            "release_date": "2025-01-01T00:00:00Z",
            "minimum_prior_version": "1.5.0",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="2.0.0",
            sha256_checksum="abc123",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        self.assertEqual(cast(dict[str, Any], release_entry["production"])["minimum_prior_version"], "1.5.0")

    def test_archived_release_includes_minimum_prior_version(self) -> None:
        """Archived release preserves minimum_prior_version if it had one."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "minimum_prior_version": "1.5.0",
                        "release_notes": "Old",
                        "zip_url": "https://www.wicid.ai/releases/v2.0.0",
                        "sha256": "old",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [],
                }
            ],
        }
        manifest = {
            "version": "3.0.0",
            "release_notes": "New",
            "release_date": "2025-01-02T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="3.0.0",
            sha256_checksum="new",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        archived = archive[0]
        self.assertEqual(archived["minimum_prior_version"], "1.5.0")

    def test_release_not_archived_if_current_in_other_slot(self) -> None:
        """Release is not archived if it's current in the other release type slot."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "1.0.0",
                        "release_notes": "Same version",
                        "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                        "sha256": "prod",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "development": {
                        "version": "1.0.0",
                        "release_notes": "Same version",
                        "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                        "sha256": "dev",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [],
                }
            ],
        }
        manifest = {
            "version": "2.0.0",
            "release_notes": "New production",
            "release_date": "2025-01-02T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="2.0.0",
            sha256_checksum="newprod",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        # Production updated
        self.assertEqual(cast(dict[str, Any], release_entry["production"])["version"], "2.0.0")
        # Development still has 1.0.0
        self.assertEqual(cast(dict[str, Any], release_entry["development"])["version"], "1.0.0")
        # Archive should be empty (1.0.0 is still current in development)
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        self.assertEqual(len(archive), 0)

    def test_archive_cleaned_of_current_releases(self) -> None:
        """Archive is cleaned to remove releases that are now current."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "2.0.0",
                        "release_notes": "Current prod",
                        "zip_url": "https://www.wicid.ai/releases/v2.0.0",
                        "sha256": "prod",
                        "release_date": "2025-01-02T00:00:00Z",
                    },
                    "development": {
                        "version": "1.5.0",
                        "release_notes": "Current dev",
                        "zip_url": "https://www.wicid.ai/releases/v1.5.0",
                        "sha256": "dev",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [
                        {
                            "version": "2.0.0",  # Matches current production - should be removed
                            "release_type": "production",
                            "release_notes": "Old prod",
                            "zip_url": "https://www.wicid.ai/releases/v2.0.0",
                            "sha256": "oldprod",
                            "release_date": "2025-01-01T00:00:00Z",
                        },
                        {
                            "version": "1.5.0",  # Matches current development - should be removed
                            "release_type": "development",
                            "release_notes": "Old dev",
                            "zip_url": "https://www.wicid.ai/releases/v1.5.0",
                            "sha256": "olddev",
                            "release_date": "2025-01-01T00:00:00Z",
                        },
                        {
                            "version": "1.0.0",  # Not current - should remain
                            "release_type": "production",
                            "release_notes": "Old",
                            "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                            "sha256": "old",
                            "release_date": "2025-01-01T00:00:00Z",
                        },
                    ],
                }
            ],
        }
        manifest = {
            "version": "3.0.0",
            "release_notes": "New production",
            "release_date": "2025-01-03T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="production",
            version="3.0.0",
            sha256_checksum="newprod",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        archive = cast(list[dict[str, Any]], release_entry["archive"])
        # After updating production to 3.0.0:
        # - 2.0.0 (old production) is archived (not current in development)
        # - 1.0.0 remains in archive (not current)
        # - 1.5.0 is removed from archive (current in development)
        # - Duplicate 2.0.0 entries are deduplicated
        versions_in_archive = [archived["version"] for archived in archive]
        self.assertIn("2.0.0", versions_in_archive)
        self.assertIn("1.0.0", versions_in_archive)
        self.assertNotIn("1.5.0", versions_in_archive)
        # Verify no duplicates
        self.assertEqual(len(versions_in_archive), len(set(versions_in_archive)))

    def test_release_entry_key_order(self) -> None:
        """Release entry keys are ordered: production, development, archive."""
        releases_data = {
            "schema_version": "1.0.0",
            "last_updated": "",
            "releases": [
                {
                    "target_machine_types": ["Test Machine"],
                    "target_operating_systems": ["circuitpython_10_0"],
                    "production": {
                        "version": "1.0.0",
                        "release_notes": "Prod",
                        "zip_url": "https://www.wicid.ai/releases/v1.0.0",
                        "sha256": "prod",
                        "release_date": "2025-01-01T00:00:00Z",
                    },
                    "archive": [],
                }
            ],
        }
        manifest = {
            "version": "1.1.0-rc1",
            "release_notes": "Dev release",
            "release_date": "2025-01-02T00:00:00Z",
        }

        update_releases_json(
            releases_data,
            manifest,
            target_machines=["Test Machine"],
            target_oses=["circuitpython_10_0"],
            release_type="development",
            version="1.1.0-rc1",
            sha256_checksum="dev",
        )

        release_entry = cast(dict[str, Any], releases_data["releases"][0])
        keys = list(release_entry.keys())
        expected_prefix = [
            "target_machine_types",
            "target_operating_systems",
            "production",
            "development",
            "archive",
        ]
        self.assertEqual(keys[: len(expected_prefix)], expected_prefix)
