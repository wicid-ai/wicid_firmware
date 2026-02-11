# WICID Firmware Build Process

## Overview

This document describes the build and release process for WICID firmware. The system is designed for:

- **Multi-platform support**: Single release can target multiple hardware types and OS versions
- **Full reset updates**: Every update is a complete firmware replacement
- **Device self-identification**: No hardcoded hardware IDs
- **Automated deployment**: GitHub Actions handles compilation and distribution
- **Semantic versioning**: Clear version progression and compatibility

## Key Concepts

### Full Reset Strategy

Every firmware update completely replaces all device files except user data:
- All firmware files are replaced (all-or-nothing)
- User configuration (`secrets.json`) is preserved
- Incompatible release tracking (`incompatible_releases.json`) is preserved
- No partial updates, no file removal lists, no migration scripts needed

This guarantees all devices have identical, consistent firmware state regardless of their update history.

### Multi-Platform Releases

A single package can support:
- Multiple hardware types (e.g., different Feather boards)
- Multiple OS versions (e.g., CircuitPython 9.3 and 10.1)

Devices identify their own capabilities at runtime and verify compatibility before installation.

### Device Self-Identification

Devices determine their own characteristics:
- Machine type from `os.uname().machine`
- OS version from `sys.implementation.version`
- No hardcoded `TARGET_SYSTEM_ID` needed

## Build Workflow

```
Developer
    ↓
./builder.py (interactive)
    ├─► Updates VERSION in settings.toml
    ├─► Generates src/manifest.json
    ├─► Updates releases.json
    └─► Creates git tag (v{version})
    ↓
Git commit & push tag
    ↓
GitHub Actions
    ├─► Compiles .py → .mpy
    ├─► Creates wicid_install.zip
    ├─► Attaches to GitHub Release
    └─► Syncs releases.json to wicid_web
    ↓
Netlify deploys
    ↓
Devices poll for updates
```

## Initial Board Setup

Before flashing the application, new Adafruit Feather ESP32-S3 boards must be initialized with CircuitPython. This process updates the bootloader and installs CircuitPython:

1. **Enter Bootloader Mode**:
   - Connect the Feather to your development computer using a data-enabled USB-C cable
   - Press and HOLD the BOOT button
   - While holding BOOT, press and release the RESET button
   - Release the BOOT button once the board enters bootloader mode (LED should not be flashing)

2. **Update Bootloader**:
   - Visit: https://circuitpython.org/board/adafruit_feather_esp32s3_4mbflash_2mbpsram/
   - Click "OPEN INSTALLER"
   - Select "Install Bootloader Only" and follow the prompts
   - After installation completes, press and release the RESET button, and you should see an updated `FTHRS3BOOT` drive

3. **Install CircuitPython**:
   - While in bootloader mode (indicated by solid green LED and availability of `FTHRS3BOOT` drive)
   - From the same CircuitPython page, download the latest `.UF2` file
   - Drag the downloaded `.UF2` file to the `FTHRS3BOOT` drive
   - The board will reboot automatically and you should now see a `CIRCUITPY` drive

   **Note**: If installing a new OS without first updating the Bootloader, follow the steps in number 1 to get into bootloader mode.

