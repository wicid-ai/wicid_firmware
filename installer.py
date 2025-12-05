#!/usr/bin/env python3
# mypy: ignore-errors
"""
WICID Firmware Installer

Provides INCREMENTAL (default, updates only changed files), SOFT (OTA-like),
HARD (full replacement), and SIMULATED OTA (local development testing)
installation methods for WICID firmware packages to CIRCUITPY devices.
"""

import argparse
import contextlib
import filecmp
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path

os.environ["COPYFILE_DISABLE"] = "1"  # Prevent macOS ._ files on FAT12/FAT32

SYSTEM_FOLDERS = {
    ".Trashes",
    ".fseventsd",
    ".metadata_never_index",
    "System Volume Information",
    ".TemporaryItems",
    ".Spotlight-V100",
}
PRESERVED_FILES = {"secrets.json"}
RUNTIME_FILES = {"boot_out.txt"}
INSTALL_SCRIPTS_DIR = "firmware_install_scripts"
PENDING_UPDATE_DIR = "pending_update"

READONLY_ERROR = """\
CIRCUITPY drive is READ-ONLY. Device must be in Safe Mode.

To enter Safe Mode:
  1. Unplug the device from USB
  2. Hold the BOOT button
  3. While holding, plug in USB
  4. Keep holding until LED turns yellow/orange
  5. Release the button

Run this installer again once in Safe Mode."""


def _is_preserved(name: str) -> bool:
    """Check if filename is preserved (case-insensitive)."""
    return name.lower() in {f.lower() for f in PRESERVED_FILES}


def _is_hidden_or_system(name: str) -> bool:
    """Check if name is hidden or a system folder."""
    return name.startswith(".") or name in SYSTEM_FOLDERS or name.upper().startswith("FSEVEN~")


def _is_os_artifact(name: str) -> bool:
    """
    Check if a file/directory is an OS artifact that should be removed.

    OS artifacts include:
    - Hidden files/directories (except .ready, .Trashes)
    - __pycache__ directories
    - System folders (.fseventsd, etc.)
    - macOS resource fork files (._*)

    Args:
        name: File or directory name to check

    Returns:
        True if the item is an OS artifact, False otherwise
    """
    # Hidden files/directories (except preserved ones needed for operation)
    if name.startswith("."):
        preserve_hidden = {".Trashes", ".ready"}
        return name not in preserve_hidden

    # Python cache directories
    if name == "__pycache__":
        return True

    # OS system folders
    if name in SYSTEM_FOLDERS:
        return True

    # macOS resource fork files
    return name.startswith("._")


def _should_ignore_file(name: str) -> bool:
    """
    Check if a file/directory should be excluded from deployment.

    This includes both OS artifacts AND deployment exclusions (like install scripts).

    Args:
        name: File or directory name to check

    Returns:
        True if the file/directory should be ignored during deployment, False otherwise
    """
    # First check if it's an OS artifact
    if _is_os_artifact(name):
        return True

    # Deployment exclusion: firmware_install_scripts (only needed for OTA updates)
    # This prevents install scripts from being copied during INCREMENTAL/HARD updates
    return name == INSTALL_SCRIPTS_DIR


def _filter_zip_members(zip_file: zipfile.ZipFile) -> list[str]:
    """
    Filter ZIP file members to exclude hidden files, __pycache__, and system files.

    Note: firmware_install_scripts is NOT filtered here because it's needed for
    SOFT updates (OTA simulation). The directory IS filtered during copy operations
    for INCREMENTAL/HARD updates via _should_ignore_file in copy_files_to_circuitpy.

    Args:
        zip_file: Open ZipFile object

    Returns:
        List of member names (strings) for members that should be extracted
    """
    filtered = []
    for member in zip_file.namelist():
        # Check each part of the path
        parts = Path(member).parts
        should_skip = False

        for part in parts:
            # Special case: firmware_install_scripts must be extracted (needed for OTA)
            if part == INSTALL_SCRIPTS_DIR:
                continue

            if _should_ignore_file(part):
                should_skip = True
                break

        if not should_skip:
            filtered.append(member)

    return filtered


def _sync_filesystem():
    """Force filesystem sync."""
    with contextlib.suppress(Exception):
        os.sync()


def _safe_remove_directory(path: Path) -> None:
    """
    Safely remove a directory, handling FAT32/FAT12 filesystem quirks.

    Uses ignore_errors=True to handle filesystem errors gracefully and syncs
    the filesystem after deletion attempt.

    Args:
        path: Path to directory to remove
    """
    if not path.exists():
        return
    _force_remove_tree(path)
    _sync_filesystem()


