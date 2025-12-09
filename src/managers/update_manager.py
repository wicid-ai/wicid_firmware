"""
OTA Update Manager for WICID firmware.

Handles checking for firmware updates, downloading update packages,
extracting them to /pending_update/root/, and managing the update process.

CRITICAL: This module is the SINGLE SOURCE OF TRUTH for all OTA update operations.

Usage:
    update_manager = UpdateManager.instance()
    # Pass callbacks explicitly when calling download methods
    await update_manager.check_download_and_reboot(progress_callback=my_callback)

    # Or for manual control:
    update_info = update_manager.check_for_updates()
    if update_info:
        await update_manager.download_update(progress_callback=my_callback)

LED Feedback:
    - UpdateManager accesses PixelController singleton internally
    - LED flashes blue/green during download, verification, and extraction
    - No need to pass pixel_controller as parameter

DO NOT:
    - Call check_for_updates() and download_update() separately unless testing
    - Use supervisor.reload() after downloading updates (it skips boot.py)
    - Implement update logic elsewhere - use this centralized implementation

Reset Types:
    - microcontroller.reset() = Hard reset, runs boot.py (REQUIRED for OTA updates)
    - supervisor.reload() = Soft reboot, skips boot.py (use for config changes only)
"""

import json
import os
import time
import traceback

import adafruit_hashlib as hashlib  # pyright: ignore[reportMissingImports]  # CircuitPython-only module
import microcontroller  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

import utils.update_install as update_install
from core.app_typing import Any, Callable, List
from core.logging_helper import logger
from core.scheduler import Scheduler
from managers.manager_base import ManagerBase
from utils.recovery import CRITICAL_FILES, validate_files
from utils.update_install import remove_directory_recursive
from utils.utils import (
    check_release_compatibility,
    compare_versions,
    get_machine_type,
    get_os_version_string,
    mark_incompatible_release,
    suppress,
)


