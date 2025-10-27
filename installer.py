#!/usr/bin/env python3
"""
WICID Firmware Installer

Provides SOFT (OTA-like) and HARD (full replacement) installation methods
for WICID firmware packages to CIRCUITPY devices.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import glob
import argparse
import json
from datetime import datetime
from pathlib import Path


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
        
        # Skip all hidden files - they're system artifacts and cause issues
        if item.startswith('.'):
            print(f"  Skipping hidden file: {item}")
            continue
        
        item_path = circuitpy_path / item
        
        try:
            if item_path.is_dir():
                # Force recursive deletion of directories
                shutil.rmtree(item_path, ignore_errors=False)
                print(f"  Deleted directory: {item}")
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
                    # Use copy_function=shutil.copy to avoid metadata issues on FAT
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True, copy_function=shutil.copy)
                    print(f"  Copied directory: {item}/")
                    copied_count += 1
            else:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
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
        # Delete existing files on CIRCUITPY
        delete_circuitpy_contents(circuitpy_path)
        
        # Copy new firmware files to CIRCUITPY root
        copy_files_to_circuitpy(temp_dir, circuitpy_path, recursive=True)
        
        # Remove macOS metadata files from CIRCUITPY
        cleanup_macos_artifacts(circuitpy_path)
        
        # Write installation timestamp
        try:
            print_step("Recording installation timestamp...")
            manifest_path = temp_dir / "manifest.json"
            version = "unknown"
            if manifest_path.exists():
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                    version = manifest.get("version", "unknown")
            
            # Format timestamp as human-readable string (matching CircuitPython format)
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            install_info = {
                "timestamp": timestamp_str,
                "version": version
            }
            timestamp_path = circuitpy_path / "install_timestamp.json"
            with open(timestamp_path, 'w') as f:
                json.dump(install_info, f)
            print_success("Installation timestamp recorded")
        except Exception as e:
            print(f"  Warning: Could not write timestamp: {e}")
        
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

Examples:
  %(prog)s                    Run interactive installer
  %(prog)s --help             Show this help message

Requirements:
  • CIRCUITPY device connected via USB
  • Device in Safe Mode (USB mass storage enabled)
  • Firmware package at releases/wicid_install.zip
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
    print("\nTwo installation modes are available:")
    print("  • SOFT: OTA-like update (safer, requires reboot to complete)")
    print("  • HARD: Full replacement (immediate, deletes all files on device)")
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
    
    update_successful = False
    update_mode = None
    
    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        
        if choice == "1":
            update_mode = "soft"
            update_successful = soft_update(circuitpy_path, zip_path)
            break
        elif choice == "2":
            update_mode = "hard"
            update_successful = hard_update(circuitpy_path, zip_path)
            break
        else:
            print("Invalid choice. Please enter 1 or 2.")
    
    # Only show completion message if update succeeded
    if update_successful:
        print_header("Installation Complete")
        print("\nTo complete the update:")
        print("  1. Press the RESET button on your WICID device")
        print("  2. The device will reboot and apply the firmware")
        
        if update_mode == "soft":
            print("\nThe boot.py script will automatically install the update on next boot.")
        
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

