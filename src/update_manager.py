"""
OTA Update Manager for WICID firmware.

Handles checking for firmware updates, downloading update packages,
extracting them to /pending_update/root/, and managing the update process.

CRITICAL: This module is the SINGLE SOURCE OF TRUTH for all OTA update operations.

Usage:
    update_manager = UpdateManager(session)
    update_manager.check_download_and_reboot()  # Handles everything, reboots if update found

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

import os
import time
import json
import traceback
import microcontroller
import adafruit_hashlib as hashlib
from utils import (
    get_machine_type,
    get_os_version_string,
    check_release_compatibility
)


class UpdateManager:
    """Manages over-the-air firmware updates."""
    
    PENDING_UPDATE_DIR = "/pending_update"
    PENDING_ROOT_DIR = "/pending_update/root"
    RECOVERY_DIR = "/recovery"
    MIN_FREE_SPACE_BYTES = 200000  # ~200KB buffer for operations
    
    # Critical files that MUST exist for device to boot and function
    # Missing any of these will brick the device or prevent updates
    CRITICAL_FILES = {
        # Boot-critical: Required for boot.py to succeed
        "/boot.py",              # CircuitPython requires source .py file
        "/boot_support.mpy",     # Imported by boot.py
        
        # Runtime-critical: Required for code.py to succeed
        "/code.py",              # CircuitPython requires source .py file
        "/code_support.mpy",     # Imported by code.py
        
        # System-critical: Required for device configuration and updates
        "/settings.toml",        # System configuration, loaded at boot
        "/manifest.json",        # Update metadata, validated during installation
        "/utils.mpy",            # Compatibility checks, device identification
        "/pixel_controller.mpy", # LED feedback during boot and updates
        
        # Network-critical: Required to download updates
        "/wifi_manager.mpy",     # WiFi connection for OTA downloads
        
        # Update-critical: Required for OTA updates to function
        "/zipfile_lite.mpy",     # Required to extract update ZIPs
        "/update_manager.mpy",   # Required for update checks and downloads
        
        # Library dependencies: Required by critical modules
        "/lib/neopixel.mpy",     # Required by pixel_controller.mpy
        "/lib/adafruit_requests.mpy",        # Required by wifi_manager.mpy for HTTP
        "/lib/adafruit_connection_manager.mpy",  # Required by adafruit_requests
        "/lib/adafruit_hashlib/__init__.mpy",  # Required by update_manager.mpy for checksum verification
    }
    
    def __init__(self, session=None):
        """
        Initialize the update manager.
        
        Args:
            session: Optional HTTP session for making requests
        """
        self.session = session
        self.next_update_check = None
        self._download_flash_start = None
        
        # Access singleton for LED feedback (optional, gracefully handles if unavailable)
        try:
            from pixel_controller import PixelController
            self.pixel_controller = PixelController()
        except (ImportError, Exception):
            self.pixel_controller = None
    
    @staticmethod
    def validate_critical_files():
        """
        Validate that all critical system files are present after installation.
        
        This method is called after moving files during update installation to ensure
        the device will boot and function correctly. Missing critical files will brick
        the device or prevent future updates.
        
        Returns:
            tuple: (bool, list) - (all_present, missing_files)
                - all_present: True if all critical files exist
                - missing_files: List of missing file paths (empty if all present)
        """
        missing_files = []
        
        for file_path in UpdateManager.CRITICAL_FILES:
            try:
                os.stat(file_path)
            except OSError:
                missing_files.append(file_path)
        
        return (len(missing_files) == 0, missing_files)
    
    @staticmethod
    def recovery_exists():
        """
        Check if recovery backup directory exists and contains files.
        
        Returns:
            bool: True if recovery backup exists with files
        """
        try:
            files = os.listdir(UpdateManager.RECOVERY_DIR)
            return len(files) > 0
        except OSError:
            return False
    
    @staticmethod
    def validate_recovery_backup():
        """
        Validate that recovery backup contains all critical files.
        
        Returns:
            tuple: (bool, list) - (all_present, missing_files)
                - all_present: True if all critical files exist in recovery
                - missing_files: List of missing file paths (empty if all present)
        """
        if not UpdateManager.recovery_exists():
            return (False, list(UpdateManager.CRITICAL_FILES))
        
        missing_files = []
        
        for file_path in UpdateManager.CRITICAL_FILES:
            # Convert root path to recovery path
            recovery_path = UpdateManager.RECOVERY_DIR + file_path
            try:
                os.stat(recovery_path)
            except OSError:
                missing_files.append(file_path)
        
        return (len(missing_files) == 0, missing_files)
    
    @staticmethod
    def create_recovery_backup():
        """
        Create or update recovery backup of critical system files.
        
        Backs up only critical files needed for device to boot and perform updates.
        Recovery backup is persistent and only updated on successful installations.
        
        Returns:
            tuple: (bool, str) - (success, message)
        """
        try:
            # Create recovery directory if it doesn't exist
            try:
                os.mkdir(UpdateManager.RECOVERY_DIR)
                print(f"Created recovery directory: {UpdateManager.RECOVERY_DIR}")
            except OSError:
                pass  # Directory already exists
            
            backed_up_count = 0
            failed_files = []
            
            for file_path in UpdateManager.CRITICAL_FILES:
                try:
                    # Determine if it's a file or directory
                    is_dir = False
                    try:
                        os.listdir(file_path)
                        is_dir = True
                    except (OSError, NotImplementedError):
                        pass
                    
                    if is_dir:
                        # Skip directories (we only backup files)
                        continue
                    
                    # Read source file
                    with open(file_path, 'rb') as src:
                        content = src.read()
                    
                    # Construct recovery path with directory structure
                    recovery_path = UpdateManager.RECOVERY_DIR + file_path
                    recovery_dir = '/'.join(recovery_path.split('/')[:-1])
                    
                    # Create parent directories in recovery if needed
                    if recovery_dir and recovery_dir != UpdateManager.RECOVERY_DIR:
                        parts = recovery_dir.split('/')
                        current_path = ""
                        for part in parts:
                            if not part:
                                continue
                            current_path += "/" + part
                            try:
                                os.mkdir(current_path)
                            except OSError:
                                pass  # Directory already exists
                    
                    # Write to recovery location
                    with open(recovery_path, 'wb') as dst:
                        dst.write(content)
                    
                    backed_up_count += 1
                    
                except Exception as e:
                    failed_files.append(f"{file_path}: {e}")
            
            # Sync filesystem
            os.sync()
            
            if failed_files:
                message = f"Partial backup: {backed_up_count} files backed up, {len(failed_files)} failed"
                print(f"⚠ {message}")
                for failure in failed_files:
                    print(f"  - {failure}")
                return (False, message)
            else:
                message = f"Recovery backup complete: {backed_up_count} critical files backed up"
                print(f"✓ {message}")
                return (True, message)
                
        except Exception as e:
            message = f"Recovery backup failed: {e}"
            print(f"✗ {message}")
            traceback.print_exception(e)
            return (False, message)
    
    @staticmethod
    def restore_from_recovery():
        """
        Restore critical files from recovery backup to root.
        
        Called when boot detects missing critical files. This is a last-resort
        recovery mechanism to prevent device bricking.
        
        Returns:
            tuple: (bool, str) - (success, message)
        """
        try:
            if not UpdateManager.recovery_exists():
                return (False, "No recovery backup found")
            
            print("=" * 50)
            print("CRITICAL: Restoring from recovery backup")
            print("=" * 50)
            
            restored_count = 0
            failed_files = []
            
            for file_path in UpdateManager.CRITICAL_FILES:
                recovery_path = UpdateManager.RECOVERY_DIR + file_path
                
                try:
                    # Check if recovery file exists
                    try:
                        os.stat(recovery_path)
                    except OSError:
                        # File not in recovery, skip
                        continue
                    
                    # Check if it's a directory
                    is_dir = False
                    try:
                        os.listdir(recovery_path)
                        is_dir = True
                    except (OSError, NotImplementedError):
                        pass
                    
                    if is_dir:
                        continue
                    
                    # Read recovery file
                    with open(recovery_path, 'rb') as src:
                        content = src.read()
                    
                    # Create parent directories if needed
                    file_dir = '/'.join(file_path.split('/')[:-1])
                    if file_dir and file_dir != '/':
                        parts = file_dir.split('/')
                        current_path = ""
                        for part in parts:
                            if not part:
                                continue
                            current_path += "/" + part
                            try:
                                os.mkdir(current_path)
                            except OSError:
                                pass
                    
                    # Write to root location
                    with open(file_path, 'wb') as dst:
                        dst.write(content)
                    
                    restored_count += 1
                    print(f"  Restored: {file_path}")
                    
                except Exception as e:
                    failed_files.append(f"{file_path}: {e}")
            
            # Sync filesystem
            os.sync()
            
            print("=" * 50)
            
            if failed_files:
                message = f"Partial recovery: {restored_count} files restored, {len(failed_files)} failed"
                print(f"⚠ {message}")
                for failure in failed_files:
                    print(f"  - {failure}")
                return (False, message)
            else:
                message = f"Recovery complete: {restored_count} critical files restored"
                print(f"✓ {message}")
                return (True, message)
                
        except Exception as e:
            message = f"Recovery restoration failed: {e}"
            print(f"✗ {message}")
            traceback.print_exception(e)
            return (False, message)
    
    @staticmethod
    def check_disk_space(required_bytes):
        """
        Check if sufficient disk space is available.
        
        Args:
            required_bytes: Minimum bytes required
        
        Returns:
            tuple: (bool, str) - (sufficient, message)
        """
        try:
            stat = os.statvfs('/')
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
    
    @staticmethod
    def validate_extracted_update(extracted_dir):
        """
        Validate that extracted update contains all critical files.
        
        Called after extraction but before installation to ensure the update
        package is complete and won't brick the device.
        
        Args:
            extracted_dir: Directory containing extracted update files
        
        Returns:
            tuple: (bool, list) - (all_present, missing_files)
        """
        missing_files = []
        
        for file_path in UpdateManager.CRITICAL_FILES:
            # Convert root path to extracted directory path
            extracted_path = extracted_dir + file_path
            
            try:
                os.stat(extracted_path)
            except OSError:
                missing_files.append(file_path)
        
        return (len(missing_files) == 0, missing_files)
    
    def calculate_sha256(self, file_path, chunk_size=65536):
        """
        Calculate SHA-256 checksum of a file using adafruit_hashlib.
        
        Optimized for maximum speed with frequent LED feedback.
        Uses large chunks for speed, but updates LED based on time for smoothness.
        
        Args:
            file_path: Path to file to checksum
            chunk_size: Bytes to read per iteration (default: 64KB for maximum speed)
        
        Returns:
            str: Hexadecimal SHA-256 checksum, or None on error
        """
        try:
            # Get file size for progress indication
            file_size = os.stat(file_path)[6]  # st_size
            print(f"  File size: {file_size / 1024:.1f} KB")
            
            start_time = time.monotonic()
            sha256 = hashlib.sha256()
            bytes_processed = 0
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sha256.update(chunk)
                    bytes_processed += len(chunk)
                    
                    # Update LED based on time - ensures consistent animation
                    self._update_download_led()
            
            elapsed = time.monotonic() - start_time
            print(f"  Checksum calculated in {elapsed:.1f} seconds")
            
            return sha256.hexdigest()
        except Exception as e:
            print(f"Error calculating checksum: {e}")
            traceback.print_exception(e)
            return None
    
    def verify_checksum(self, file_path, expected_checksum):
        """
        Verify file matches expected SHA-256 checksum using adafruit_hashlib.
        
        Args:
            file_path: Path to file to verify
            expected_checksum: Expected SHA-256 hex string
        
        Returns:
            tuple: (bool, str) - (matches, message)
        """
        if not expected_checksum:
            return (False, "No checksum provided - update manifest may be from older version")
        
        actual_checksum = self.calculate_sha256(file_path)
        
        if actual_checksum is None:
            return (False, "Failed to calculate checksum")
        
        if actual_checksum.lower() == expected_checksum.lower():
            return (True, f"Checksum verified: {actual_checksum[:16]}...")
        else:
            return (False, f"Checksum mismatch: expected {expected_checksum[:16]}..., got {actual_checksum[:16]}...")
    
    def _determine_release_channel(self):
        """
        Determine which release channel to use.
        
        Returns:
            str: "development" if /development file exists, else "production"
        """
        try:
            with open("/development", "r"):
                return "development"
        except OSError:
            return "production"
    
    def check_for_updates(self):
        """
        Check if a newer compatible version is available for this device.
        
        Uses device self-identification and multi-platform manifest format.
        
        Returns:
            dict or None: Update info dict with keys 'version', 'zip_url', 'release_notes'
                         if update is available, otherwise None
        """
        if not self.session:
            print("No HTTP session available for update check")
            return None
        
        try:
            # Get device characteristics at runtime
            device_machine = get_machine_type()
            device_os = get_os_version_string()
            current_version = os.getenv("VERSION", "0.0.0")
            manifest_url = os.getenv("SYSTEM_UPDATE_MANIFEST_URL")
            
            if not manifest_url:
                print("No update manifest URL configured")
                return None
            
            print(f"Checking for updates:")
            print(f"  Machine: {device_machine}")
            print(f"  OS: {device_os}")
            print(f"  Version: {current_version}")
            
            # Get weather_zip for user-agent
            try:
                with open("/secrets.json", "r") as f:
                    secrets = json.load(f)
                    weather_zip = secrets.get("weather_zip", "")
            except:
                weather_zip = ""
            
            # Include device info in User-Agent header
            user_agent = f"WICID/{current_version} ({device_machine}; {device_os}; ZIP:{weather_zip})"
            headers = {"User-Agent": user_agent}
            
            # Fetch the releases manifest
            response = self.session.get(manifest_url, headers=headers)
            
            # Check if response is successful
            if response.status_code != 200:
                print(f"Update check failed: HTTP {response.status_code}")
                response.close()
                return None
            
            # Try to parse JSON
            try:
                manifest = response.json()
            except (ValueError, AttributeError) as json_err:
                print(f"Invalid JSON response from manifest URL")
                response.close()
                return None
            
            response.close()
            
            # Determine which release channel to use
            channel = self._determine_release_channel()
            print(f"Using release channel: {channel}")
            
            # Find compatible releases
            releases_array = manifest.get("releases", [])
            
            for release_entry in releases_array:
                # Check if this release entry has the requested channel
                if channel not in release_entry:
                    continue
                
                release_info = release_entry[channel]
                
                # Prepare release data for compatibility check
                release_data = {
                    "target_machine_types": release_entry.get("target_machine_types", []),
                    "target_operating_systems": release_entry.get("target_operating_systems", []),
                    "version": release_info["version"]
                }
                
                # Use DRY compatibility check
                is_compatible, error_msg = check_release_compatibility(release_data, current_version)
                
                if is_compatible:
                    print(f"Update available: {current_version} -> {release_info['version']}")
                    return {
                        "version": release_info["version"],
                        "zip_url": release_info.get("zip_url"),
                        "sha256": release_info.get("sha256"),
                        "release_notes": release_info.get("release_notes", ""),
                        "target_machine_types": release_entry.get("target_machine_types", []),
                        "target_operating_systems": release_entry.get("target_operating_systems", [])
                    }
                else:
                    print(f"Skipping {release_info['version']}: {error_msg}")
            
            print("No compatible updates available")
            return None
                
        except Exception as e:
            print(f"Error checking for updates: {e}")
            traceback.print_exception(e)
            return None
    
    def _update_download_led(self, force=False):
        """
        Update LED during download operations (flashes blue/green).
        
        Uses time-based throttling to flash frequently without impacting performance.
        Just calls tick() which handles time-based animation internally.
        
        Args:
            force: If True, update LED regardless of throttle (default: False)
        """
        if not self.pixel_controller or self._download_flash_start is None:
            return
        
        # The pixel controller's tick() method handles time-based updates internally
        # We can call it frequently without performance penalty - it self-throttles
        self.pixel_controller.tick()
    
    def download_update(self, zip_url, expected_checksum=None):
        """
        Download update package and extract to /pending_update/root/.
        
        Args:
            zip_url: URL of the zip file to download
            expected_checksum: Optional SHA-256 checksum to verify download
        
        Returns:
            bool: True if download and extraction successful, False otherwise
        """
        if not self.session:
            print("No HTTP session available for download")
            return False
        
        # Start LED flashing for download phase
        if self.pixel_controller:
            self._download_flash_start = time.monotonic()
            # Start the flashing animation
            self.pixel_controller.start_flashing([(0, 0, 255), (0, 255, 0)], rate=4)
            print("LED indicator: flashing blue/green during download and verification")
        
        try:
            # Check disk space before download
            # Require MIN_FREE_SPACE_BYTES as buffer for operations
            space_ok, space_msg = self.check_disk_space(self.MIN_FREE_SPACE_BYTES)
            print(f"Disk space check: {space_msg}")
            
            if not space_ok:
                print("✗ Insufficient disk space for update")
                print(f"  Please free up space and try again")
                return False
            
            self._update_download_led()
            
            # Create pending_update directory structure
            try:
                os.mkdir(self.PENDING_UPDATE_DIR)
            except OSError:
                pass  # Directory already exists
            
            try:
                os.mkdir(self.PENDING_ROOT_DIR)
            except OSError:
                pass  # Directory already exists
            
            # Download to a temporary ZIP file
            zip_path = f"{self.PENDING_UPDATE_DIR}/update.zip"
            
            print(f"Downloading update: {zip_url}")
            print(f"Saving to: {zip_path}")
            
            self._update_download_led()
            
            # Download the file
            response = self.session.get(zip_url)
            
            # Save to file in chunks to handle large files reliably
            # Use larger chunks for faster download
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:  # filter out keep-alive chunks
                        f.write(chunk)
                        # Update LED based on time (every 0.1s), not chunks - smooth and fast
                        self._update_download_led()
            
            response.close()
            
            # Sync to ensure file is written
            os.sync()
            
            print("✓ Download complete")
            self._update_download_led()
            
            # Verify checksum if provided
            if expected_checksum:
                print("Verifying download integrity...")
                # Ensure LED is still flashing for checksum phase
                if self.pixel_controller and self._download_flash_start is not None:
                    if self.pixel_controller._mode != self.pixel_controller.MODE_FLASHING:
                        self.pixel_controller.start_flashing([(0, 0, 255), (0, 255, 0)], rate=4)
                self._update_download_led()
                checksum_valid, checksum_msg = self.verify_checksum(zip_path, expected_checksum)
                
                if not checksum_valid:
                    print(f"✗ Checksum verification failed: {checksum_msg}")
                    
                    # If checksum was provided but doesn't match, this is a security issue
                    if "mismatch" in checksum_msg.lower():
                        print("SECURITY WARNING: Downloaded file may be corrupted or tampered with")
                    
                    # Clean up corrupted download
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass
                    
                    return False
                
                print(f"✓ {checksum_msg}")
                self._update_download_led()
            else:
                print("⚠ No checksum in manifest - update may be from older release")
            
            # Extract ZIP to /pending_update/root/
            try:
                from zipfile_lite import ZipFile
                
                print("Extracting update files...")
                self._update_download_led()
                
                with ZipFile(zip_path) as zf:
                    all_files = zf.namelist()
                    # Filter out hidden files (starting with .)
                    files_to_extract = [f for f in all_files if not any(part.startswith('.') for part in f.split('/'))]
                    
                    print(f"ZIP contains {len(all_files)} files")
                    if len(files_to_extract) < len(all_files):
                        print(f"Skipping {len(all_files) - len(files_to_extract)} hidden files")
                    
                    # Extract each file individually to filter out dotfiles
                    file_count = 0
                    for filename in files_to_extract:
                        zf.extract(filename, self.PENDING_ROOT_DIR)
                        
                        # Update LED every 3 files for visible feedback
                        file_count += 1
                        if file_count % 3 == 0:
                            self._update_download_led()
                
                # Sync filesystem immediately after extraction to prevent corruption
                os.sync()
                print("✓ Extraction complete")
                self._update_download_led()
                
                # Validate the extracted manifest.json
                manifest_path = f"{self.PENDING_ROOT_DIR}/manifest.json"
                try:
                    with open(manifest_path, "r") as f:
                        manifest = json.load(f)
                    print(f"✓ Manifest validated (version: {manifest.get('version', 'unknown')})")
                    self._update_download_led()
                except (OSError, ValueError, KeyError) as e:
                    print(f"✗ Extracted manifest.json is corrupted or invalid: {e}")
                    # Clean up corrupted extraction
                    os.remove(zip_path)
                    return False
                
                # Validate that all critical files are present in extracted update
                print("Validating extracted update contains all critical files...")
                self._update_download_led()
                all_present, missing_files = self.validate_extracted_update(self.PENDING_ROOT_DIR)
                
                if not all_present:
                    print(f"✗ Update package is incomplete")
                    print(f"  Missing {len(missing_files)} critical files:")
                    for missing in missing_files[:10]:
                        print(f"    - {missing}")
                    if len(missing_files) > 10:
                        print(f"    ... and {len(missing_files) - 10} more")
                    print("  Installation would brick the device - aborting")
                    
                    # Clean up incomplete extraction
                    os.remove(zip_path)
                    return False
                
                print(f"✓ All critical files present in update")
                
                # Remove the ZIP file (we only need the extracted files)
                os.remove(zip_path)
                
                # Final sync
                os.sync()
                
                print(f"✓ Update ready for installation")
                return True
                
            except Exception as e:
                print(f"Error extracting update: {e}")
                traceback.print_exception(e)
                
                # Clean up on error
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                
                return False
            
        except Exception as e:
            print(f"Error downloading update: {e}")
            traceback.print_exception(e)
            
            # Clean up partial download
            try:
                os.remove(f"{self.PENDING_UPDATE_DIR}/update.zip")
            except OSError:
                pass  # File doesn't exist or can't be removed
            
            return False
    
    def schedule_next_update_check(self, interval_hours=None):
        """
        Calculate when the next scheduled update check should occur.
        
        Args:
            interval_hours: Hours until next check (default: from settings)
        
        Returns:
            float: Monotonic timestamp for next check
        """
        if interval_hours is None:
            try:
                interval_hours = int(os.getenv("SYSTEM_UPDATE_CHECK_INTERVAL", "24"))
            except:
                interval_hours = 24
        
        try:
            # Convert to seconds and add to current monotonic time
            seconds_until = interval_hours * 3600
            next_check = time.monotonic() + seconds_until
            
            print(f"Next update check scheduled in {interval_hours} hours")
            return next_check
            
        except Exception as e:
            print(f"Error scheduling update check: {e}")
            # Fallback: check again in 24 hours
            return time.monotonic() + (24 * 3600)
    
    def should_check_now(self):
        """
        Check if it's time for a scheduled update check.
        
        Returns:
            bool: True if scheduled check time has arrived
        """
        if self.next_update_check is None:
            return False
        
        return time.monotonic() >= self.next_update_check
    
    def check_download_and_reboot(self, delay_seconds=2):
        """
        Centralized OTA update workflow: check, download, and hard reboot to install.
        
        This is the ONLY method that should be used to trigger OTA updates to ensure
        consistency and reliability across all update paths (initial boot, scheduled checks).
        
        CRITICAL: Uses microcontroller.reset() (hard reset) to ensure boot.py runs.
        Never use supervisor.reload() (soft reboot) as it skips boot.py.
        
        Args:
            delay_seconds: Seconds to wait before rebooting (default: 2)
        
        Returns:
            bool: True if update is available and download succeeded (device will reboot),
                  False if no update or download failed (caller should continue normally)
        """
        if not self.session:
            print("No HTTP session available for updates")
            return False
        
        try:
            # Check for updates
            update_info = self.check_for_updates()
            
            if not update_info:
                print("No updates available")
                return False
            
            # Update available
            print(f"Update available: {update_info['version']}")
            print(f"Release notes: {update_info.get('release_notes', 'No release notes')}")
            print("Downloading update...")
            
            # Download and extract with checksum verification
            if self.download_update(update_info['zip_url'], update_info.get('sha256')):
                print("✓ Update downloaded successfully")
                print(f"Rebooting in {delay_seconds} seconds to install update...")
                time.sleep(delay_seconds)
                
                # CRITICAL: Hard reset required for boot.py to run and install update
                # DO NOT use supervisor.reload() as it skips boot.py
                microcontroller.reset()
                # Never reaches here - device reboots
                
            else:
                print("✗ Update download failed, continuing with current version")
                return False
                
        except Exception as e:
            print(f"Error during update check: {e}")
            traceback.print_exception(e)
            return False