def _safe_copy_directory(src: Path, dst: Path) -> None:
    """
    Safely copy a directory tree with aggressive cleanup of macOS artifacts.

    Walks the tree and copies files individually, cleaning up ._* files
    after each directory to prevent space exhaustion.

    Args:
        src: Source directory path
        dst: Destination directory path
    """
    if dst.exists():
        _safe_remove_directory(dst)

    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not _should_ignore_file(d)]

        rel_root = Path(root).relative_to(src)
        dst_root = dst / rel_root
        dst_root.mkdir(parents=True, exist_ok=True)

        # Delete ._* file for the directory itself (if macOS created one)
        with contextlib.suppress(OSError):
            if dst_root.parent.exists():
                resource_fork = dst_root.parent / f"._{dst_root.name}"
                if resource_fork.exists():
                    resource_fork.unlink()

        # Copy files
        for f in files:
            if _should_ignore_file(f):
                continue
            _safe_copy_file(Path(root) / f, dst_root / f)

        # Clean any remaining ._* files in this directory
        for item in dst_root.iterdir():
            if item.name.startswith("._"):
                with contextlib.suppress(OSError):
                    item.unlink()


def _safe_copy_file(src: Path, dst: Path) -> None:
    """
    Safely copy a file and immediately clean up macOS resource forks.

    macOS creates ._* files when copying to FAT filesystems despite COPYFILE_DISABLE=1.
    These consume 4KB per file and cause "No space left" errors.

    Args:
        src: Source file path
        dst: Destination file path
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Retry on transient FAT errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.copyfile(src, dst)

            # IMMEDIATELY delete macOS resource fork file if created
            # Suppress errors - file might be locked/protected by macOS
            resource_fork = dst.parent / f"._{dst.name}"
            with contextlib.suppress(OSError):
                if resource_fork.exists():
                    resource_fork.unlink()

            return
        except OSError as e:
            if e.errno in (14, 22, 28) and attempt < max_retries - 1:
                # Bad address, Invalid argument, No space - sync and retry
                _sync_filesystem()
                time.sleep(0.2)
            else:
                raise


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
    """Get WICID Web root from LOCAL_WICID_WEB_ROOT_DIR env or default ../wicid_web."""
    env_path = os.environ.get("LOCAL_WICID_WEB_ROOT_DIR")
    return Path(env_path) if env_path else Path(__file__).parent.parent / "wicid_web"


def detect_circuitpy_drive():
    """Auto-detect the CIRCUITPY drive. Returns Path or None."""
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
                        f"{letter}:\\", volume_name_buffer, ctypes.sizeof(volume_name_buffer), None, None, None, None, 0
                    )
                    if volume_name_buffer.value == "CIRCUITPY":
                        return drive_path
                except Exception:
                    pass

    return None


def list_circuitpy_contents(circuitpy_path):
    """List files/directories on CIRCUITPY that would be deleted."""
    to_delete = []

    try:
        for item in os.listdir(circuitpy_path):
            # Skip system folders and preserved files
            if item in SYSTEM_FOLDERS or item in PRESERVED_FILES:
                continue

            # Skip all hidden files (starting with .)
            if item.startswith("."):
                continue

            item_path = circuitpy_path / item
            relative_path = str(item_path.relative_to(circuitpy_path))

            # Add trailing slash for directories
            if item_path.is_dir():
                relative_path += "/"

            to_delete.append(relative_path)
    except Exception as e:
        print_error(f"Could not list CIRCUITPY contents: {e}")

    return sorted(to_delete)


def delete_circuitpy_contents(circuitpy_path):
    """Delete all files and directories on CIRCUITPY except preserved items."""
    print_step("Deleting files on CIRCUITPY drive...")
    deleted_count = 0

    for item in os.listdir(circuitpy_path):
        if _is_preserved(item):
            print(f"  Preserving: {item}")
            continue
        if _is_hidden_or_system(item):
            continue

        item_path = circuitpy_path / item

        try:
            if item_path.is_dir():
                _force_remove_tree(item_path)
                print(f"  Deleted directory: {item}")
            else:
                item_path.unlink()
                print(f"  Deleted file: {item}")
            deleted_count += 1
        except OSError as e:
            if e.errno == 30:  # EROFS
                raise OSError(READONLY_ERROR) from e
            raise

    print_success(f"Deleted {deleted_count} items from CIRCUITPY")


def extract_zip_to_temp(zip_path):
    """Extract ZIP file to a temporary directory and return the path."""
    print_step(f"Extracting {zip_path}...")

    temp_dir = Path(tempfile.mkdtemp(prefix="wicid_install_"))

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Filter ZIP members to exclude hidden files and system artifacts
            filtered_members = _filter_zip_members(zf)

            # Extract only filtered members
            for member in filtered_members:
                zf.extract(member, temp_dir)

            file_count = len(filtered_members)

        # Clean up any artifacts that might have been created during extraction
        cleanup_artifacts(temp_dir)

        print_success(f"Extracted {file_count} files to temporary directory")
        return temp_dir

    except Exception as e:
        print_error(f"Failed to extract ZIP: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def get_disk_space(path):
    """Get available disk space in bytes."""
    stat = shutil.disk_usage(path)
    return stat.free


def _force_remove_tree(path: Path) -> None:
    """
    Forcefully remove a directory tree on FAT filesystems with best-effort cleanup.
    Handles invalid entries by walking bottom-up and suppressing unlink/rmdir errors.
    """
    if not path.exists():
        return

    for _ in range(2):  # two passes to handle stubborn entries
        for root, dirs, files in os.walk(path, topdown=False):
            for f in files:
                with contextlib.suppress(OSError):
                    (Path(root) / f).unlink()
            for d in dirs:
                with contextlib.suppress(OSError):
                    (Path(root) / d).rmdir()
        with contextlib.suppress(OSError):
            path.rmdir()
        _sync_filesystem()

    # Final attempt
    shutil.rmtree(path, ignore_errors=True)
    _sync_filesystem()


def copy_files_to_circuitpy(source_dir, dest_dir, recursive=True, include_install_scripts=False):
    """
    Copy files from source to destination with context-aware exclusions.

    Args:
        source_dir: Source directory path
        dest_dir: Destination directory path
        recursive: If True, copy subdirectories recursively
        include_install_scripts: If True, include firmware_install_scripts directory
                                (needed for SOFT updates/OTA). If False, exclude it
                                (INCREMENTAL/HARD updates don't need it on device).
    """
    print_step(f"Copying files to {dest_dir}...")
    copied_count = 0

    try:
        cleanup_artifacts(source_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        for item in os.listdir(source_dir):
            # Special case: install_scripts handling based on update context
            if item == INSTALL_SCRIPTS_DIR:
                if not include_install_scripts:
                    continue  # Skip for INCREMENTAL/HARD updates
                # For SOFT updates, fall through to copy it

            # Standard ignore rules (except install_scripts which we handled above)
            elif _should_ignore_file(item):
                continue

            if _is_preserved(item):
                print(f"  Skipping preserved file: {item}")
                continue

            src_path = source_dir / item
            dst_path = dest_dir / item

            if src_path.is_dir() and recursive:
                _safe_copy_directory(src_path, dst_path)
                print(f"  Copied directory: {item}/")
                copied_count += 1
            elif src_path.is_file():
                if _is_preserved(dst_path.name):
                    raise RuntimeError(f"BUG: Would overwrite preserved file {dst_path.name}")
                _safe_copy_file(src_path, dst_path)
                print(f"  Copied file: {item}")
                copied_count += 1

    except OSError as e:
        if e.errno == 30:  # EROFS
            raise OSError(READONLY_ERROR) from e
        raise

    _sync_filesystem()
    print_success(f"Copied {copied_count} items")
    cleanup_artifacts(dest_dir)


def cleanup_artifacts(path: Path, max_passes: int = 3):
    """
    Remove OS artifacts and system files (NOT deployment exclusions).

    Removes:
    - Hidden files (except preserved ones like .ready, .Trashes)
    - macOS resource fork files (._*)
    - __pycache__ directories
    - System folders

    Note: Does NOT remove firmware_install_scripts - that's a deployment exclusion,
    not an artifact. Deployment filtering happens in copy_files_to_circuitpy().

    Multiple cleanup passes handle macOS async resource fork creation - macOS creates
    ._* files milliseconds AFTER file operations complete, so we sweep repeatedly
    until no more artifacts are found.

    Args:
        path: Path to directory to clean
        max_passes: Maximum cleanup passes (default 3)
    """
    total_removed = 0

    for _ in range(max_passes):
        removed_this_pass = 0

        # Sync filesystem before checking (let macOS finish async operations)
        _sync_filesystem()
        time.sleep(0.1)  # Brief delay for macOS background processes

        for root, dirs, files in os.walk(path):
            # Process directories - only remove OS artifacts
            for d in dirs[:]:  # Use slice copy to allow modification
                if _is_os_artifact(d):
                    dir_path = Path(root) / d
                    if dir_path.is_dir():
                        _safe_remove_directory(dir_path)
                        removed_this_pass += 1
                    dirs.remove(d)  # Remove from dirs to avoid walking into it

            # Process files - only remove OS artifacts
            for f in files:
                if _is_os_artifact(f):
                    try:
                        (Path(root) / f).unlink()
                        removed_this_pass += 1
                    except OSError:
                        pass  # File locked or other error

        total_removed += removed_this_pass

        # If no artifacts found this pass, we're done
        if removed_this_pass == 0:
            break

    if total_removed:
        print(f"  Cleaned up {total_removed} hidden files/directories")


def validate_simulated_ota_prerequisites(web_root_dir, circuitpy_path, zip_path):
    """Validate prerequisites for simulated OTA. Returns (success, error_message)."""
    # Check web root directory exists
    if not web_root_dir.exists():
        return (
            False,
            f"WICID Web directory not found: {web_root_dir}\n\nPlease ensure the WICID Web repository exists at this location.\nYou can set a custom path with LOCAL_WICID_WEB_ROOT_DIR in .env file.",
        )

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
        return False, "releases.json not found in project root\n\nPlease build the firmware first."

    # Check CIRCUITPY drive is writable
    test_file = circuitpy_path / ".write_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
    except OSError as e:
        if e.errno == 30:  # EROFS
            return False, READONLY_ERROR
        return False, f"Cannot write to CIRCUITPY drive: {e}"

    # Check settings.toml exists
    settings_toml = circuitpy_path / "settings.toml"
    if not settings_toml.exists():
        return False, f"settings.toml not found on CIRCUITPY drive: {settings_toml}"

    return True, ""


def _drain_stdout(pipe):
    """
    Continuously drain stdout pipe to prevent blocking.
    Runs in a background daemon thread.

    Args:
        pipe: File object to drain
    """
    try:
        for _line in pipe:
            pass  # Discard output
    except Exception:
        pass  # Pipe closed or process died


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
            bufsize=1,
        )

        print("  Waiting for server to start...")

        # Read output until we see "ready" with timeout
        start_time = time.time()
        timeout = 30  # seconds
        output_lines = []
        local_url = None
        candidate_urls = []

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
                # Found ready marker, now collect all Network URLs from subsequent lines
                for _ in range(10):
                    line = process.stdout.readline()
                    if not line:
                        break
                    output_lines.append(line.strip())
                    print(f"    {line.strip()}")

                    # Look for Network URL pattern: "Network: http://IP:PORT/"
                    match = re.search(r"Network:\s+(http://[\d.]+:\d+/?)", line)
                    if match:
                        url = match.group(1).rstrip("/")
                        candidate_urls.append(url)

                    # Stop reading when we see the help prompt (no more URLs after this)
                    if "press" in line.lower():
                        break

                # Exit the outer loop after collecting URLs
                break

        # Start background thread to drain stdout and prevent pipe blocking
        # This is critical: Vite continues to output messages, and if we don't drain
        # the pipe, it will fill up (~64KB) and block the process, preventing termination
        drain_thread = threading.Thread(target=_drain_stdout, args=(process.stdout,), daemon=True)
        drain_thread.start()

        # Prioritize URLs starting with 10.0.0, otherwise use the first one found
        if candidate_urls:
            for url in candidate_urls:
                if re.search(r"http://10\.0\.0\.\d+", url):
                    local_url = url
                    break
            # If no 10.0.0.x URL found, use the first candidate
            if local_url is None:
                local_url = candidate_urls[0]

        if local_url is None:
            process.terminate()
            raise Exception(
                "Server started but could not find Network URL in output.\n"
                "Server may not be configured correctly.\n"
                "Output received:\n" + "\n".join(output_lines)
            )

        print_success(f"Server started at: {local_url}")
        print(f"  Server PID: {process.pid}")

        return process, local_url

    except FileNotFoundError as err:
        raise Exception("npm command not found. Please ensure Node.js and npm are installed.") from err
    except Exception:
        # Try to clean up process if it exists
        try:
            if "process" in locals() and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except Exception:
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

    _safe_copy_file(src_zip, dst_zip)
    print(f"  Copied: wicid_install.zip -> {dst_zip}")

    # Read and modify releases.json
    src_releases = Path("releases.json")
    with open(src_releases) as f:
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
    with open(dst_releases, "w") as f:
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
        with open(settings_file) as f:
            content = f.read()

        # Replace VERSION with 0.0.0 to trigger update
        content = re.sub(r'VERSION\s*=\s*"[^"]*"', 'VERSION = "0.0.0"', content)

        # Replace SYSTEM_UPDATE_MANIFEST_URL with local URL
        content = re.sub(
            r'SYSTEM_UPDATE_MANIFEST_URL\s*=\s*"[^"]*"',
            f'SYSTEM_UPDATE_MANIFEST_URL = "{local_wicid_web_url}/releases.json"',
            content,
        )

        # Write back to file
        with open(settings_file, "w") as f:
            f.write(content)

        print('  Set VERSION = "0.0.0"')
        print(f'  Set SYSTEM_UPDATE_MANIFEST_URL = "{local_wicid_web_url}/releases.json"')

        print_success("CIRCUITPY settings.toml updated")

    except OSError as e:
        if e.errno == 30:  # EROFS
            raise OSError(READONLY_ERROR) from e
        raise


def copy_file_safely(src_path, dst_path):
    """Copy a file, creating parent directories as needed."""
    _safe_copy_file(src_path, dst_path)


def _case_insensitive_exists(path):
    """Check if file exists (FAT12/FAT32 is case-insensitive on mount)."""
    if path.exists():
        return path
    # FAT12 is case-insensitive; check for case variants in parent dir
    parent = path.parent
    if not parent.exists():
        return None
    target = path.name.lower()
    for item in parent.iterdir():
        if item.name.lower() == target:
            return item
    return None


def _resolve_py_mpy_conflict(dst_path):
    """Remove conflicting .py/.mpy variant (skip lib/ directory)."""
    if "lib" in dst_path.parts:
        return None
    suffix = dst_path.suffix.lower()
    if suffix not in (".py", ".mpy"):
        return None
    alt_path = dst_path.with_suffix(".mpy" if suffix == ".py" else ".py")
    if alt_path.exists():
        alt_path.unlink()
        return alt_path
    return None


def _validate_boot_file(circuitpy_path):
    """Ensure boot.py exists after installation."""
    boot_path = circuitpy_path / "boot.py"
    if not boot_path.exists():
        raise RuntimeError("CRITICAL: boot.py missing after installation.")


def copy_tests(circuitpy_path, tests_dir, hard=False):
    """Copy integration/functional tests to CIRCUITPY (unit tests are desktop-only)."""
    print_step(f"Copying tests ({'hard' if hard else 'incremental'})...")

    tests_dir = Path(tests_dir).resolve()
    tests_dest = Path(circuitpy_path).resolve() / "tests"

    if hard and tests_dest.exists():
        _safe_remove_directory(tests_dest)
        print("  Deleted existing tests directory")

    tests_dest.mkdir(parents=True, exist_ok=True)

    # Copy infrastructure files
    for f in ["__init__.py", "unittest.py", "run_tests.py", "test_helpers.py"]:
        src = tests_dir / f
        if src.exists():
            dst = tests_dest / f
            if hard or not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
                copy_file_safely(src, dst)
                print(f"  Copied: tests/{f}")

    # Copy integration/ and functional/ subdirectories
    for subdir in ["integration", "functional"]:
        src_dir = tests_dir / subdir
        dst_dir = tests_dest / subdir
        if not src_dir.exists():
            continue

        if hard:
            _safe_copy_directory(src_dir, dst_dir)
            print(f"  Copied: tests/{subdir}/")
        else:
            # Incremental: copy only new/changed files
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if not _should_ignore_file(d)]
                for f in files:
                    if _should_ignore_file(f):
                        continue
                    src = Path(root) / f
                    rel = src.relative_to(tests_dir)
                    dst = tests_dest / rel
                    is_new = not dst.exists()
                    if is_new or not filecmp.cmp(src, dst, shallow=False):
                        _safe_copy_file(src, dst)
                        print(f"  {'Added' if is_new else 'Updated'}: tests/{rel}")

    _sync_filesystem()
    print_success("Tests copied")


def _copy_tests_if_requested(circuitpy_path, include_tests, hard=False):
    """Copy tests and create TESTMODE flag if requested. Returns False on failure."""
    if not include_tests:
        return True
    tests_dir = Path("tests")
    if not tests_dir.is_dir():
        print_error("Tests directory not found")
        return False
    copy_tests(circuitpy_path, tests_dir, hard=hard)
    (circuitpy_path / "TESTMODE").touch()
    print_success("Created TESTMODE flag file")
    return True


def incremental_update(circuitpy_path, zip_path, include_tests=False):
    """Perform INCREMENTAL update - only replace changed/missing files."""
    print_header("INCREMENTAL UPDATE MODE")
    print("\nUpdates only changed or missing files. secrets.json preserved.")

    circuitpy_path = Path(circuitpy_path).resolve()

    try:
        temp_dir = extract_zip_to_temp(zip_path)
    except Exception as e:
        print_error(f"Failed to extract firmware package: {e}")
        traceback.print_exc()
        return False

    try:
        print_step("Comparing files and preparing updates...")
        updated_count = 0
        added_count = 0
        skipped_count = 0

        for root, dirs, files in os.walk(temp_dir):
            # Filter directories using unified function
            dirs[:] = [d for d in dirs if not _should_ignore_file(d)]
            # Filter files using unified function
            files = [f for f in files if not _should_ignore_file(f)]
            # Skip if any part of the path should be ignored
            if any(_should_ignore_file(part) for part in Path(root).parts):
                continue

            for file in files:
                # Get relative path from temp_dir
                rel_path = Path(root).relative_to(temp_dir) / file

                # Skip preserved files
                if file.lower() in [f.lower() for f in PRESERVED_FILES]:
                    print(f"  Skipping preserved file: {rel_path}")
                    skipped_count += 1
                    continue

                # Skip runtime-generated files (e.g., boot_out.txt)
                if file in RUNTIME_FILES:
                    skipped_count += 1
                    continue

                # Skip ignored files/directories using unified function
                if any(_should_ignore_file(part) for part in rel_path.parts):
                    skipped_count += 1
                    continue

                src_path = Path(root) / file
                dst_path = circuitpy_path / rel_path

                # Check if file exists on CIRCUITPY (case-insensitive for FAT32)
                existing_path = _case_insensitive_exists(dst_path)

                if existing_path:
                    # File exists - resolve .py/.mpy conflicts BEFORE comparison
                    removed_conflict = _resolve_py_mpy_conflict(dst_path)
                    if removed_conflict:
                        try:
                            rel_removed = removed_conflict.relative_to(circuitpy_path)
                        except ValueError:
                            rel_removed = removed_conflict
                        print(f"  Removed stale {rel_removed} to resolve .py/.mpy conflict")
                        # Re-check existence after conflict resolution
                        existing_path = _case_insensitive_exists(dst_path)

                    if existing_path:
                        # File exists - compare content
                        try:
                            # Use filecmp for content comparison (shallow=False does byte-by-byte)
                            if filecmp.cmp(src_path, existing_path, shallow=False):
                                # Files are identical - skip
                                skipped_count += 1
                                continue
                            else:
                                # Files differ - update
                                copy_file_safely(src_path, dst_path)
                                print(f"  Updated: {rel_path}")
                                updated_count += 1
                        except OSError as e:
                            # OSError during comparison (file handle issues, etc.)
                            # Log the error but don't update - this could indicate a real problem
                            print(f"  Warning: Could not compare {rel_path}: {e}")
                            print("  Skipping update - file may be locked or corrupted")
                            skipped_count += 1
                        except Exception as e:
                            # Other exceptions - log but be more cautious
                            print(f"  Warning: Unexpected error comparing {rel_path}: {e}")
                            print("  Skipping update to avoid corruption")
                            skipped_count += 1
                    else:
                        # File was deleted by conflict resolution - add it
                        copy_file_safely(src_path, dst_path)
                        print(f"  Added: {rel_path}")
                        added_count += 1
                else:
                    # File doesn't exist - resolve conflicts first, then add
                    removed_conflict = _resolve_py_mpy_conflict(dst_path)
                    if removed_conflict:
                        try:
                            rel_removed = removed_conflict.relative_to(circuitpy_path)
                        except ValueError:
                            rel_removed = removed_conflict
                        print(f"  Removed stale {rel_removed} to resolve .py/.mpy conflict")

                    copy_file_safely(src_path, dst_path)
                    print(f"  Added: {rel_path}")
                    added_count += 1

        # Handle directories - ensure they exist on CIRCUITPY
        for root, dirs, _files in os.walk(temp_dir):
            # Filter directories using unified function
            dirs[:] = [d for d in dirs if not _should_ignore_file(d)]

            for dir_name in dirs:
                rel_dir_path = Path(root).relative_to(temp_dir) / dir_name
                dst_dir_path = circuitpy_path / rel_dir_path

                # Create directory if it doesn't exist
                if not dst_dir_path.exists():
                    dst_dir_path.mkdir(parents=True, exist_ok=True)

        # Sync filesystem to ensure all writes are flushed before cleanup
        _sync_filesystem()

        # Remove macOS metadata files from CIRCUITPY
        cleanup_artifacts(circuitpy_path)

        print_success(
            f"Incremental update completed: {added_count} added, {updated_count} updated, {skipped_count} unchanged"
        )

        if not _copy_tests_if_requested(circuitpy_path, include_tests):
            return False

        _sync_filesystem()
        _validate_boot_file(circuitpy_path)
        return True

    except OSError as e:
        if e.errno == 30:  # EROFS
            print_error(READONLY_ERROR)
        else:
            print_error(f"Incremental update failed: {e}")
            traceback.print_exc()
        return False
    except Exception as e:
        print_error(f"Incremental update failed: {e}")

        traceback.print_exc()
        return False

    finally:
        # Clean up temporary directory
        print_step("Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print_success("Cleanup complete")


def soft_update(circuitpy_path, zip_path):
    """Perform SOFT update - stages files in /pending_update/ for reboot install."""
    print_header("SOFT UPDATE MODE")
    print("\nThis will prepare an OTA-like update:")
    print("1. Extract firmware package locally")
    print("2. Create /pending_update/root/ directory on CIRCUITPY")
    print("3. Copy firmware files to /pending_update/root/")
    print("4. Create .ready marker file to signal update is ready")
    print("5. On reboot, boot.py will install the update")
    print("\nUser data (secrets.json) will be preserved.")

    # Extract to temporary directory
    try:
        temp_dir = extract_zip_to_temp(zip_path)
    except Exception as e:
        print_error(f"Failed to extract firmware package: {e}")
        traceback.print_exc()
        return False

    try:
        # Check disk space before proceeding
        print_step("Checking available disk space...")
        pending_update_dir = circuitpy_path / PENDING_UPDATE_DIR
        pending_root_dir = pending_update_dir / "root"

        # Delete existing pending_update (file or directory) to reclaim space
        if pending_update_dir.exists():
            if pending_update_dir.is_file():
                pending_update_dir.unlink()
            else:
                _force_remove_tree(pending_update_dir)
            _sync_filesystem()

        # Calculate required space (simple approach with 2x buffer for FAT overhead)
        # Buffer accounts for: FAT12 cluster waste, directory entries, and safety margin
        temp_size = sum(f.stat().st_size for f in temp_dir.rglob("*") if f.is_file())
        available_space = get_disk_space(circuitpy_path)
        required = int(temp_size * 2.0)  # 2x buffer for FAT12 overhead

        print(f"  Update size: {temp_size / 1024:.1f} KB")
        print(f"  Required (with FAT12 buffer): {required / 1024:.1f} KB")
        print(f"  Available: {available_space / 1024:.1f} KB")

        if available_space < required:
            print_error(
                f"Insufficient disk space for SOFT update.\n"
                f"  Required:  {required / 1024:.1f} KB\n"
                f"  Available: {available_space / 1024:.1f} KB\n\n"
                f"SOFT update requires space for both existing firmware AND the update.\n"
                f"Use option 2 (HARD update) instead - it deletes existing files first."
            )
            return False

        print_success("Sufficient disk space available")

        # Create pending_update directories on CIRCUITPY
        print_step("Creating update directories on CIRCUITPY...")

        pending_update_dir.mkdir(parents=True, exist_ok=True)
        pending_root_dir.mkdir(parents=True, exist_ok=True)

        print_success(f"Created /{PENDING_UPDATE_DIR}/root/ on CIRCUITPY")

        # Copy extracted files to pending_update/root/
        # Include install_scripts since SOFT updates simulate OTA and need them in pending_update
        copy_files_to_circuitpy(temp_dir, pending_root_dir, recursive=True, include_install_scripts=True)

        # Create .ready marker file to signal staging is complete
        # The boot process requires this marker to exist and be non-empty
        ready_marker_file = pending_update_dir / ".ready"
        try:
            if ready_marker_file.exists():
                if ready_marker_file.is_dir():
                    _force_remove_tree(ready_marker_file)
                else:
                    ready_marker_file.unlink()
            ready_marker_file.write_text("ready")
            _sync_filesystem()
        except OSError as e:
            raise OSError(
                f"Cannot create .ready marker file: {e}\n"
                "The CIRCUITPY filesystem may have corrupted entries.\n\n"
                "Recovery steps:\n"
                "1. Eject the CIRCUITPY drive\n"
                "2. Unplug the device from USB\n"
                "3. Plug it back in\n"
                "4. Run the installer again\n\n"
                "If the issue persists, use HARD update (option 2) instead."
            ) from e

        # Remove macOS metadata files from CIRCUITPY
        cleanup_artifacts(circuitpy_path)

        print_success("SOFT update prepared successfully")
        return True

    except OSError as e:
        if e.errno == 30:  # EROFS
            print_error(READONLY_ERROR)
        else:
            print_error(f"SOFT update failed: {e}")
            traceback.print_exc()
        return False
    except Exception as e:
        print_error(f"SOFT update failed: {e}")
        traceback.print_exc()
        return False

    finally:
        # Clean up temporary directory
        print_step("Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print_success("Cleanup complete")


def hard_update(circuitpy_path, zip_path, include_tests=False):
    """Perform HARD update - deletes all files except secrets.json, then copies fresh."""
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

    # Extract to temporary directory
    try:
        temp_dir = extract_zip_to_temp(zip_path)
    except Exception as e:
        print_error(f"Failed to extract firmware package: {e}")
        traceback.print_exc()
        return False

    try:
        # Clean pending_update before delete to avoid invalid entries
        _force_remove_tree(circuitpy_path / PENDING_UPDATE_DIR)

        cleanup_artifacts(circuitpy_path)

        secrets_path = circuitpy_path / "secrets.json"
        had_secrets = secrets_path.exists()

        delete_circuitpy_contents(circuitpy_path)
        _sync_filesystem()

        copy_files_to_circuitpy(temp_dir, circuitpy_path, recursive=True)
        _sync_filesystem()

        # Verify secrets.json preserved
        if had_secrets and not secrets_path.exists():
            raise RuntimeError("BUG: secrets.json was deleted during update")

        cleanup_artifacts(circuitpy_path)

        _validate_boot_file(circuitpy_path)
        print_success("HARD update completed successfully")

        # Copy tests directory if requested
        return _copy_tests_if_requested(circuitpy_path, include_tests, hard=True)

    except OSError as e:
        # Don't print stack trace for read-only filesystem - the error message is clear
        if "READ-ONLY" in str(e):
            print_error(str(e))
        else:
            print_error(f"HARD update failed: {e}")
            traceback.print_exc()
        return False
    except Exception as e:
        print_error(f"HARD update failed: {e}")
        traceback.print_exc()
        return False

    finally:
        # Clean up temporary directory
        print_step("Cleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print_success("Cleanup complete")


def simulated_ota_update(circuitpy_path, zip_path):
    """Perform SIMULATED OTA using local WICID Web server for development testing."""
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
        print("  • Device VERSION: 0.0.0 (will trigger update)")
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
        traceback.print_exc()

        # Only stop server if it was started and we encountered an error before user prompt
        # If we've already prompted the user, they control the server lifecycle
        if process and process.poll() is None:
            with contextlib.suppress(Exception):
                stop_wicid_web_server(process)

        return False


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="installer.py",
        description="WICID Firmware Installer - Install firmware to CIRCUITPY devices",
        epilog="Run without arguments for interactive mode. Requires CIRCUITPY device in Safe Mode.",
    )
    return parser.parse_args()


def main():
    """Main installer entry point."""
    parse_arguments()
    print_header("WICID Firmware Installer")

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
    print("\n1. INCREMENTAL Update (Default)")
    print("   • Updates only changed or missing files")
    print("   • No files are deleted")
    print("   • Fastest and safest for regular updates")
    print("   • Preserves all existing files and data")

    print("\n2. HARD Update (Full Replacement)")
    print("   • Immediate installation")
    print("   • Deletes ALL files on CIRCUITPY drive")
    print("   • Preserves only secrets.json")
    print("   • Use for clean installations or troubleshooting")

    print("\n3. SOFT Update (OTA-like)")
    print("   • Safer installation method")
    print("   • Files are staged in /pending_update/")
    print("   • Installation completes on next reboot")

    print("\n4. Simulated OTA Update (Local Development)")
    print("   • Starts local WICID Web application server")
    print("   • Points device to local server for updates")
    print("   • Tests OTA update flow in development")
    print("   • Requires WICID Web repository")

    update_successful = False
    update_mode = None

    while True:
        choice = input("\nEnter your choice (1-4, or press Enter for default): ").strip()

        # Default to incremental if empty
        if choice == "":
            choice = "1"

        if choice == "1":
            update_mode = "incremental"
            # Ask if user wants to include integration/functional tests (unit tests are desktop-only)
            include_tests_response = input("Include integration and functional tests? [y/N]: ").strip().lower()
            include_tests = include_tests_response in ["y", "yes"]
            update_successful = incremental_update(circuitpy_path, zip_path, include_tests=include_tests)
            break
        elif choice == "2":
            update_mode = "hard"
            # Ask if user wants to include integration/functional tests (unit tests are desktop-only)
            include_tests_response = input("Include integration and functional tests? [y/N]: ").strip().lower()
            include_tests = include_tests_response in ["y", "yes"]
            update_successful = hard_update(circuitpy_path, zip_path, include_tests=include_tests)
            break
        elif choice == "3":
            update_mode = "soft"
            update_successful = soft_update(circuitpy_path, zip_path)
            break
        elif choice == "4":
            update_mode = "simulated_ota"
            update_successful = simulated_ota_update(circuitpy_path, zip_path)
            break
        else:
            print("Invalid choice. Please enter 1, 2, 3, or 4 (or press Enter for default).")

    # Only show completion message if update succeeded
    if update_successful:
        # Simulated OTA handles its own completion messages and instructions
        if update_mode != "simulated_ota":
            print_header("Installation Complete")

            if update_mode == "incremental":
                print("\nThe firmware has been updated incrementally.")
                print("Changed and missing files have been updated.")
                print("\nTo apply the update:")
                print("  1. Press the RESET button on your WICID device")
                print("  2. The device will reboot with the updated firmware")
            elif update_mode == "soft":
                print("\nThe update has been staged.")
                print("\nTo complete the update:")
                print("  1. Press the RESET button on your WICID device")
                print("  2. The device will reboot and apply the firmware")
                print("\nThe boot.py script will automatically install the update on next boot.")
            else:
                print("\nTo complete the update:")
                print("  1. Press the RESET button on your WICID device")
                print("  2. The device will reboot and apply the firmware")

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
        traceback.print_exc()
        sys.exit(1)
