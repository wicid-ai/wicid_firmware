#!/usr/bin/env python3
"""
WICID Firmware Installer

Provides SOFT (OTA-like), HARD (full replacement), and SIMULATED OTA 
(local development testing) installation methods for WICID firmware 
packages to CIRCUITPY devices.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import glob
import argparse
import subprocess
import re
import json
import time
from pathlib import Path

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use defaults


SYSTEM_FOLDERS = ['.Trashes', '.fseventsd', '.metadata_never_index', 'System Volume Information', '.TemporaryItems', '.Spotlight-V100']
PRESERVED_FILES = ['secrets.json']


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


def print_step(text):
    """Print a formatted step message."""
    print(f"\n→ {text}")


def print_success(text):
    """Print a success message."""
    print(f"✓ {text}")


def print_error(text):
    """Print an error message."""
    print(f"✗ ERROR: {text}")


def get_web_root_directory():
    """
    Get the WICID Web root directory from environment or use default.
    
    Returns:
        Path: Path to WICID Web root directory
    """
    # Try environment variable first
    env_path = os.environ.get('LOCAL_WICID_WEB_ROOT_DIR')
    if env_path:
        return Path(env_path)
    
    # Use default: ../wicid_web relative to project root
    project_root = Path(__file__).parent
    return project_root.parent / "wicid_web"


def detect_circuitpy_drive():
    """
    Auto-detect the CIRCUITPY drive across different operating systems.
    
    Returns:
        Path or None: Path to CIRCUITPY drive if found, None otherwise
    """
    # Check macOS
    macos_path = Path("/Volumes/CIRCUITPY")
    if macos_path.exists() and macos_path.is_dir():
        return macos_path
    
    # Check Linux - /media/username/CIRCUITPY
    media_paths = glob.glob("/media/*/CIRCUITPY")
    if media_paths:
        return Path(media_paths[0])
    
    # Check Linux - /mnt/CIRCUITPY
    mnt_path = Path("/mnt/CIRCUITPY")
    if mnt_path.exists() and mnt_path.is_dir():
        return mnt_path
    
    # Check Windows - try common drive letters
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            drive_path = Path(f"{letter}:/")
            if drive_path.exists():
                # Check if this drive is named CIRCUITPY
                try:
                    # On Windows, we can check the volume label
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    volume_name_buffer = ctypes.create_unicode_buffer(1024)
                    kernel32.GetVolumeInformationW(
                        f"{letter}:\\",
                        volume_name_buffer,
                        ctypes.sizeof(volume_name_buffer),
                        None, None, None, None, 0
                    )
                    if volume_name_buffer.value == "CIRCUITPY":
                        return drive_path
                except:
                    pass
    
    return None


def list_circuitpy_contents(circuitpy_path):
    """
    List all files and directories on CIRCUITPY that would be deleted.
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
    
    Returns:
        list: List of paths that would be deleted
    """
    to_delete = []
    
    try:
        for item in os.listdir(circuitpy_path):
            # Skip system folders and preserved files
            if item in SYSTEM_FOLDERS or item in PRESERVED_FILES:
                continue
            
            # Skip all hidden files (starting with .)
            if item.startswith('.'):
                continue
            
            item_path = circuitpy_path / item
            relative_path = str(item_path.relative_to(circuitpy_path))
            
            # Add trailing slash for directories
            if item_path.is_dir():
                relative_path += '/'
            
            to_delete.append(relative_path)
    except Exception as e:
        print_error(f"Could not list CIRCUITPY contents: {e}")
    
    return sorted(to_delete)


def delete_circuitpy_contents(circuitpy_path):
    """
    Delete all files and directories on CIRCUITPY except preserved items.
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
    
    Raises:
        OSError: If filesystem is read-only or deletion fails
    """
    print_step("Deleting files on CIRCUITPY drive...")
    
    deleted_count = 0
    
    for item in os.listdir(circuitpy_path):
        # Skip system folders and preserved files
        if item in SYSTEM_FOLDERS or item in PRESERVED_FILES:
            print(f"  Preserving: {item}")
            continue
        
        # Skip all hidden files - they're system artifacts
        # These will be cleaned up separately after all operations complete
        if item.startswith('.'):
            continue
        
        item_path = circuitpy_path / item
        
        try:
            if item_path.is_dir():
                shutil.rmtree(item_path, ignore_errors=False)
                print(f"  Deleted directory: {item}")
                deleted_count += 1
            else:
                item_path.unlink()
                print(f"  Deleted file: {item}")
                deleted_count += 1
        except OSError as e:
            # Check for read-only filesystem error
            if e.errno == 30:  # EROFS - Read-only file system
                raise OSError(
                    "CIRCUITPY drive is READ-ONLY. "
                    "The device must be in Safe Mode to allow file modifications.\n\n"
                    "To enter Safe Mode:\n"
                    "  1. Unplug the device from USB\n"
                    "  2. Hold the BOOT button (or button on the board)\n"
                    "  3. While holding the button, plug in USB\n"
                    "  4. Keep holding until the LED turns yellow/orange\n"
                    "  5. Release the button\n\n"
                    "The device is now in Safe Mode and the filesystem is writable.\n"
                    "Run this installer again."
                ) from e
            else:
                print_error(f"Could not delete {item}: {e}")
                raise
    
    print_success(f"Deleted {deleted_count} items from CIRCUITPY")


def extract_zip_to_temp(zip_path):
    """
    Extract ZIP file to a temporary directory.
    
    Args:
        zip_path: Path to ZIP file
    
    Returns:
        Path: Path to temporary directory with extracted contents
    """
    print_step(f"Extracting {zip_path}...")
    
    temp_dir = Path(tempfile.mkdtemp(prefix="wicid_install_"))
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_dir)
            file_count = len(zf.namelist())
        
        print_success(f"Extracted {file_count} files to temporary directory")
        return temp_dir
    
    except Exception as e:
        print_error(f"Failed to extract ZIP: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def copy_files_to_circuitpy(source_dir, dest_dir, recursive=True):
    """
    Copy files from source to destination, maintaining directory structure.
    
    Args:
        source_dir: Source directory path
        dest_dir: Destination directory path
        recursive: If True, copy directory structure recursively
    
    Raises:
        OSError: If filesystem is read-only or copy fails
    """
    print_step(f"Copying files to {dest_dir}...")
    
    copied_count = 0
    
    try:
        for item in os.listdir(source_dir):
            # Skip all hidden files (starting with .)
            if item.startswith('.'):
                continue
            
            src_path = source_dir / item
            dst_path = dest_dir / item
            
            if src_path.is_dir():
                if recursive:
                    # Remove destination if it exists (handles stale dirs/files)
                    if dst_path.exists():
                        if dst_path.is_dir():
                            shutil.rmtree(dst_path)
                        else:
                            dst_path.unlink()
                    # Use copy_function=shutil.copy to avoid metadata issues on FAT
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True, copy_function=shutil.copy)
                    print(f"  Copied directory: {item}/")
                    copied_count += 1
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                # Remove destination if it exists (handles stale dirs/files)
                if dst_path.exists():
                    if dst_path.is_dir():
                        shutil.rmtree(dst_path)
                    else:
                        dst_path.unlink()
                # Use copy() instead of copy2() to avoid metadata issues on FAT
                shutil.copy(src_path, dst_path)
                print(f"  Copied file: {item}")
                copied_count += 1
    
    except OSError as e:
        # Check for read-only filesystem error
        if e.errno == 30:  # EROFS - Read-only file system
            raise OSError(
                "CIRCUITPY drive is READ-ONLY. "
                "The device must be in Safe Mode to allow file modifications.\n\n"
                "To enter Safe Mode:\n"
                "  1. Unplug the device from USB\n"
                "  2. Hold the BOOT button (or button on the board)\n"
                "  3. While holding the button, plug in USB\n"
                "  4. Keep holding until the LED turns yellow/orange\n"
                "  5. Release the button\n\n"
                "The device is now in Safe Mode and the filesystem is writable.\n"
                "Run this installer again."
            ) from e
        else:
            print_error(f"Error copying files: {e}")
            raise
    except Exception as e:
        print_error(f"Error copying files: {e}")
        raise
    
    print_success(f"Copied {copied_count} items")


def cleanup_macos_artifacts(circuitpy_path):
    """
    Remove hidden files from CIRCUITPY drive.
    
    macOS automatically creates ._ files and .DS_Store on FAT volumes.
    These aren't needed on the device.
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
    """
    print_step("Cleaning up hidden files...")
    
    removed_count = 0
    
    try:
        for root, dirs, files in os.walk(circuitpy_path):
            for file in files:
                if file.startswith('.'):
                    file_path = Path(root) / file
                    try:
                        file_path.unlink()
                        removed_count += 1
                    except FileNotFoundError:
                        # File already gone - that's fine
                        pass
                    except Exception as e:
                        print(f"  Could not remove {file}: {e}")
        
        if removed_count > 0:
            print_success(f"Removed {removed_count} hidden files")
        else:
            print_success("No hidden files found")
    
    except Exception as e:
        print(f"  Warning: Error during cleanup: {e}")


def validate_simulated_ota_prerequisites(web_root_dir, circuitpy_path, zip_path):
    """
    Validate all prerequisites for simulated OTA update are met.
    
    Args:
        web_root_dir: Path to WICID Web root directory
        circuitpy_path: Path to CIRCUITPY drive
        zip_path: Path to firmware ZIP file
    
    Returns:
        tuple: (bool success, str error_message)
    """
    # Check web root directory exists
    if not web_root_dir.exists():
        return False, f"WICID Web directory not found: {web_root_dir}\n\nPlease ensure the WICID Web repository exists at this location.\nYou can set a custom path with LOCAL_WICID_WEB_ROOT_DIR in .env file."
    
    if not web_root_dir.is_dir():
        return False, f"WICID Web path is not a directory: {web_root_dir}"
    
    # Check for package.json to validate it's a Node project
    package_json = web_root_dir / "package.json"
    if not package_json.exists():
        return False, f"package.json not found in: {web_root_dir}\n\nThis doesn't appear to be a Node.js project."
    
    # Check for public directory
    public_dir = web_root_dir / "public"
    if not public_dir.exists():
        return False, f"public/ directory not found in: {web_root_dir}\n\nUnable to copy files to web server."
    
    # Check firmware package exists
    if not zip_path.exists():
        return False, f"Firmware package not found: {zip_path}\n\nPlease build the firmware first."
    
    # Check releases.json exists
    releases_json = Path("releases.json")
    if not releases_json.exists():
        return False, f"releases.json not found in project root\n\nPlease build the firmware first."
    
    # Check CIRCUITPY drive is writable
    test_file = circuitpy_path / ".write_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
    except OSError as e:
        if e.errno == 30:  # EROFS
            return False, (
                "CIRCUITPY drive is READ-ONLY.\n\n"
                "The device must be in Safe Mode to allow file modifications.\n"
                "To enter Safe Mode:\n"
                "  1. Unplug the device from USB\n"
                "  2. Hold the BOOT button\n"
                "  3. While holding, plug in USB\n"
                "  4. Keep holding until LED turns yellow/orange\n"
                "  5. Release the button"
            )
        return False, f"Cannot write to CIRCUITPY drive: {e}"
    
    # Check settings.toml exists
    settings_toml = circuitpy_path / "settings.toml"
    if not settings_toml.exists():
        return False, f"settings.toml not found on CIRCUITPY drive: {settings_toml}"
    
    return True, ""


def start_wicid_web_server(web_root_dir):
    """
    Start the WICID Web application server in the background.
    
    Args:
        web_root_dir: Path to WICID Web root directory
    
    Returns:
        tuple: (subprocess.Popen process, str local_wicid_web_url)
    
    Raises:
        Exception: If server fails to start or times out
    """
    print_step(f"Starting WICID Web server from: {web_root_dir}")
    
    try:
        # Start npm run dev in background
        process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(web_root_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        print("  Waiting for server to start...")
        
        # Read output until we see "ready" with timeout
        start_time = time.time()
        timeout = 30  # seconds
        output_lines = []
        local_url = None
        
        while time.time() - start_time < timeout:
            line = process.stdout.readline()
            if not line:
                # Check if process died
                if process.poll() is not None:
                    raise Exception(f"Server process exited unexpectedly with code {process.returncode}")
                time.sleep(0.1)
                continue
            
            output_lines.append(line.strip())
            print(f"    {line.strip()}")
            
            # Check if ready
            if "ready" in line.lower():
                # Found ready marker, now look for Network URL in subsequent lines
                # Read a few more lines to find the Network URL
                for _ in range(10):
                    line = process.stdout.readline()
                    if not line:
                        break
                    output_lines.append(line.strip())
                    print(f"    {line.strip()}")
                    
                    # Look for Network URL pattern: "Network: http://IP:PORT/"
                    match = re.search(r'Network:\s+(http://[\d.]+:\d+/?)', line)
                    if match:
                        local_url = match.group(1).rstrip('/')
                        break
                
                # Exit the outer loop after finding ready
                break
        
        if local_url is None:
            process.terminate()
            raise Exception(
                f"Server started but could not find Network URL in output.\n"
                f"Server may not be configured correctly.\n"
                f"Output received:\n" + "\n".join(output_lines)
            )
        
        print_success(f"Server started at: {local_url}")
        print(f"  Server PID: {process.pid}")
        
        return process, local_url
    
    except FileNotFoundError:
        raise Exception(
            "npm command not found. Please ensure Node.js and npm are installed."
        )
    except Exception as e:
        # Try to clean up process if it exists
        try:
            if 'process' in locals() and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except:
            pass
        raise


def stop_wicid_web_server(process):
    """
    Stop the WICID Web application server.
    
    Args:
        process: subprocess.Popen process to terminate
    """
    print_step(f"Stopping WICID Web server (PID: {process.pid})...")
    
    try:
        # Try graceful shutdown first
        process.terminate()
        
        try:
            process.wait(timeout=5)
            print_success("Server stopped gracefully")
        except subprocess.TimeoutExpired:
            # Force kill if it doesn't stop
            print("  Server did not stop gracefully, forcing...")
            process.kill()
            process.wait()
            print_success("Server force stopped")
    
    except Exception as e:
        print(f"  Warning: Error stopping server: {e}")


def copy_files_to_web_public(web_root_dir, local_wicid_web_url):
    """
    Copy firmware files to web server public directory and update releases.json.
    
    Args:
        web_root_dir: Path to WICID Web root directory
        local_wicid_web_url: Local web server URL (e.g., http://10.0.0.142:8080)
    
    Raises:
        Exception: If file operations fail
    """
    print_step("Copying files to web server public directory...")
    
    public_dir = web_root_dir / "public"
    
    # Copy firmware ZIP
    src_zip = Path("releases/wicid_install.zip")
    dst_zip = public_dir / "wicid_install.zip"
    
    shutil.copy(src_zip, dst_zip)
    print(f"  Copied: wicid_install.zip -> {dst_zip}")
    
    # Read and modify releases.json
    src_releases = Path("releases.json")
    with open(src_releases, 'r') as f:
        releases_data = json.load(f)
    
    # Update all zip_url fields to point to local server
    modified_count = 0
    for release in releases_data.get("releases", []):
        if "production" in release:
            release["production"]["zip_url"] = f"{local_wicid_web_url}/wicid_install.zip"
            modified_count += 1
        if "development" in release:
            release["development"]["zip_url"] = f"{local_wicid_web_url}/wicid_install.zip"
            modified_count += 1
    
    # Write modified releases.json to public directory
    dst_releases = public_dir / "releases.json"
    with open(dst_releases, 'w') as f:
        json.dump(releases_data, f, indent=2)
    
    print(f"  Modified releases.json with {modified_count} URL(s) updated")
    print(f"  Copied: releases.json -> {dst_releases}")
    
    print_success("Files copied to web server")


def modify_circuitpy_settings(circuitpy_path, local_wicid_web_url):
    """
    Modify settings.toml on CIRCUITPY drive for local OTA testing.
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
        local_wicid_web_url: Local web server URL
    
    Raises:
        OSError: If filesystem is read-only or modification fails
    """
    print_step("Modifying CIRCUITPY settings.toml...")
    
    settings_file = circuitpy_path / "settings.toml"
    
    try:
        # Read current settings
        with open(settings_file, 'r') as f:
            content = f.read()
        
        # Replace VERSION with 0.0.0 to trigger update
        content = re.sub(
            r'VERSION\s*=\s*"[^"]*"',
            'VERSION = "0.0.0"',
            content
        )
        
        # Replace SYSTEM_UPDATE_MANIFEST_URL with local URL
        content = re.sub(
            r'SYSTEM_UPDATE_MANIFEST_URL\s*=\s*"[^"]*"',
            f'SYSTEM_UPDATE_MANIFEST_URL = "{local_wicid_web_url}/releases.json"',
            content
        )
        
        # Write back to file
        with open(settings_file, 'w') as f:
            f.write(content)
        
        print(f"  Set VERSION = \"0.0.0\"")
        print(f"  Set SYSTEM_UPDATE_MANIFEST_URL = \"{local_wicid_web_url}/releases.json\"")
        
        print_success("CIRCUITPY settings.toml updated")
    
    except OSError as e:
        if e.errno == 30:  # EROFS
            raise OSError(
                "CIRCUITPY drive is READ-ONLY.\n\n"
                "The device must be in Safe Mode to allow file modifications.\n"
                "To enter Safe Mode:\n"
                "  1. Unplug the device from USB\n"
                "  2. Hold the BOOT button\n"
                "  3. While holding, plug in USB\n"
                "  4. Keep holding until LED turns yellow/orange\n"
                "  5. Release the button"
            ) from e
        raise


def soft_update(circuitpy_path, zip_path):
    """
    Perform a SOFT update (OTA-like installation).
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
        zip_path: Path to firmware ZIP file
    
    Returns:
        bool: True if update completed successfully, False otherwise
    """
    print_header("SOFT UPDATE MODE")
    print("\nThis will prepare an OTA-like update:")
    print("1. Extract firmware package locally")
    print("2. Create /pending_update/root/ directory on CIRCUITPY")
    print("3. Copy firmware files to /pending_update/root/")
    print("4. On reboot, boot.py will install the update")
    print("\nUser data (secrets.json) will be preserved.")
    
    # Extract to temporary directory
    try:
        temp_dir = extract_zip_to_temp(zip_path)
    except Exception as e:
        print_error(f"Failed to extract firmware package: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        # Create pending_update directories on CIRCUITPY
        print_step("Creating update directories on CIRCUITPY...")
        pending_update_dir = circuitpy_path / "pending_update"
        pending_root_dir = pending_update_dir / "root"
        
        pending_update_dir.mkdir(exist_ok=True)
        pending_root_dir.mkdir(exist_ok=True)
        
        print_success("Created /pending_update/root/ on CIRCUITPY")
        
        # Copy extracted files to pending_update/root/
        copy_files_to_circuitpy(temp_dir, pending_root_dir, recursive=True)
        
        # Remove macOS metadata files from CIRCUITPY
        cleanup_macos_artifacts(circuitpy_path)
        
        print_success("SOFT update prepared successfully")
        return True
    
    except Exception as e:
        print_error(f"SOFT update failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Clean up temporary directory
        print_step("Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print_success("Cleanup complete")


def hard_update(circuitpy_path, zip_path):
    """
    Perform a HARD update (full firmware replacement).
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
        zip_path: Path to firmware ZIP file
    
    Returns:
        bool: True if update completed successfully, False if cancelled or failed
    """
    print_header("HARD UPDATE MODE")
    print("\n⚠️  WARNING: This will DELETE ALL FILES on the CIRCUITPY drive!")
    print("The following will be preserved:")
    for item in PRESERVED_FILES:
        print(f"  - {item}")
    
    # List files that will be deleted
    print("\nThe following files/directories ON CIRCUITPY will be DELETED:")
    to_delete = list_circuitpy_contents(circuitpy_path)
    
    if to_delete:
        for item in to_delete:
            print(f"  - {item}")
    else:
        print("  (no files to delete)")
    
    # Confirm with user
    print("\n" + "!" * 60)
    print("This operation will DELETE files on CIRCUITPY drive ONLY.")
    print("Your local files will NOT be affected.")
    print("!" * 60)
    
    response = input("\nType 'yes' to continue with HARD update: ").strip().lower()
    
    if response != "yes":
        print("\nHARD update cancelled.")
        return False
    
    # Extract to temporary directory
    try:
        temp_dir = extract_zip_to_temp(zip_path)
    except Exception as e:
        print_error(f"Failed to extract firmware package: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        # Clean up macOS metadata files BEFORE deletion to prevent interference
        cleanup_macos_artifacts(circuitpy_path)
        
        # Delete existing files on CIRCUITPY
        delete_circuitpy_contents(circuitpy_path)
        
        # Copy new firmware files to CIRCUITPY root
        copy_files_to_circuitpy(temp_dir, circuitpy_path, recursive=True)
        
        # Remove any newly created macOS metadata files
        cleanup_macos_artifacts(circuitpy_path)
        
        print_success("HARD update completed successfully")
        return True
    
    except OSError as e:
        # Don't print stack trace for read-only filesystem - the error message is clear
        if "READ-ONLY" in str(e):
            print_error(str(e))
        else:
            print_error(f"HARD update failed: {e}")
            import traceback
            traceback.print_exc()
        return False
    except Exception as e:
        print_error(f"HARD update failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Clean up temporary directory
        print_step("Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print_success("Cleanup complete")


def simulated_ota_update(circuitpy_path, zip_path):
    """
    Perform a SIMULATED OTA update using local WICID Web server.
    
    Args:
        circuitpy_path: Path to CIRCUITPY drive
        zip_path: Path to firmware ZIP file
    
    Returns:
        bool: True if setup completed successfully, False otherwise
    """
    print_header("SIMULATED OTA UPDATE MODE")
    print("\nThis will set up a simulated over-the-air update:")
    print("1. Start local WICID Web application server")
    print("2. Copy firmware files to web server public directory")
    print("3. Modify device settings to point to local server")
    print("4. Device will pull update from local server on reset")
    print("\nThis is useful for testing the OTA update flow in development.")
    
    process = None
    
    try:
        # Get web root directory
        web_root_dir = get_web_root_directory()
        print(f"\nUsing WICID Web directory: {web_root_dir}")
        
        # Validate prerequisites
        print_step("Validating prerequisites...")
        success, error_msg = validate_simulated_ota_prerequisites(web_root_dir, circuitpy_path, zip_path)
        
        if not success:
            print_error(error_msg)
            return False
        
        print_success("All prerequisites validated")
        
        # Start web server
        process, local_url = start_wicid_web_server(web_root_dir)
        
        # Copy files to web server
        copy_files_to_web_public(web_root_dir, local_url)
        
        # Modify CIRCUITPY settings
        modify_circuitpy_settings(circuitpy_path, local_url)
        
        # Print completion summary
        print_header("Simulated OTA Update Ready")
        print("\n✓ Setup Complete!")
        print("\nConfiguration Summary:")
        print(f"  • Web Server: {local_url} (PID: {process.pid})")
        print(f"  • Device VERSION: 0.0.0 (will trigger update)")
        print(f"  • Update Manifest: {local_url}/releases.json")
        print(f"  • Firmware Package: {local_url}/wicid_install.zip")
        
        print("\n" + "=" * 60)
        print("TESTING INSTRUCTIONS")
        print("=" * 60)
        print("\n1. Press the RESET button on your WICID device")
        print("2. The device will boot and check for updates")
        print("3. It will download and install the firmware from local server")
        print("4. Monitor the device LED for update progress:")
        print("   - Downloading: LED activity")
        print("   - Installing: Device will reboot")
        print("   - Success: Normal operation resumes")
        
        print("\nIMPORTANT: The web server must remain running during the update.")
        print("           Do not stop the server until the update is complete.")
        
        # Prompt to terminate server
        print("\n" + "=" * 60)
        response = input("\nOnce update is verified, terminate server? [Y/n]: ").strip().lower()
        
        if response == "" or response == "y" or response == "yes":
            stop_wicid_web_server(process)
            process = None  # Mark as stopped
        else:
            print(f"\nWeb server remains running at: {local_url}")
            print(f"Server PID: {process.pid}")
            print("\nTo stop the server later, run:")
            print(f"  kill {process.pid}")
        
        return True
    
    except Exception as e:
        print_error(f"Simulated OTA update failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Only stop server if it was started and we encountered an error before user prompt
        # If we've already prompted the user, they control the server lifecycle
        if process and process.poll() is None:
            try:
                stop_wicid_web_server(process)
            except:
                pass
        
        return False


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog='installer.py',
        description='WICID Firmware Installer - Install firmware to CIRCUITPY devices',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Installation Modes:
  SOFT UPDATE (OTA-like)
    • Safer installation method
    • Files are staged in /pending_update/
    • Installation completes on next reboot
    • Recommended for most users
    
  HARD UPDATE (Full Replacement)
    • Immediate installation
    • Deletes ALL files on CIRCUITPY drive
    • Preserves only secrets.json
    • Use for clean installations or troubleshooting
  
  SIMULATED OTA UPDATE (Local Development)
    • Starts local WICID Web application server
    • Points device to local server for updates
    • Useful for testing OTA update flow in development
    • Requires WICID Web repository at ../wicid_web (configurable via .env)

Examples:
  %(prog)s                    Run interactive installer
  %(prog)s --help             Show this help message

Requirements:
  • CIRCUITPY device connected via USB
  • Device in Safe Mode (USB mass storage enabled)
  • Firmware package at releases/wicid_install.zip
  • For simulated OTA: Node.js and WICID Web repository
        """
    )
    
    return parser.parse_args()


