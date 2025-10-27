"""
WICID Boot Support Module

This module contains all boot logic that runs before code.py:
1. Storage configuration (disable USB, remount filesystem)
2. Checking for and installing pending firmware updates
3. Full reset update strategy (all-or-nothing replacement)

This module is compiled to bytecode (.mpy) for efficiency.
"""

import os
import json
import storage
import microcontroller
import traceback
import time

# Import compatibility checking utilities
try:
    import sys
    sys.path.insert(0, '/')
    from utils import check_release_compatibility, mark_incompatible_release
    from pixel_controller import PixelController
except ImportError as e:
    print(f"Warning: Could not import utils or pixel_controller: {e}")
    check_release_compatibility = None
    mark_incompatible_release = None
    PixelController = None

# Check for pending firmware update
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"
BOOT_LOG_FILE = "/boot_log.txt"

def log_boot_message(message):
    """Write a message to the boot log file."""
    try:
        with open(BOOT_LOG_FILE, "a") as f:
            f.write(message + "\n")
        print(message)
    except:
        print(message)

def cleanup_pending_update():
    """
    Remove pending update directory and all its contents.
    Logs errors but continues to attempt cleanup.
    """
    print("Cleaning up pending update...")
    
    try:
        # Remove all files in the directory tree
        for root, dirs, files in os.walk(PENDING_UPDATE_DIR, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError as e:
                    log_boot_message(f"  Could not remove {name}: {e}")
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError as e:
                    log_boot_message(f"  Could not remove directory {name}: {e}")
        
        # Remove the main directory
        try:
            os.rmdir(PENDING_UPDATE_DIR)
        except OSError as e:
            log_boot_message(f"  Could not remove {PENDING_UPDATE_DIR}: {e}")
        
        print("✓ Cleanup complete")
    except Exception as e:
        log_boot_message(f"Warning: Cleanup error: {e}")

def delete_all_except(preserve_paths):
    """
    Delete all files and directories in root except specified paths.
    Forces recursive deletion but logs errors and continues.
    
    Args:
        preserve_paths: List of paths to preserve (e.g., ['/secrets.json', '/pending_update'])
    """
    print("Performing full reset (deleting all existing files)...")
    
    # Normalize preserve paths
    preserve_set = set(path.rstrip('/') for path in preserve_paths)
    
    # Get list of all items in root
    root_items = os.listdir('/')
    
    for item in root_items:
        item_path = f"/{item}"
        
        # Skip preserved paths
        if item_path in preserve_set:
            print(f"  Preserved: {item_path}")
            continue
        
        # Skip system files/directories
        if item in ['.Trashes', '.metadata_never_index', '.fseventsd', 'System Volume Information']:
            continue
        
        try:
            # Try to remove as file first
            try:
                os.remove(item_path)
                print(f"  Deleted file: {item_path}")
                continue
            except OSError:
                pass
            
            # If not a file, try as directory - force recursive deletion
            try:
                # Remove directory contents recursively
                for root, dirs, files in os.walk(item_path, topdown=False):
                    for name in files:
                        try:
                            file_path = os.path.join(root, name)
                            os.remove(file_path)
                        except OSError as e:
                            log_boot_message(f"  Could not remove {file_path}: {e}")
                    for name in dirs:
                        try:
                            dir_path = os.path.join(root, name)
                            os.rmdir(dir_path)
                        except OSError as e:
                            log_boot_message(f"  Could not remove directory {dir_path}: {e}")
                
                # Remove the directory itself
                os.rmdir(item_path)
                print(f"  Deleted directory: {item_path}")
            except OSError as e:
                log_boot_message(f"  Could not delete {item_path}: {e}")
        
        except Exception as e:
            log_boot_message(f"  Error processing {item_path}: {e}")
    
    print("✓ Full reset complete")

def move_directory_contents(src_dir, dest_dir, pixel_controller=None, flash_start_time=None):
    """
    Move all files and directories from src to dest.
    Logs errors but continues to attempt moving remaining files.
    
    Args:
        src_dir: Source directory path
        dest_dir: Destination directory path
        pixel_controller: Optional PixelController instance for LED updates
        flash_start_time: Optional start time for LED flashing
    """
    print(f"Moving files from {src_dir} to {dest_dir}...")
    
    items = os.listdir(src_dir)
    
    for item in items:
        src_path = f"{src_dir}/{item}"
        dest_path = f"{dest_dir}/{item}"
        
        # Update LED during file operations
        if pixel_controller and flash_start_time is not None:
            pixel_controller.flash_blue_green(flash_start_time)
        
        try:
            # Check if it's a directory
            is_dir = False
            try:
                os.listdir(src_path)
                is_dir = True
            except (OSError, NotADirectoryError):
                pass
            
            if is_dir:
                # Create destination directory if it doesn't exist
                try:
                    os.mkdir(dest_path)
                except OSError:
                    pass  # Directory might already exist
                
                # Recursively move contents
                move_directory_contents(src_path, dest_path, pixel_controller, flash_start_time)
                
                # Remove source directory
                try:
                    os.rmdir(src_path)
                except OSError as e:
                    log_boot_message(f"  Could not remove {src_path}: {e}")
            else:
                # Move file
                try:
                    # Read from source
                    with open(src_path, 'rb') as src_file:
                        content = src_file.read()
                    
                    # Write to destination
                    with open(dest_path, 'wb') as dest_file:
                        dest_file.write(content)
                    
                    # Remove source
                    os.remove(src_path)
                    
                    print(f"  Moved: {item}")
                except Exception as e:
                    log_boot_message(f"  Could not move {src_path}: {e}")
        
        except Exception as e:
            log_boot_message(f"  Error processing {item}: {e}")
    
    print("✓ File move complete")

def configure_storage():
    """
    Configure storage for production mode.
    Must be called early from boot.py before USB initialization.
    """
    # Production mode: disable USB mass storage, allow code to write files
    storage.disable_usb_drive()
    storage.remount("/", readonly=False)
    
    print("=" * 50)
    print("PRODUCTION MODE")
    print("Filesystem writable from code")
    print("USB mass storage disabled")
    print("")
    print("To enable USB for development:")
    print("Hold button for 10 seconds to enter Safe Mode")
    print("=" * 50)

def process_pending_update():
    """
    Check for and process pending firmware updates.
    """
    log_boot_message("\n=== BOOT: Checking for pending firmware updates ===")
    log_boot_message(f"Looking for: {PENDING_ROOT_DIR}")
    
    # Check for pending update installation
    try:
        # First check if the directory exists
        if not os.path.isdir(PENDING_ROOT_DIR):
            log_boot_message("No pending update found - proceeding with normal boot")
            return
        
        # Check if directory has files
        try:
            files = os.listdir(PENDING_ROOT_DIR)
            if not files:
                log_boot_message("Pending update directory is empty - cleaning up")
                cleanup_pending_update()
                return
            log_boot_message(f"Found {len(files)} files in pending update")
        except OSError as e:
            log_boot_message(f"Cannot read pending update directory: {e}")
            return
        
        log_boot_message("=" * 50)
        log_boot_message("FIRMWARE UPDATE DETECTED")
        log_boot_message("=" * 50)
        
        # Initialize LED controller and start flashing blue/green
        pixel_controller = None
        flash_start_time = None
        if PixelController:
            try:
                pixel_controller = PixelController()
                flash_start_time = time.monotonic()
                pixel_controller.flash_blue_green(flash_start_time)
                print("LED indicator: flashing blue/green during update")
            except Exception as e:
                print(f"Could not initialize LED: {e}")
        
        # Step 1: Load manifest from extracted update
        manifest_path = f"{PENDING_ROOT_DIR}/manifest.json"
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            log_boot_message("✓ Manifest loaded")
        except Exception as e:
            log_boot_message(f"ERROR: Could not load manifest: {e}")
            log_boot_message(f"Traceback: {traceback.format_exc()}")
            cleanup_pending_update()
            return
        
        # Step 2: Get current version
        try:
            current_version = os.getenv("VERSION", "0.0.0")
        except:
            current_version = "0.0.0"
        
        log_boot_message(f"Current version: {current_version}")
        log_boot_message(f"Update version: {manifest.get('version', 'unknown')}")
        
        # Step 3: Verify compatibility using DRY check
        if check_release_compatibility:
            is_compatible, error_msg = check_release_compatibility(manifest, current_version)
            
            # Update LED during compatibility check
            if pixel_controller and flash_start_time is not None:
                pixel_controller.flash_blue_green(flash_start_time)
            
            if not is_compatible:
                log_boot_message(f"ERROR: {error_msg}")
                
                # Turn off LED on error
                if pixel_controller:
                    pixel_controller.off()
                
                if mark_incompatible_release:
                    mark_incompatible_release(manifest.get("version", "unknown"))
                
                cleanup_pending_update()
                log_boot_message("=" * 50)
                log_boot_message("Update aborted due to incompatibility")
                log_boot_message("=" * 50)
                return
            else:
                log_boot_message(f"✓ Compatibility verified")
                
                # Update LED
                if pixel_controller and flash_start_time is not None:
                    pixel_controller.flash_blue_green(flash_start_time)
                
                # Step 4: Delete everything except secrets and incompatible list
                preserve_paths = [
                    "/secrets.json",
                    "/incompatible_releases.json",
                    PENDING_UPDATE_DIR
                ]
                delete_all_except(preserve_paths)
                
                # Update LED after deletion
                if pixel_controller and flash_start_time is not None:
                    pixel_controller.flash_blue_green(flash_start_time)
                
                # Step 5: Move files from pending_update/root to root
                move_directory_contents(PENDING_ROOT_DIR, "/", pixel_controller, flash_start_time)
                
                # Update LED after moving files
                if pixel_controller and flash_start_time is not None:
                    pixel_controller.flash_blue_green(flash_start_time)
                
                # Step 5.5: Record installation timestamp
                try:
                    install_info = {
                        "timestamp": time.time(),
                        "version": manifest.get("version", "unknown")
                    }
                    with open("/install_timestamp.json", "w") as f:
                        json.dump(install_info, f)
                    os.sync()
                    print("✓ Installation timestamp recorded")
                except Exception as e:
                    print(f"Warning: Could not write timestamp: {e}")
                
                # Step 6: Cleanup pending update directory
                cleanup_pending_update()
                
                # Update LED after cleanup
                if pixel_controller and flash_start_time is not None:
                    pixel_controller.flash_blue_green(flash_start_time)
                
                log_boot_message("=" * 50)
                log_boot_message(f"Update complete: {current_version} → {manifest.get('version')}")
                log_boot_message("Rebooting...")
                log_boot_message("=" * 50)
                
                # Sync filesystem before reboot
                os.sync()
                
                # Reboot
                microcontroller.reset()
        else:
            log_boot_message("WARNING: Compatibility check not available, skipping update")
            cleanup_pending_update()

    except OSError as e:
        # No pending_update directory - normal boot
        log_boot_message(f"OSError during update check: {e}")
    except Exception as e:
        log_boot_message(f"Error checking for updates: {e}")
        log_boot_message(f"Traceback: {traceback.format_exc()}")

def main():
    """
    Main entry point called from boot.py.
    Configures storage and processes any pending updates.
    """
    configure_storage()
    process_pending_update()