class UpdateManager(ManagerBase):
    """Manages over-the-air firmware updates."""

    _instance = None
    pixel_controller: Any = None  # PixelController | None, but Any to avoid circular import

    MIN_FREE_SPACE_BYTES = 200000  # ~200KB buffer for operations

    def _init(
        self,
        connection_manager: Any = None,
    ) -> None:
        """
        Initialize the update manager.

        Args:
            connection_manager: Optional ConnectionManager instance for testing/DI (gets singleton if None)
        """
        # Get ConnectionManager singleton if not provided (for testing/DI)
        if connection_manager is None:
            from managers.connection_manager import ConnectionManager

            self.connection_manager = ConnectionManager.instance()
        else:
            self.connection_manager = connection_manager

        self._cached_update_info: dict[str, Any] | None = None  # Store check_for_updates() results
        self.next_update_check: float | None = None
        self.logger = logger("wicid.update_manager")

        # Access singleton for LED feedback (optional, gracefully handles if unavailable)
        try:
            from controllers.pixel_controller import PixelController

            self.pixel_controller = PixelController()
        except (ImportError, Exception):
            self.pixel_controller = None

        self._initialized = True

    @staticmethod
    def check_disk_space(required_bytes: int) -> tuple[bool, str]:
        """
        Check if sufficient disk space is available.

        Args:
            required_bytes: Minimum bytes required

        Returns:
            tuple: (bool, str) - (sufficient, message)
        """
        try:
            stat = os.statvfs("/")
            free_bytes = stat[0] * stat[3]  # f_bsize * f_bavail

            if free_bytes >= required_bytes:
                free_kb = free_bytes / 1024
                return (True, f"Sufficient space: {free_kb:.1f}KB free")
            else:
                free_kb = free_bytes / 1024
                required_kb = required_bytes / 1024
                return (False, f"Insufficient space: {free_kb:.1f}KB free, {required_kb:.1f}KB required")

        except Exception as e:
            return (False, f"Could not check disk space: {e}")

    def _remove_directory_recursive(self, path: str) -> None:
        """
        Recursively remove a directory and all its contents.

        Delegates to shared utility function.

        Args:
            path: Directory path to remove
        """
        remove_directory_recursive(path)

    def _cleanup_pending_update(self) -> None:
        """
        Remove the entire /pending_update directory tree.

        Cleans up all staging artifacts including .staging, root, .ready marker,
        and any leftover ZIP files. Called on failures to ensure clean state
        for next update attempt.
        """
        try:
            remove_directory_recursive(update_install.PENDING_UPDATE_DIR)
            self.logger.debug("Removed pending_update directory")
        except Exception as e:
            self.logger.warning(f"Error cleaning up pending_update: {e}")

    def _write_ready_marker(self, manifest_hash: str) -> None:
        """
        Write the .ready marker file with manifest hash.

        The .ready marker signals to boot.py that staging is complete and
        the update is ready for installation. Contains the manifest hash
        for integrity verification.

        Args:
            manifest_hash: SHA-256 hash of manifest.json for verification
        """
        try:
            with open(update_install.READY_MARKER_FILE, "w") as f:
                f.write(manifest_hash)
            os.sync()
            self.logger.debug(f"Wrote ready marker with hash: {manifest_hash[:16]}...")
        except Exception as e:
            self.logger.warning(f"Failed to write ready marker: {e}")

    def _validate_ready_marker(self, expected_hash: str) -> bool:
        """
        Validate the .ready marker contains the expected manifest hash.

        Args:
            expected_hash: Expected SHA-256 hash of manifest.json

        Returns:
            bool: True if marker exists and hash matches, False otherwise
        """
        try:
            with open(update_install.READY_MARKER_FILE) as f:
                actual_hash = f.read().strip()
            return actual_hash == expected_hash
        except OSError:
            return False

    def _record_failed_update(self, reason: str, version: str | None = None) -> None:
        """
        Delegate to utils.mark_incompatible_release so failed versions are skipped next time.
        """
        version_to_block = version or (self._cached_update_info.get("version") if self._cached_update_info else None)
        if not version_to_block:
            self.logger.warning(f"Unable to record failed update: unknown version ({reason})")
            return

        try:
            mark_incompatible_release(version_to_block, reason)
        except Exception as e:
            self.logger.warning(f"Could not record failed update {version_to_block}: {e}")

    async def calculate_sha256(
        self,
        file_path: str,
        chunk_size: int = 2048,
        progress_callback: Callable[[str, str, float | None], None] | None = None,
        service_callback: Callable[[], None] | None = None,
    ) -> str | None:
        """
        Calculate SHA-256 checksum of a file using adafruit_hashlib.

        Uses 2KB chunks to balance verification speed with LED animation responsiveness.
        This size ensures yielding occurs frequently enough (~10-20ms) to keep the
        scheduler's 25Hz LED animation task from being starved.

        Args:
            file_path: Path to file to checksum
            chunk_size: Bytes to read per iteration (default: 2KB for speed/responsiveness balance)
            progress_callback: Optional callback for progress reporting
            service_callback: Optional callback to service background tasks

        Returns:
            str | None: Hexadecimal SHA-256 checksum, or None on error
        """
        try:
            # Get file size for progress indication
            file_size = os.stat(file_path)[6]  # st_size
            self.logger.debug(f"File size: {file_size / 1024:.1f} KB")

            start_time = time.monotonic()
            sha256 = hashlib.sha256()  # type: ignore[attr-defined]
            bytes_processed = 0
            tick_count = 0
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sha256.update(chunk)
                    bytes_processed += len(chunk)
                    tick_count += 1

                    # Yield control to scheduler so other tasks can run
                    if service_callback:
                        try:
                            service_callback()
                        except Exception as e:
                            self.logger.debug(f"Service callback error: {e}")
                    await Scheduler.yield_control()

                    if progress_callback:
                        progress_pct = int((bytes_processed / file_size) * 100)
                        progress_pct = max(0, min(progress_pct, 100))
                        try:
                            progress_callback("verifying", "Verifying download integrity...", progress_pct)
                        except Exception as e:
                            self.logger.warning(f"Progress callback error: {e}")

            elapsed = time.monotonic() - start_time
            self.logger.debug(f"Checksum calculated in {elapsed:.1f} seconds")
            self.logger.debug(f"Total tick() calls during checksum: {tick_count}")
            if tick_count:
                self.logger.debug(f"Average time per chunk: {elapsed / tick_count:.2f} seconds")

            return sha256.hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating checksum: {e}")
            traceback.print_exception(e)
            return None

    async def verify_checksum(
        self,
        file_path: str,
        expected_checksum: str,
        progress_callback: Callable[[str, str, float | None], None] | None = None,
        service_callback: Callable[[], None] | None = None,
    ) -> tuple[bool, str]:
        """
        Verify file matches expected SHA-256 checksum using adafruit_hashlib.

        Args:
            file_path: Path to file to verify
            expected_checksum: Expected SHA-256 hex string
            progress_callback: Optional callback for progress reporting
            service_callback: Optional callback to service background tasks

        Returns:
            tuple: (bool, str) - (matches, message)
        """
        if not expected_checksum:
            return (False, "No checksum provided - update manifest may be from older version")

        actual_checksum = await self.calculate_sha256(
            file_path, progress_callback=progress_callback, service_callback=service_callback
        )

        if actual_checksum is None:
            return (False, "Failed to calculate checksum")

        if actual_checksum.lower() == expected_checksum.lower():
            return (True, f"Checksum verified: {actual_checksum[:16]}...")
        else:
            return (False, f"Checksum mismatch: expected {expected_checksum[:16]}..., got {actual_checksum[:16]}...")

    def _determine_release_channel(self) -> str:
        """
        Determine which release channel to use.

        Returns:
            str: "development" if /DEVELOPMENT file exists, else "production"
        """
        try:
            with open("/DEVELOPMENT"):
                return "development"
        except OSError:
            return "production"

    def check_for_updates(self) -> dict[str, Any] | None:
        """
        Check if a newer compatible version is available for this device.

        Uses device self-identification and multi-platform manifest format.
        Caches result for use by download_update().

        Returns:
            dict or None: Update info dict with keys 'version', 'zip_url', 'release_notes'
                         if update is available, otherwise None
        """
        try:
            session = self._get_session()
            # Get device characteristics at runtime
            device_machine = get_machine_type()
            device_os = get_os_version_string()
            current_version = os.getenv("VERSION", "0.0.0")
            manifest_url = os.getenv("SYSTEM_UPDATE_MANIFEST_URL")

            if not manifest_url:
                self.logger.warning("No update manifest URL configured")
                return None

            self.logger.info("Checking for updates")
            self.logger.debug(f"Machine: {device_machine}, OS: {device_os}, Version: {current_version}")

            # Get weather_zip for user-agent
            try:
                with open("/secrets.json") as f:
                    secrets = json.load(f)
                    weather_zip = secrets.get("weather_zip", "")
            except Exception:
                weather_zip = ""

            # Include device info in User-Agent header
            user_agent = f"WICID/{current_version} ({device_machine}; {device_os}; ZIP:{weather_zip})"
            headers = self._build_request_headers(user_agent=user_agent)

            # Fetch the releases manifest
            response = session.get(manifest_url, headers=headers)

            # Check if response is successful
            if response.status_code != 200:
                self.logger.error(f"Update check failed: HTTP {response.status_code}")
                response.close()
                return None

            # Try to parse JSON
            try:
                manifest = response.json()
            except (ValueError, AttributeError):
                self.logger.error("Invalid JSON response from manifest URL")
                response.close()
                return None

            response.close()

            # Determine which release channel to use
            channel = self._determine_release_channel()
            self.logger.debug(f"Using release channel: {channel}")

            # Find compatible releases
            releases_array = manifest.get("releases", [])

            for release_entry in releases_array:
                if channel == "production":
                    # Production mode: only consider production releases
                    if "production" not in release_entry:
                        continue

                    release_info = release_entry["production"]

                    # Prepare release data for compatibility check
                    release_data = {
                        "target_machine_types": release_entry.get("target_machine_types", []),
                        "target_operating_systems": release_entry.get("target_operating_systems", []),
                        "version": release_info["version"],
                    }

                    # Use DRY compatibility check
                    is_compatible, error_msg = check_release_compatibility(release_data, current_version)

                    if is_compatible:
                        self.logger.info(f"Update available: {current_version} -> {release_info['version']}")
                        update_info = {
                            "version": release_info["version"],
                            "zip_url": release_info.get("zip_url"),
                            "sha256": release_info.get("sha256"),
                            "release_notes": release_info.get("release_notes", ""),
                            "target_machine_types": release_entry.get("target_machine_types", []),
                            "target_operating_systems": release_entry.get("target_operating_systems", []),
                        }
                        self._cached_update_info = update_info  # Cache for download_update()
                        return update_info
                    else:
                        self.logger.debug(f"Skipping production {release_info['version']}: {error_msg}")

                else:  # channel == "development"
                    # Development mode: check both production and development, pick best compatible
                    compatible_releases = []

                    # Check production release if it exists
                    if "production" in release_entry:
                        prod_info = release_entry["production"]
                        prod_release_data = {
                            "target_machine_types": release_entry.get("target_machine_types", []),
                            "target_operating_systems": release_entry.get("target_operating_systems", []),
                            "version": prod_info["version"],
                        }
                        is_compatible, error_msg = check_release_compatibility(prod_release_data, current_version)
                        if is_compatible:
                            compatible_releases.append(("production", prod_info))
                        else:
                            self.logger.debug(f"Skipping production {prod_info['version']}: {error_msg}")

                    # Check development release if it exists
                    if "development" in release_entry:
                        dev_info = release_entry["development"]
                        dev_release_data = {
                            "target_machine_types": release_entry.get("target_machine_types", []),
                            "target_operating_systems": release_entry.get("target_operating_systems", []),
                            "version": dev_info["version"],
                        }
                        is_compatible, error_msg = check_release_compatibility(dev_release_data, current_version)
                        if is_compatible:
                            compatible_releases.append(("development", dev_info))
                        else:
                            self.logger.debug(f"Skipping development {dev_info['version']}: {error_msg}")

                    # Select best compatible release
                    if len(compatible_releases) == 0:
                        continue  # Neither is compatible, skip this entry
                    elif len(compatible_releases) == 1:
                        # Only one compatible, use it
                        selected_channel, selected_info = compatible_releases[0]
                        self.logger.info(
                            f"Update available: {current_version} -> {selected_info['version']} ({selected_channel})"
                        )
                        update_info = {
                            "version": selected_info["version"],
                            "zip_url": selected_info.get("zip_url"),
                            "sha256": selected_info.get("sha256"),
                            "release_notes": selected_info.get("release_notes", ""),
                            "target_machine_types": release_entry.get("target_machine_types", []),
                            "target_operating_systems": release_entry.get("target_operating_systems", []),
                        }
                        self._cached_update_info = update_info  # Cache for download_update()
                        return update_info
                    else:
                        # Both are compatible, compare versions
                        # Find production and development releases
                        prod_info = None
                        dev_info = None
                        for ch, info in compatible_releases:
                            if ch == "production":
                                prod_info = info
                            elif ch == "development":
                                dev_info = info

                        # Compare versions (returns 1 if first > second, -1 if first < second, 0 if equal)
                        version_comparison = compare_versions(prod_info["version"], dev_info["version"])

                        if version_comparison > 0:
                            # Production is newer
                            selected_channel, selected_info = ("production", prod_info)
                            self.logger.info(
                                f"Update available: {current_version} -> {prod_info['version']} (production, newer than development {dev_info['version']})"
                            )
                        elif version_comparison < 0:
                            # Development is newer
                            selected_channel, selected_info = ("development", dev_info)
                            self.logger.info(
                                f"Update available: {current_version} -> {dev_info['version']} (development, newer than production {prod_info['version']})"
                            )
                        else:
                            # Versions are equal, prefer production
                            selected_channel, selected_info = ("production", prod_info)
                            self.logger.info(
                                f"Update available: {current_version} -> {prod_info['version']} (production, same as development, preferring production)"
                            )

                        update_info = {
                            "version": selected_info["version"],
                            "zip_url": selected_info.get("zip_url"),
                            "sha256": selected_info.get("sha256"),
                            "release_notes": selected_info.get("release_notes", ""),
                            "target_machine_types": release_entry.get("target_machine_types", []),
                            "target_operating_systems": release_entry.get("target_operating_systems", []),
                        }
                        self._cached_update_info = update_info  # Cache for download_update()
                        return update_info

            self.logger.info("No compatible updates available")
            return None

        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")
            traceback.print_exception(e)
            return None

    def _get_session(self) -> Any:
        """
        Get HTTP session from ConnectionManager.

        ConnectionManager owns the session lifecycle - it creates, caches, and
        cleans up the session when the socket pool changes.

        Returns:
            HTTP session instance
        """
        return self.connection_manager.get_session()

    def _build_request_headers(self, user_agent: str | None = None) -> dict[str, str]:
        """
        Build HTTP request headers with Connection: close for socket cleanup.

        The Connection: close header ensures that sockets are released immediately
        after the request completes, rather than being kept alive for reuse.
        This is critical on resource-constrained devices to prevent socket exhaustion.

        Args:
            user_agent: Optional User-Agent string to include in headers

        Returns:
            dict[str, str]: Headers dictionary with Connection: close and optional User-Agent
        """
        headers = {"Connection": "close"}
        if user_agent:
            headers["User-Agent"] = user_agent
        return headers

    async def download_update(
        self,
        zip_url: str | None = None,
        expected_checksum: str | None = None,
        progress_callback: Callable[[str, str, float | None], None] | None = None,
        service_callback: Callable[[], None] | None = None,
    ) -> tuple[bool, str]:
        """
        Download update package and extract to /pending_update/root/.

        Uses cached update info from check_for_updates() if no explicit parameters provided.
        Cooperative yields ensure scheduler-driven tasks stay responsive during long operations.

        Args:
            zip_url: Optional explicit URL (uses cached if None)
            expected_checksum: Optional explicit SHA-256 checksum (uses cached if None)
            progress_callback: Optional callback for progress reporting
            service_callback: Optional callback to service background tasks

        Returns:
            bool: True if download and extraction successful, False otherwise

        Raises:
            ValueError: If no cached update info and no explicit parameters provided
        """
        if zip_url is None:
            if self._cached_update_info is None:
                raise ValueError("No update info available. Call check_for_updates() first.")
            zip_url = self._cached_update_info.get("zip_url")
            expected_checksum = self._cached_update_info.get("sha256")

        session = self._get_session()

        def notify(state: str, msg: str, pct: float | None = None) -> None:
            if progress_callback:
                try:
                    progress_callback(state, msg, pct)
                except Exception as e:
                    self.logger.warning(f"Progress callback error: {e}")
            if service_callback:
                try:
                    service_callback()
                except Exception as e:
                    self.logger.debug(f"Service callback error: {e}")

        async def _execute_download() -> tuple[bool, str]:
            try:
                space_ok, space_msg = self.check_disk_space(self.MIN_FREE_SPACE_BYTES)
                self.logger.debug(f"Disk space check: {space_msg}")
                if not space_ok:
                    self.logger.error("Insufficient disk space for update")
                    self.logger.error("Please free up space and try again")
                    self._cleanup_pending_update()
                    self._record_failed_update("Insufficient disk space")
                    return False, "Insufficient disk space for update"

                # Clean up any previous failed update artifacts before starting
                # Use full cleanup to remove staging, root, and any leftover files
                self._cleanup_pending_update()

                # Create staging directory structure
                with suppress(OSError):
                    os.mkdir(update_install.PENDING_UPDATE_DIR)
                with suppress(OSError):
                    os.mkdir(update_install.PENDING_STAGING_DIR)

                zip_path = f"{update_install.PENDING_UPDATE_DIR}/update.zip"
                self.logger.info(f"Downloading update: {zip_url}")
                self.logger.debug(f"Saving to: {zip_path}")

                notify("downloading", "Starting download...", 0)

                def _get_content_length(headers: Any) -> int | None:
                    if not headers:
                        return None
                    try:
                        for key in ("Content-Length", "content-length"):
                            value = headers.get(key)
                            if value:
                                return value
                    except AttributeError:
                        pass
                    try:
                        for key, value in headers.items():
                            if isinstance(key, str) and key.lower() == "content-length":
                                return value
                    except Exception:
                        pass
                    return None

                content_length = None
                try:
                    head_response = session.head(zip_url, headers=self._build_request_headers())
                    if hasattr(head_response, "headers") and head_response.headers:
                        content_length_str = _get_content_length(head_response.headers)
                        if content_length_str:
                            try:
                                content_length = int(content_length_str)
                                self.logger.debug(f"Content-Length from HEAD: {content_length} bytes")
                            except (ValueError, TypeError):
                                pass
                    head_response.close()
                except Exception as e:
                    self.logger.debug(f"HEAD request failed (non-critical): {e}")

                response = session.get(zip_url, headers=self._build_request_headers())

                if content_length is None and hasattr(response, "headers") and response.headers:
                    content_length_str = _get_content_length(response.headers)
                    if content_length_str:
                        try:
                            content_length = int(content_length_str)
                            self.logger.debug(f"Content-Length from GET: {content_length} bytes")
                        except (ValueError, TypeError):
                            pass

                bytes_downloaded = 0
                download_chunk_size = 2048  # Smaller chunks keep LED/service callbacks responsive
                with open(zip_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=download_chunk_size):
                        if not chunk:
                            continue
                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                        progress_pct: float | None = None
                        if content_length and content_length > 0:
                            progress_pct = float((bytes_downloaded / content_length) * 100)
                            progress_pct = max(0.0, min(progress_pct, 99.0))
                        notify("downloading", "Download...", progress_pct)
                        await Scheduler.yield_control()

                response.close()
                os.sync()
                await Scheduler.yield_control()

                self.logger.info("Download complete")
                notify("downloading", "Download complete", 100)

                if expected_checksum:
                    self.logger.info("Verifying download integrity")
                    notify("verifying", "Verifying download integrity...", None)

                    async def _run_verification() -> tuple[bool, str]:
                        return await self.verify_checksum(
                            zip_path,
                            expected_checksum,
                            progress_callback=progress_callback,
                            service_callback=service_callback,
                        )

                    if self.pixel_controller:
                        async with self.pixel_controller.indicate_operation("verifying"):
                            checksum_valid, checksum_msg = await _run_verification()
                    else:
                        checksum_valid, checksum_msg = await _run_verification()

                    if not checksum_valid:
                        self.logger.error(f"Checksum verification failed: {checksum_msg}")
                        notify("error", f"Verification failed: {checksum_msg}", None)
                        if "mismatch" in checksum_msg.lower():
                            self.logger.critical("SECURITY WARNING: Downloaded file may be corrupted or tampered with")
                        # Full cleanup on checksum failure
                        self._cleanup_pending_update()
                        self._record_failed_update(checksum_msg)
                        return False, checksum_msg

                    self.logger.info(checksum_msg)
                    notify("verifying", "Verification complete", 100)
                else:
                    self.logger.warning("No checksum in manifest - update may be from older release")

                try:
                    from utils.zipfile_lite import ZipFile

                    self.logger.info("Extracting update files")
                    notify("unpacking", "Extracting update files...", 0)
                    await Scheduler.yield_control()

                    with ZipFile(zip_path) as zf:
                        all_files = zf.namelist()
                        files_to_extract = [
                            f for f in all_files if not any(part.startswith(".") for part in f.split("/"))
                        ]

                        self.logger.debug(f"ZIP contains {len(all_files)} files")
                        if len(files_to_extract) < len(all_files):
                            self.logger.debug(f"Skipping {len(all_files) - len(files_to_extract)} hidden files")

                        file_count = 0
                        total_files = len(files_to_extract)
                        for file_count, filename in enumerate(files_to_extract, start=1):
                            # Extract to staging directory first (atomic staging)
                            zf.extract(filename, update_install.PENDING_STAGING_DIR)

                            if file_count % 3 == 0 or file_count == total_files:
                                progress_pct = (file_count / total_files) * 100 if total_files else None
                                notify("unpacking", f"Extracting files... ({file_count}/{total_files})", progress_pct)
                            await Scheduler.yield_control()

                    os.sync()
                    await Scheduler.yield_control()

                    self.logger.info("Extraction complete")
                    notify("unpacking", "Extraction complete", 100)

                    manifest_path = f"{update_install.PENDING_STAGING_DIR}/manifest.json"
                    try:
                        with open(manifest_path) as f:  # type: ignore[assignment]
                            manifest = json.load(f)
                        self.logger.info(f"Manifest validated (version: {manifest.get('version', 'unknown')})")
                    except (OSError, ValueError, KeyError) as e:
                        self.logger.error(f"Extracted manifest.json is corrupted or invalid: {e}")
                        with suppress(OSError):
                            os.remove(zip_path)
                        self._cleanup_pending_update()
                        error_msg = f"Invalid manifest: {e}"
                        self._record_failed_update(error_msg)
                        return False, error_msg

                    self.logger.debug("Validating extracted update contains all critical files")
                    notify("unpacking", "Validating update package...", None)

                    # Check if this is a script-only release
                    if manifest.get("script_only_release", False):
                        # Script-only releases only need manifest.json
                        # Pre-install script will be validated separately
                        all_present: bool = True
                        missing_files: List[str] = []
                    else:
                        # Normal validation for full releases
                        all_present, missing_files = validate_files(update_install.PENDING_STAGING_DIR, CRITICAL_FILES)

                    if not all_present:
                        self.logger.error("Update package is incomplete")
                        self.logger.error(f"Missing {len(missing_files)} critical files:")
                        for missing in missing_files[:10]:
                            self.logger.error(f"  - {missing}")
                        if len(missing_files) > 10:
                            self.logger.error(f"  ... and {len(missing_files) - 10} more")
                        self.logger.error("Installation would brick the device - aborting")
                        notify("error", "Update package incomplete", None)
                        with suppress(OSError):
                            os.remove(zip_path)
                        self._cleanup_pending_update()
                        error_msg = "Update package incomplete"
                        self._record_failed_update(error_msg, version=manifest.get("version"))
                        return False, error_msg

                    self.logger.info("All critical files present in update")

                    # Remove ZIP file before atomic rename to free space
                    with suppress(OSError):
                        os.remove(zip_path)
                    os.sync()

                    # Atomic staging: rename .staging to root
                    # This ensures boot.py only sees a complete update
                    self.logger.debug("Performing atomic rename: .staging -> root")
                    try:
                        os.rename(update_install.PENDING_STAGING_DIR, update_install.PENDING_ROOT_DIR)
                    except OSError as e:
                        self.logger.error(f"Failed to rename staging to root: {e}")
                        self._cleanup_pending_update()
                        error_msg = f"Staging rename failed: {e}"
                        self._record_failed_update(error_msg, version=manifest.get("version"))
                        return False, error_msg

                    # Write ready marker with manifest hash for boot verification
                    manifest_hash = expected_checksum or "no-checksum"
                    self._write_ready_marker(manifest_hash)

                    os.sync()
                    await Scheduler.yield_control()

                    self.logger.info("Update ready for installation")
                    notify("complete", "Update ready for installation", 100)
                    return True, "Update ready for installation"

                except Exception as e:
                    self.logger.error(f"Error extracting update: {e}")
                    traceback.print_exception(e)
                    notify("error", f"Extraction failed: {e}", None)
                    # Full cleanup on extraction failure
                    self._cleanup_pending_update()
                    error_msg = f"Extraction error: {e}"
                    self._record_failed_update(error_msg)
                    return False, error_msg

            except (AttributeError, TypeError, NameError) as e:
                self.logger.critical(f"Programming error in download_update: {e}")
                traceback.print_exception(e)
                notify("error", f"Download failed: {e}", None)
                self._cleanup_pending_update()
                self._record_failed_update(f"Programming error: {e}")
                raise RuntimeError(f"Unrecoverable error in update download: {e}") from e
            except Exception as e:
                self.logger.error(f"Error downloading update: {e}")
                traceback.print_exception(e)
                notify("error", f"Download failed: {e}", None)
                # Full cleanup on any failure
                self._cleanup_pending_update()
                error_msg = str(e)
                self._record_failed_update(error_msg)
                return False, error_msg

        if self.pixel_controller:
            self.logger.debug("LED indicator: flashing blue/green during download and verification")
            async with self.pixel_controller.indicate_operation("downloading"):
                return await _execute_download()

        return await _execute_download()

    def schedule_next_update_check(
        self, interval_hours: float | None = None, delay_seconds: float | None = None
    ) -> float:
        """
        Calculate when the next scheduled update check should occur.

        Args:
            interval_hours: Hours until next check (default: from settings)
            delay_seconds: Optional explicit delay in seconds for the next check.
                            Overrides interval_hours when provided.

        Returns:
            float: Monotonic timestamp for next check
        """
        if delay_seconds is not None:
            try:
                delay_seconds = float(delay_seconds)
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid delay_seconds '{delay_seconds}' supplied; falling back to interval.")
                delay_seconds = None

        if delay_seconds is not None:
            delay_seconds = max(0.0, delay_seconds)
            next_check = time.monotonic() + delay_seconds
            self.logger.debug(f"Next update check scheduled in {delay_seconds:.1f} seconds")
            return next_check

        if interval_hours is None:
            try:
                interval_hours = int(os.getenv("SYSTEM_UPDATE_CHECK_INTERVAL", "24"))
            except ValueError:
                interval_hours = 24

        try:
            # Convert to seconds and add to current monotonic time
            seconds_until = interval_hours * 3600
            next_check = time.monotonic() + seconds_until

            self.logger.info(f"Next update check scheduled in {interval_hours} hours")
            return next_check

        except Exception as e:
            self.logger.error(f"Error scheduling update check: {e}")
            # Fallback: check again in 24 hours
            return time.monotonic() + (24 * 3600)

    def should_check_now(self) -> bool:
        """
        Check if it's time for a scheduled update check.

        Returns:
            bool: True if scheduled check time has arrived
        """
        if self.next_update_check is None:
            return False

        return time.monotonic() >= self.next_update_check

    async def check_download_and_reboot(
        self,
        delay_seconds: float = 2,
        progress_callback: Callable[[str, str, float | None], None] | None = None,
        service_callback: Callable[[], None] | None = None,
    ) -> None:
        """
        Centralized OTA update workflow: check, download, and hard reboot to install.

        This is the ONLY method that should be used to trigger OTA updates to ensure
        consistency and reliability across all update paths (initial boot, scheduled checks).

        CRITICAL: Uses microcontroller.reset() (hard reset) to ensure boot.py runs.
        Never use supervisor.reload() (soft reboot) as it skips boot.py.

        Args:
            delay_seconds: Seconds to wait before rebooting (default: 2)
            progress_callback: Optional callback for progress reporting
            service_callback: Optional callback to service background tasks

        Returns:
            bool: True if update is available and download succeeded (device will reboot),
                  False if no update or download failed (caller should continue normally)
        """
        try:
            # Check for updates
            update_info = self.check_for_updates()

            if not update_info:
                self.logger.debug("No updates available")
                return

            # Update available
            self.logger.info(f"Update available: {update_info['version']}")
            self.logger.info(f"Release notes: {update_info.get('release_notes', 'No release notes')}")
            self.logger.info("Downloading update")

            # Download and extract with checksum verification
            # download_update() uses cached info from check_for_updates()
            if await self.download_update(progress_callback=progress_callback, service_callback=service_callback):
                self.logger.info("Update downloaded successfully")
                self.logger.info(f"Rebooting in {delay_seconds} seconds to install update")
                await Scheduler.sleep(delay_seconds)

                # CRITICAL: Hard reset required for boot.py to run and install update
                # DO NOT use supervisor.reload() as it skips boot.py
                microcontroller.reset()
                # Never reaches here - device reboots

            else:
                self.logger.error("Update download failed, continuing with current version")

        except Exception as e:
            self.logger.error(f"Error during update check: {e}")
            traceback.print_exception(e)