The board is now ready for application deployment using the [installer CLI](#installing-firmware-manually-optional).

## Managing CircuitPython Libraries

The `/src/lib/` directory is maintained in source control to facilitate OTA updates. Unlike the typical CircuitPython workflow where libraries are installed directly on the microcontroller, this project requires managing libraries from your development machine.

**Adding or Removing Libraries:**

1. **Install circup** (if not already installed with pipenv):
   ```bash
   pip install circup
   ```

2. **Update wicid_circuitpy_requirements.txt** to reflect the library changes you need

3. **Delete the existing /src/lib/ directory** to regenerate it cleanly:
   ```bash
   rm -rf src/lib
   ```

4. **Create a boot_out.txt file** in the `src/` directory. Because circup needs to determine the target OS version, and we're not running directly on the device, we reference a local boot_out.txt file:
   ```bash
   echo "Adafruit CircuitPython 10.0.3 on 2025-10-09;" > src/boot_out.txt
   ```

   Note: This file is gitignored, so once created you can leave it in place. Update the version string if you change CircuitPython versions.

5. **Install libraries** using circup from the project root:
   ```bash
   circup --path src install -r wicid_circuitpy_requirements.txt
   ```

   Note: To see the latest version of all libraries installed (for updating wicid_circuitpy_requirements.txt), while WICID is connected, run:

   ```bash
   circup --path src freeze
   ```

6. **Deploy to device**: Copy all files from `src/` to your device's CIRCUITPY drive, or use the build process to create a release package

## Using the Build Tool

### Prerequisites

- Python 3.14+
- Git access to repository
- `mpy-cross` compiler matching your CircuitPython version

#### Installing mpy-cross

The `mpy-cross` compiler **must** match the CircuitPython version running on your target device. Installing via `pip install mpy-cross` will not work because that version targets MicroPython, not CircuitPython.

**Version Selection Strategy:**

Use semantic versioning to select the latest stable patch version that matches your target major.minor version:
- Target `circuitpython_10` → Use latest `10.x.y` (e.g., `10.0.3`)
- Target `circuitpython_9_3` → Use latest `9.3.y` (e.g., `9.3.2`)

Always prefer `.static` builds and avoid pre-release versions (those with `-` suffixes like `10.0.0-beta.1`).

**Download Steps:**

1. Visit the Adafruit mpy-cross binary repository:
   - **macOS**: https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/macos/
   - **Linux x64**: https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/linux-amd64/
   - **Linux ARM64**: https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/linux-arm64/
   - **Windows**: https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/windows/

2. Find the latest stable version matching your target CircuitPython version:
   - Look for files like `mpy-cross-[OS]-[VERSION].static`
   - Example for macOS targeting CircuitPython 10.x: `mpy-cross-macos-10.0.3-universal.static`
   - Example for Linux targeting CircuitPython 9.3.x: `mpy-cross-linux-amd64-9.3.2.static`

3. Download and move to your project root directory

4. Rename it to `mpy-cross` (or `mpy-cross.exe` on Windows):
   ```bash
   # macOS example
   mv mpy-cross-macos-10.0.3-universal.static mpy-cross

   # Linux example
   mv mpy-cross-linux-amd64-10.0.3.static mpy-cross
   ```

5. Make it executable (macOS/Linux):
   ```bash
   chmod +x mpy-cross
   ```

6. Verify the version:
   ```bash
   ./mpy-cross --version
   ```

The build script will use this local `mpy-cross` binary to compile firmware.

**Note:** The GitHub Actions workflow automatically downloads the latest matching version from the [linux-amd64 repository](https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/linux-amd64/) based on the `target_operating_systems` field in your manifest.

### Interactive Build

Run the build tool:

```bash
./builder.py
```

### Build Prompts

The tool prompts for 6 pieces of information:

**1. Target Machine Types**

Full hardware identifier strings (comma-separated). Defaults to previous release value.

Example: `Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3`

The tool loads the last release's values as defaults, making it easy to keep the same targets or add new ones.

**2. Target Operating Systems**

OS version strings in `os_major_minor` format (comma-separated). Defaults to previous release value.

Example: `circuitpython_9_3, circuitpython_10_1`

Uses semantic versioning - a device with CircuitPython 10.1.4 will match `circuitpython_10_1`.

**3. Release Type**

Choose release channel:
- **Production**: Stable releases (default)
- **Development**: Beta/experimental releases

Devices select their channel by presence of `/development` file.

**4. Version Number**

Semantic version string (e.g., `0.2.0` or `1.0.0-beta.1`).

The tool suggests:
- Patch increment (bug fixes)
- Minor increment (new features)
- Major increment (breaking changes)

**5. Release Notes**

Free-form description of changes. Appears in:
- GitHub Release description
- Device update notifications (future)
- releases.json manifest

**6. Minimum Prior Version**

Optional version requirement that devices must meet to be eligible for this update. This enables ordered upgrade paths, ensuring devices upgrade through specific versions in sequence.

- Leave empty for no restriction (any version can upgrade directly)
- Defaults to the previous release's minimum prior version, or the previous release's version if no MPV was set
- Example: Setting MPV to `0.6.0` means devices must be running at least version 0.6.0 to upgrade to this release

This is particularly useful for IoT devices that may be offline for extended periods. By requiring devices to upgrade through intermediate versions, you can minimize backward-compatibility burden - each release only needs to be compatible with one prior release.

### What the Tool Does

After you confirm:

1. **Updates VERSION** in `src/settings.toml`
2. **Generates manifest** in `src/manifest.json` (gitignored, used for build defaults)
3. **Updates releases.json** with new release information
4. **Creates git tag** in `v{version}` format (e.g., `v0.2.0`)
5. **Stages files** for commit: `src/settings.toml`, `src/manifest.json`, `releases.json`

### Commit and Push

```bash
# Review changes
git diff --staged

# Commit
git commit -m "Release 0.2.0"

# Push (triggers GitHub Actions)
git push && git push --tags
```

The tag push triggers automated building and deployment.

## Installing Firmware Manually (Optional)

After building a release package locally, you can install it directly to a device using the installer script:

```bash
python installer.py
```

### When to Use the Installer

The installer is useful for:
- **Development**: Testing firmware changes on physical devices
- **Initial setup**: Flashing new devices before they're configured for OTA
- **Troubleshooting**: Clean installations when a device has issues
- **Manual updates**: Installing specific versions without waiting for OTA

### Installation Modes

**SOFT Update**
- Mimics OTA update behavior
- Extracts firmware to `/pending_update/root/` on CIRCUITPY
- Device's `boot.py` handles installation on next reboot
- Safer option with automatic compatibility verification
- Preserves all existing files until reboot

**HARD Update**
- Immediate full replacement
- Deletes all existing firmware files (preserves `secrets.json`)
- Copies new firmware directly to device root
- Lists files to be deleted and requires explicit confirmation
- Useful for clean slate installations

### Requirements

- CIRCUITPY device connected via USB in Safe Mode
- Built firmware package at `releases/wicid_install.zip`
- Python 3.11+ on host machine

### What the Installer Does

1. **Auto-detects** CIRCUITPY drive across macOS, Linux, and Windows
2. **Verifies** firmware package exists
3. **Extracts** package to temporary directory
4. **Filters** hidden files (.DS_Store, ._ files, etc.)
5. **Copies** firmware with proper directory structure
6. **Cleans up** system artifacts and temporary files
7. **Guides** user through device reboot process

### Platform Support

The installer works across:
- **macOS**: Detects `/Volumes/CIRCUITPY`
- **Linux**: Checks `/media/*/CIRCUITPY` and `/mnt/CIRCUITPY`
- **Windows**: Scans drive letters for CIRCUITPY volume

### FAT Filesystem Handling

The installer is optimized for the FAT12 filesystem used by CIRCUITPY:
- Uses `shutil.copy()` instead of `copy2()` to avoid metadata errors
- Skips all hidden files (`.DS_Store`, `._*` files)
- Handles system folders (`.Trashes`, `.fseventsd`, etc.)
- Cleans up macOS artifacts after installation

## GitHub Actions Automation

### Trigger

Tags matching `v*` pattern (e.g., `v0.2.0`, `v1.0.0-beta.1`)

### Automated Steps

1. **Setup**: Install Python
2. **Version Detection**: Parse `target_operating_systems` from manifest and query [Adafruit's S3 bucket](https://adafruit-circuit-python.s3.amazonaws.com/index.html?prefix=bin/mpy-cross/linux-amd64/) to find the latest stable mpy-cross version matching the semantic version requirement
3. **Download mpy-cross**: Fetch the version-matched `mpy-cross` binary for Linux AMD64
4. **Build**: Run `builder.py --build` (non-interactive mode)
   - Compiles all `.py` files to `.mpy` bytecode using version-matched compiler
   - Creates `wicid_install.zip` package
5. **Release**: Create GitHub Release with ZIP attached
6. **Sync**: Push `releases.json` to wicid_web repository
7. **Deploy**: Netlify automatically deploys updated manifest

### Authentication

Requires `WICID_WEB_RELEASES_TOKEN` GitHub Actions secret with write access to wicid_web repository.

## Package Structure

### wicid_install.zip

Every release package contains complete firmware:

```
wicid_install.zip
├── manifest.json        # Compatibility metadata
├── settings.toml        # System config (includes VERSION)
├── boot.py             # Source bootloader (CircuitPython requirement)
├── code.py             # Source main app (CircuitPython requirement)
├── boot_support.mpy    # Compiled boot logic
├── code_support.mpy    # Compiled runtime logic
├── update_manager.mpy  # Compiled update system
├── *.mpy               # All other firmware modules
├── lib/                # Device libraries
└── www/                # Web UI assets
```

All Python files except `boot.py` and `code.py` are compiled to bytecode for efficiency. CircuitPython requires these two files as source. User data (`secrets.json`) and recovery backup (`/recovery/`) are never included.

### manifest.json Format

Simplified manifest for compatibility verification:

```json
{
  "schema_version": "1.0.0",
  "version": "0.7.0",
  "minimum_prior_version": "0.6.0",
  "target_machine_types": [
    "Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"
  ],
  "target_operating_systems": [
    "circuitpython_9_3",
    "circuitpython_10_1"
  ],
  "release_type": "production",
  "release_notes": "Added OTA updates with checksum verification",
  "release_date": "2025-10-15T12:00:00Z"
}
```

No file lists, removal patterns, or install scripts - the full reset strategy doesn't need them.

**Note**: The manifest in the ZIP contains metadata about the release. It does not include the SHA-256 checksum (that's in releases.json). The `minimum_prior_version` field is optional - if omitted, any version can upgrade to this release.

## releases.json Structure

Multi-platform master manifest with SHA-256 checksums and archive of historical releases:

```json
{
  "schema_version": "1.0.0",
  "last_updated": "2025-10-16T12:00:00Z",
  "releases": [
    {
      "target_machine_types": ["Adafruit Feather ESP32S3..."],
      "target_operating_systems": ["circuitpython_9_3", "circuitpython_10_1"],
      "production": {
        "version": "0.7.0",
        "minimum_prior_version": "0.6.0",
        "release_notes": "Added new feature",
        "zip_url": "https://www.wicid.ai/releases/v0.7.0",
        "sha256": "a1b2c3d4e5f6...full 64-char hex string",
        "release_date": "2025-10-16T12:00:00Z"
      },
      "development": {
        "version": "0.8.0-b1",
        "minimum_prior_version": "0.7.0",
        ...
      },
      "archive": [
        {
          "version": "0.6.0",
          "release_type": "production",
          "minimum_prior_version": "0.5.0",
          "release_notes": "Previous release",
          "zip_url": "https://www.wicid.ai/releases/v0.6.0",
          "sha256": "...",
          "release_date": "2025-10-15T12:00:00Z"
        },
        {
          "version": "0.5.0",
          "release_type": "production",
          "minimum_prior_version": null,
          ...
        }
      ]
    }
  ]
}
```

The build tool maintains this automatically - you don't edit it manually.

**Key features:**
- `production` and `development` contain the current releases for each channel
- `archive` contains historical releases, sorted newest-to-oldest
- When a new release is created, the previous release of that type is automatically moved to `archive`
- `minimum_prior_version` (optional) specifies the minimum version a device must be running to upgrade
- Old clients ignore the `archive` key, maintaining backward compatibility

**Critical**: The `sha256` field contains the SHA-256 checksum of the ZIP file, calculated during the build process. Devices verify this checksum after download to ensure integrity and prevent installation of corrupted or tampered updates.

**Build Process**: `releases.json` is now a generated artifact (not checked into git). The builder calculates the checksum from the actual ZIP file and includes it in releases.json. GitHub Actions syncs this generated file to wicid_web for deployment.

### Minimum Prior Version (MPV)

The `minimum_prior_version` field enables ordered upgrade paths, ensuring devices upgrade through specific versions in sequence. This is particularly valuable for IoT devices that may be offline for extended periods.

**How it works:**

1. When a device checks for updates, it first checks the current `production` or `development` release
2. If the device's current version meets the `minimum_prior_version` requirement (or no MPV is set), it can upgrade directly
3. If the device's version is too old, it searches the `archive` for the newest eligible release
4. The device upgrades to that intermediate version, then on the next check can upgrade to the current release

**Example upgrade chain:**

- Device at version `0.3.0`
- Current production: `0.7.0` (requires `0.6.0`)
- Archive contains:
  - `0.6.0` (requires `0.5.0`) - device not eligible
  - `0.5.0` (requires `0.4.0`) - device not eligible
  - `0.4.0` (no requirement) - device eligible!
- Device upgrades to `0.4.0`, then on next check upgrades to `0.5.0`, and so on

This ensures each release only needs backward compatibility with one prior release, dramatically reducing maintenance burden.

## Installation on Device

When a device downloads an update:

1. **Pre-flight Checks**:
   - Check available disk space (requires ~200KB minimum)
   - Verify update manifest is reachable

2. **Download**: ZIP saved to `/pending_update/`
   - Download in 4KB chunks for reliability
   - Calculate SHA-256 checksum of downloaded file

3. **Verification**: Validate download integrity
   - Compare calculated checksum against manifest
   - Abort if checksum mismatch (corrupted/tampered download)

4. **Extract**: Contents extracted to `/pending_update/root/`
   - Extract all non-hidden files
   - Validate manifest.json is present and valid
   - Verify all critical files are present
   - Any failure during download, verification, or extraction records the offending version in `/incompatible_releases.json` so future update checks skip it automatically

5. **Restart**: Device reboots immediately via hard reset

6. **Recovery Check** (at boot, before everything):
   - Check if all critical files are present
   - If missing, restore from `/recovery/` backup
   - Mark failed update as incompatible
   - Reboot after recovery

7. **Verify**: Bootloader checks compatibility:
   - Machine type must match
   - OS version must be compatible
   - Version must be newer
   - Not previously marked incompatible
   - All critical files present in update package

8. **Install**: If compatible, perform full reset:
   - Delete all existing firmware
   - Preserve `/secrets.json`, `/incompatible_releases.json`, and `/recovery/`
   - Move new files to root
   - Validate all critical files present after installation

9. **Backup**: Create/update recovery backup
   - Back up all critical files to `/recovery/`
   - Persistent across updates for catastrophic failure recovery

10. **Reboot**: Device starts with new firmware

If incompatible or validation fails at any stage, the release is marked to prevent retry loops and the device boots with current firmware.

### Recovery System

The OTA update process includes a persistent recovery backup system to prevent device bricking:

- **Recovery Backup**: Located in `/recovery/`, contains copies of all critical files
- **Automatic Recovery**: If critical files are missing at boot, automatically restores from `/recovery/`
- **One-Strike Policy**: Updates that trigger recovery are immediately marked incompatible
- **Persistent**: Recovery backup is preserved across all updates and only updated on successful installations

This ensures the device can always recover from:
- Power loss during update installation
- Corrupted update packages
- Filesystem corruption
- Interrupted file operations

### Install Scripts

Optional Python scripts can be included in update packages to perform custom actions during installation.

#### Script Naming Convention

Scripts must be stored in `firmware_install_scripts/` with version-specific names:

```
firmware_install_scripts/
├── pre_install_v0.6.0-b2.py    # Pre-install for version 0.6.0-b2
├── post_install_v0.6.0-b2.py   # Post-install for version 0.6.0-b2
├── pre_install.py.example      # Example (not included in builds)
└── post_install.py.example     # Example (not included in builds)
```

The builder only includes scripts matching the exact release version.

#### Pre-Install Scripts

**Timing**: Runs after update package extraction, before compatibility checks and file validation.

**Use Cases**:
- Migrate old directory structures to match new validation requirements
- Modify extracted update files before validation
- Patch current filesystem before installation
- Script-only releases (do work, cleanup, reboot without completing normal flow)

**Arguments**: `main(log_message, pending_root_dir, pending_update_dir)`
- `log_message`: Function to log messages to boot log and `/install.log`
- `pending_root_dir`: Path to extracted update (`/pending_update/root`)
- `pending_update_dir`: Path to pending directory (`/pending_update`)

**Error Handling**: If script fails, update is marked incompatible and aborted.

**Example**:
```python
def main(log_message, pending_root_dir, pending_update_dir):
    log_message("Migrating directory structure...")
    import os
    # Move old directories to new locations
    try:
        os.rename("/old_path", "/new_path")
        log_message("Migration complete")
    except OSError as e:
        log_message(f"Migration failed: {e}")
        return False
    return True
```

#### Post-Install Scripts

**Timing**: Runs after installation complete and recovery backup created, before cleanup.

**Use Cases**:
- Migrate user configuration to new format
- Clean up obsolete files from previous versions
- Initialize new configuration files with defaults
- Modify recovery backup if needed

**Arguments**: `main(log_message, version)`
- `log_message`: Function to log messages to boot log and `/install.log`
- `version`: Version string of installed firmware

**Error Handling**: If script fails, error is logged but update continues (non-fatal).

**Example**:
```python
def main(log_message, version):
    log_message(f"Post-install for version {version}")
    import json
    import os

    # Clean up obsolete files
    for path in ["/old_config.json", "/deprecated/"]:
        try:
            os.remove(path)
            log_message(f"Removed: {path}")
        except OSError:
            pass

    return True
```

#### Script-Only Releases

Script-only releases are minimal packages that contain only install scripts—no firmware files. They're useful for:
- Configuration patches
- Data migrations
- Quick fixes that don't require a full firmware update

**Version Convention**: Use the `-s[N]` suffix to indicate a script-only release:
- `0.7.2-s1` - First script-only release for 0.7.2
- `0.7.2-s2` - Second script-only release for 0.7.2

**Building Script-Only Releases**:

1. Create the pre-install script: `firmware_install_scripts/pre_install_v0.7.2-s1.py`
2. Run `./builder.py`
3. Enter version with `-s` suffix (e.g., `0.7.2-s1`)
4. The builder detects the script-only release and asks for confirmation
5. A minimal package is created with only `manifest.json` and install scripts

**Package Contents**:
```
wicid_install.zip
├── manifest.json              # With script_only_release: true
├── pre_install_v0.7.2-s1.py   # Required
└── post_install_v0.7.2-s1.py  # Optional
```

**Script Requirements**:

The pre-install script MUST:
1. Perform the needed work
2. Clean up the `/pending_update/` directory
3. Call `microcontroller.reset()` to reboot

If the script doesn't reboot, the normal update flow will continue and fail validation (no firmware files).

**Example Script**:

```python
def main(log_message, pending_root_dir, pending_update_dir):
    import os
    import microcontroller

    log_message("Applying config patch...")

    # Do the patch work
    with open("/settings.toml", "r") as f:
        content = f.read()
    content = content.replace('OLD_VALUE', 'NEW_VALUE')
    with open("/settings.toml", "w") as f:
        f.write(content)

    # Clean up (important!)
    _rmtree(pending_update_dir)
    os.sync()

    log_message("Rebooting...")
    microcontroller.reset()  # Normal flow won't continue


def _rmtree(path):
    """Helper to recursively remove a directory."""
    import os
    try:
        items = os.listdir(path)
    except OSError:
        return
    for item in items:
        item_path = f"{path}/{item}"
        try:
            os.remove(item_path)
        except OSError:
            _rmtree(item_path)
            try:
                os.rmdir(item_path)
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
```

#### Manifest Flags

The build tool automatically adds script flags to `manifest.json`:

```json
{
  "has_pre_install_script": true,
  "has_post_install_script": false
}
```

Scripts are only executed if their corresponding flag is `true`.

#### Install Log

Script execution is logged to `/install.log`, which is overwritten on each update attempt. The log includes:
- Script start/end timestamps
- Log messages from the script
- Success/failure status
- Any error tracebacks

## Version Guidelines

### Semantic Versioning

Format: `MAJOR.MINOR.PATCH[-PRERELEASE]`

**Patch** (0.0.x): Bug fixes, performance improvements
**Minor** (0.x.0): New features, backward compatible
**Major** (x.0.0): Breaking changes, incompatible updates

**Pre-release** tags: `-alpha.1`, `-beta.2`, `-rc.1`

### Version Comparison

- `0.1.0` < `0.2.0` < `1.0.0`
- `1.0.0-beta` < `1.0.0` (pre-release < release)
- Devices only install newer versions

## Testing

### Local Package Test

```bash
# Build without pushing
./builder.py

# Verify package contents
unzip -l releases/wicid_install.zip

# Check manifest
unzip -p releases/wicid_install.zip manifest.json | python -m json.tool
```

### End-to-End Test

1. Create test release with build tool
2. Commit and push tag
3. Monitor GitHub Actions workflow
4. Verify wicid_web repository updated
5. Point test device to update server
6. Observe device update and reboot

## Troubleshooting

### "mpy-cross not found"

The build script looks for `./mpy-cross` in the project root. Download the correct version following the [Installing mpy-cross](#installing-mpy-cross) instructions above.

Verify it's in the right location and executable:
```bash
ls -la ./mpy-cross
./mpy-cross --version
```

### "mpy-cross version mismatch"

If you get fatal errors on device when loading `.mpy` files, your `mpy-cross` version doesn't match your CircuitPython version. Check your device's version:
```python
# On device REPL
import sys
print(sys.implementation.version)
```

Then download the matching `mpy-cross` version. For example, if device shows `(10, 0, 3)`, download `mpy-cross` version `10.0.3`.

### Git tag already exists

```bash
# Delete local tag
git tag -d v0.2.0

# Delete remote tag if pushed
git push origin :refs/tags/v0.2.0
```

### GitHub Actions fails

Check workflow logs for:
- Missing `WICID_WEB_RELEASES_TOKEN` secret
- Compilation errors
- Network issues

### Device won't update

Common causes:
- Insufficient storage space
- Network connectivity issues
- Version already installed
- Release marked as incompatible

Check device logs for specific error messages.

## Best Practices

1. **Test locally** before pushing tags
2. **Use clear release notes** for each version
3. **Follow semantic versioning** consistently
4. **Monitor GitHub Actions** after pushing
5. **Verify wicid_web** received the update
6. **Test on device** before announcing to users
7. **Keep git clean** - commit staged files from build tool

## Configuration Files

### settings.toml (System Configuration)

Non-sensitive system settings:

```toml
VERSION = "0.1.0"
SYSTEM_UPDATE_MANIFEST_URL = "https://www.wicid.ai/releases.json"
SYSTEM_UPDATE_CHECK_INTERVAL = 24  # hours
WEATHER_UPDATE_INTERVAL = 1200  # seconds
```

Read via `os.getenv()` in device code. Updated by build tool.

### secrets.json (User Data)

User-specific credentials, preserved during updates:

```json
{
  "ssid": "wifi_network",
  "password": "wifi_password",
  "weather_zip": "12345"
}
```

Created by setup portal, never included in release packages.

## Repository Structure

```
wicid_firmware/
├── src/                      # Device firmware
│   ├── settings.toml        # System configuration
│   ├── manifest.json        # Build defaults (gitignored)
│   ├── boot.py              # Bootloader
│   ├── code.py              # Main app
│   ├── *.py                 # Firmware modules
│   ├── lib/                 # Libraries
│   └── www/                 # Web UI
├── builder.py               # Build tool
├── installer.py             # Manual firmware installer
├── releases.json            # Master manifest
├── releases/                # Build artifacts (gitignored)
└── .github/
    └── workflows/
        └── release.yml      # Automation
```

## Summary

The WICID build process is designed for simplicity and reliability:

- **Simple prompts** with smart defaults
- **Full reset** guarantees consistency
- **Multi-platform** reduces maintenance
- **Self-identifying devices** eliminate hardcoded IDs
- **Automated deployment** reduces human error

Focus on writing clear release notes and following semantic versioning - the build system handles the rest.
