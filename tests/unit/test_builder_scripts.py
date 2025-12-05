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
from builder import create_manifest, discover_install_scripts, is_script_only_release, parse_version

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