def main():
    """Main installer entry point."""
    # Parse arguments (handles --help automatically)
    parse_arguments()
    
    print_header("WICID Firmware Installer")
    
    print("\nWelcome to the WICID Firmware Installer!")
    print("\nThis installer will help you update your WICID device with new firmware.")
    print("\nThree installation modes are available:")
    print("  • SOFT: OTA-like update (safer, requires reboot to complete)")
    print("  • HARD: Full replacement (immediate, deletes all files on device)")
    print("  • SIMULATED OTA: Local development testing (uses local web server)")
    print("\nThe installer will:")
    print("  1. Detect your CIRCUITPY device")
    print("  2. Verify firmware package availability")
    print("  3. Guide you through the installation process")
    
    # Detect CIRCUITPY drive
    print_step("Detecting CIRCUITPY drive...")
    circuitpy_path = detect_circuitpy_drive()
    
    if not circuitpy_path:
        print_error("CIRCUITPY drive not found!")
        print("\nPlease ensure:")
        print("  • Your WICID device is connected via USB")
        print("  • The device is in Safe Mode (USB mass storage enabled)")
        print("  • The CIRCUITPY drive is mounted")
        sys.exit(1)
    
    print_success(f"Found CIRCUITPY at: {circuitpy_path}")
    
    # Check for firmware package
    print_step("Checking for firmware package...")
    zip_path = Path("releases/wicid_install.zip")
    
    if not zip_path.exists():
        print_error(f"Firmware package not found: {zip_path}")
        print("\nPlease ensure:")
        print("  • You are running this script from the project root")
        print("  • The releases/wicid_install.zip file exists")
        print("  • You have built the firmware package")
        sys.exit(1)
    
    print_success(f"Found firmware package: {zip_path}")
    
    # Prompt for installation mode
    print_header("Select Installation Mode")
    print("\n1. SOFT Update (OTA-like)")
    print("   • Safer installation method")
    print("   • Files are staged in /pending_update/")
    print("   • Installation completes on next reboot")
    print("   • Recommended for most users")
    
    print("\n2. HARD Update (Full Replacement)")
    print("   • Immediate installation")
    print("   • Deletes ALL files on CIRCUITPY drive")
    print("   • Preserves only secrets.json")
    print("   • Use for clean installations or troubleshooting")
    
    print("\n3. Simulated OTA Update (Local Development)")
    print("   • Starts local WICID Web application server")
    print("   • Points device to local server for updates")
    print("   • Tests OTA update flow in development")
    print("   • Requires WICID Web repository")
    
    update_successful = False
    update_mode = None
    
    while True:
        choice = input("\nEnter your choice (1, 2, or 3): ").strip()
        
        if choice == "1":
            update_mode = "soft"
            update_successful = soft_update(circuitpy_path, zip_path)
            break
        elif choice == "2":
            update_mode = "hard"
            update_successful = hard_update(circuitpy_path, zip_path)
            break
        elif choice == "3":
            update_mode = "simulated_ota"
            update_successful = simulated_ota_update(circuitpy_path, zip_path)
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")
    
    # Only show completion message if update succeeded
    if update_successful:
        # Simulated OTA handles its own completion messages and instructions
        if update_mode != "simulated_ota":
            print_header("Installation Complete")
            print("\nTo complete the update:")
            print("  1. Press the RESET button on your WICID device")
            print("  2. The device will reboot and apply the firmware")
            
            if update_mode == "soft":
                print("\nThe boot.py script will automatically install the update on next boot.")
            
            print("\nThank you for using WICID!")
        else:
            # For simulated OTA, just print a thank you
            print("\nThank you for using WICID!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

