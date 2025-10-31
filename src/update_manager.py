"""
OTA Update Manager for WICID firmware.

Handles checking for firmware updates, downloading update packages,
extracting them to /pending_update/root/, and managing the update process.
"""

import os
import time
import json
import traceback
from utils import (
    get_machine_type,
    get_os_version_string,
    check_release_compatibility
)


class UpdateManager:
    """Manages over-the-air firmware updates."""
    
    PENDING_UPDATE_DIR = "/pending_update"
    PENDING_ROOT_DIR = "/pending_update/root"
    
    def __init__(self, session=None):
        """
        Initialize the update manager.
        
        Args:
            session: Optional HTTP session for making requests
        """
        self.session = session
        self.next_update_check = None
    
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
    
    def download_update(self, zip_url):
        """
        Download update package and extract to /pending_update/root/.
        
        Args:
            zip_url: URL of the zip file to download
        
        Returns:
            bool: True if download and extraction successful, False otherwise
        """
        if not self.session:
            print("No HTTP session available for download")
            return False
        
        try:
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
            
            # Download the file
            response = self.session.get(zip_url)
            
            # Save to file in chunks to handle large files reliably
            # CircuitPython's adafruit_requests requires reading via iter_content
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:  # filter out keep-alive chunks
                        f.write(chunk)
            
            response.close()
            
            # Sync to ensure file is written
            os.sync()
            
            print("✓ Download complete")
            
            # Extract ZIP to /pending_update/root/
            try:
                from zipfile_lite import ZipFile
                
                print("Extracting update files...")
                
                with ZipFile(zip_path) as zf:
                    all_files = zf.namelist()
                    # Filter out hidden files (starting with .)
                    files_to_extract = [f for f in all_files if not any(part.startswith('.') for part in f.split('/'))]
                    
                    print(f"ZIP contains {len(all_files)} files")
                    if len(files_to_extract) < len(all_files):
                        print(f"Skipping {len(all_files) - len(files_to_extract)} hidden files")
                    
                    # Extract each file individually to filter out dotfiles
                    for filename in files_to_extract:
                        zf.extract(filename, self.PENDING_ROOT_DIR)
                
                # Sync filesystem immediately after extraction to prevent corruption
                os.sync()
                print("✓ Extraction complete")
                
                # Validate the extracted manifest.json
                manifest_path = f"{self.PENDING_ROOT_DIR}/manifest.json"
                try:
                    with open(manifest_path, "r") as f:
                        manifest = json.load(f)
                    print(f"✓ Manifest validated (version: {manifest.get('version', 'unknown')})")
                except (OSError, ValueError, KeyError) as e:
                    print(f"Error: Extracted manifest.json is corrupted or invalid: {e}")
                    # Clean up corrupted extraction
                    os.remove(zip_path)
                    return False
                
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
