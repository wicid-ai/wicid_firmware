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

# Import compatibility checking utilities
try:
    import sys
    sys.path.insert(0, '/')
    from utils import check_release_compatibility, mark_incompatible_release
except ImportError as e:
    print(f"Warning: Could not import utils: {e}")
    check_release_compatibility = None
    mark_incompatible_release = None

# Check for pending firmware update
PENDING_UPDATE_DIR = "/pending_update"
PENDING_ROOT_DIR = "/pending_update/root"

def cleanup_pending_update():
    """Remove pending update directory and all its contents."""
    try:
        print("Cleaning up pending update...")
        
        # Remove all files in the directory tree
        for root, dirs, files in os.walk(PENDING_UPDATE_DIR, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError as e:
                    print(f"  Could not remove {name}: {e}")
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError as e:
                    print(f"  Could not remove directory {name}: {e}")
        
        # Remove the main directory
        try:
            os.rmdir(PENDING_UPDATE_DIR)
        except OSError as e:
            print(f"  Could not remove {PENDING_UPDATE_DIR}: {e}")
        
        print("✓ Cleanup complete")
    except Exception as e:
        print(f"Warning: Cleanup error: {e}")

def delete_all_except(preserve_paths):
    """
    Delete all files and directories in root except specified paths.
    
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
            
            # If not a file, try as directory
            try:
                # Remove directory contents recursively
                for root, dirs, files in os.walk(item_path, topdown=False):
                    for name in files:
                        try:
                            file_path = os.path.join(root, name)
                            os.remove(file_path)
                        except OSError as e:
                            print(f"  Could not remove {file_path}: {e}")
                    for name in dirs:
                        try:
                            dir_path = os.path.join(root, name)
                            os.rmdir(dir_path)
                        except OSError as e:
                            print(f"  Could not remove directory {dir_path}: {e}")
                
                # Remove the directory itself
                os.rmdir(item_path)
                print(f"  Deleted directory: {item_path}")
            except OSError as e:
                print(f"  Could not delete {item_path}: {e}")
        
        except Exception as e:
            print(f"  Error processing {item_path}: {e}")
    
    print("✓ Full reset complete")

def move_directory_contents(src_dir, dest_dir):
    """
    Move all files and directories from src to dest.
    
    Args:
        src_dir: Source directory path
        dest_dir: Destination directory path
    """
    print(f"Moving files from {src_dir} to {dest_dir}...")
    
    items = os.listdir(src_dir)
    
    for item in items:
        src_path = f"{src_dir}/{item}"
        dest_path = f"{dest_dir}/{item}"
        
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
                move_directory_contents(src_path, dest_path)
                
                # Remove source directory
                try:
                    os.rmdir(src_path)
                except OSError as e:
                    print(f"  Could not remove {src_path}: {e}")
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
                    print(f"  Could not move {src_path}: {e}")
        
        except Exception as e:
            print(f"  Error processing {item}: {e}")
    
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
    print("\nChecking for pending firmware updates...")
    print(f"Looking for: {PENDING_ROOT_DIR}")
    
    # Check for pending update installation
    try:
        # First check if the directory exists
        if not os.path.isdir(PENDING_ROOT_DIR):
            print("No pending update found - proceeding with normal boot")
            return
        
        # Check if directory has files
        try:
            files = os.listdir(PENDING_ROOT_DIR)
            if not files:
                print("Pending update directory is empty - cleaning up")
                cleanup_pending_update()
                return
            print(f"Found {len(files)} files in pending update")
        except OSError:
            print("Cannot read pending update directory - proceeding with normal boot")
            return
        
        print("")
        print("=" * 50)
        print("FIRMWARE UPDATE DETECTED")
        print("=" * 50)
        
        # Step 1: Load manifest from extracted update
        manifest_path = f"{PENDING_ROOT_DIR}/manifest.json"
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            print("✓ Manifest loaded")
        except Exception as e:
            print(f"ERROR: Could not load manifest: {e}")
            cleanup_pending_update()
            raise
        
        # Step 2: Get current version
        try:
            current_version = os.getenv("VERSION", "0.0.0")
        except:
            current_version = "0.0.0"
        
        print(f"Current version: {current_version}")
        print(f"Update version: {manifest.get('version', 'unknown')}")
        
        # Step 3: Verify compatibility using DRY check
        if check_release_compatibility:
            is_compatible, error_msg = check_release_compatibility(manifest, current_version)
            
            if not is_compatible:
                print(f"ERROR: {error_msg}")
                
                if mark_incompatible_release:
                    mark_incompatible_release(manifest.get("version", "unknown"))
                
                cleanup_pending_update()
                print("=" * 50)
                print("Update aborted due to incompatibility")
                print("=" * 50)
                print("")
            else:
                print(f"✓ Compatibility verified")
                
                # Step 4: Delete everything except secrets and incompatible list
                preserve_paths = [
                    "/secrets.json",
                    "/incompatible_releases.json",
                    PENDING_UPDATE_DIR
                ]
                delete_all_except(preserve_paths)
                
                # Step 5: Move files from pending_update/root to root
                move_directory_contents(PENDING_ROOT_DIR, "/")
                
                # Step 6: Cleanup pending update directory
                cleanup_pending_update()
                
                print("=" * 50)
                print(f"Update complete: {current_version} → {manifest.get('version')}")
                print("Rebooting...")
                print("=" * 50)
                print("")
                
                # Sync filesystem before reboot
                os.sync()
                
                # Reboot
                microcontroller.reset()
        else:
            print("WARNING: Compatibility check not available, skipping update")
            cleanup_pending_update()

    except OSError:
        # No pending_update directory - normal boot
        pass
    except Exception as e:
        print(f"Error checking for updates: {e}")
        traceback.print_exception(e)

def main():
    """
    Main entry point called from boot.py.
    Configures storage and processes any pending updates.
    """
    configure_storage()
    process_pending_update()

