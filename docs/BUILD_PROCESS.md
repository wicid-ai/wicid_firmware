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
./build.py (interactive)
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

## Using the Build Tool

### Prerequisites

- Python 3.11+
- Git access to repository
- `mpy-cross` installed: `pip install mpy-cross`

### Interactive Build

Run the build tool:

```bash
./build.py
```

### Build Prompts

The tool prompts for 5 pieces of information:

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

## GitHub Actions Automation

### Trigger

Tags matching `v*` pattern (e.g., `v0.2.0`, `v1.0.0-beta.1`)

### Automated Steps

1. **Setup**: Install Python and mpy-cross
2. **Build**: Run `build.py --build` (non-interactive mode)
   - Compiles all `.py` files to `.mpy` bytecode
   - Creates `wicid_install.zip` package
3. **Release**: Create GitHub Release with ZIP attached
4. **Sync**: Push `releases.json` to wicid_web repository
5. **Deploy**: Netlify automatically deploys updated manifest

### Authentication

Requires `WICID_WEB_TOKEN` secret with write access to wicid_web repository.

## Package Structure

### wicid_install.zip

Every release package contains complete firmware:

```
wicid_install.zip
├── manifest.json        # Compatibility metadata
├── settings.toml        # System config (includes VERSION)
├── boot.mpy            # Compiled bootloader
├── code.mpy            # Compiled main app
├── *.mpy               # All other firmware modules
├── lib/                # Device libraries
└── www/                # Web UI assets
```

All Python files are compiled to bytecode for efficiency. User data (`secrets.json`) is never included.

### manifest.json Format

Simplified manifest for compatibility verification:

```json
{
  "schema_version": "1.0.0",
  "version": "0.2.0",
  "target_machine_types": [
    "Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"
  ],
  "target_operating_systems": [
    "circuitpython_9_3",
    "circuitpython_10_1"
  ],
  "release_type": "production",
  "release_notes": "Added OTA updates",
  "release_date": "2025-10-15T12:00:00Z",
  "git_commit": "abc123"
}
```

No file lists, removal patterns, or install scripts - the full reset strategy doesn't need them.

## releases.json Structure

Multi-platform master manifest:

```json
{
  "schema_version": "1.0.0",
  "last_updated": "2025-10-16T12:00:00Z",
  "releases": [
    {
      "target_machine_types": ["Adafruit Feather ESP32S3..."],
      "target_operating_systems": ["circuitpython_9_3", "circuitpython_10_1"],
      "production": {
        "version": "0.2.0",
        "release_notes": "Added OTA updates",
        "zip_url": "https://github.com/.../v0.2.0/wicid_install.zip",
        "release_date": "2025-10-15T12:00:00Z",
        "git_commit": "abc123"
      },
      "development": {
        "version": "0.2.1",
        ...
      }
    }
  ]
}
```

The build tool maintains this automatically - you don't edit it manually.

## Installation on Device

When a device downloads an update:

1. **Download**: ZIP saved to `/pending_update/`
2. **Extract**: Contents extracted to `/pending_update/root/`
3. **Restart**: Device reboots immediately
4. **Verify**: Bootloader checks compatibility:
   - Machine type must match
   - OS version must be compatible  
   - Version must be newer
   - Not previously marked incompatible
5. **Install**: If compatible, perform full reset:
   - Delete all existing firmware
   - Preserve `/secrets.json` and `/incompatible_releases.json`
   - Move new files to root
6. **Reboot**: Device starts with new firmware

If incompatible, the release is marked to prevent retry loops and the device boots with current firmware.

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
./build.py

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

```bash
pip install mpy-cross
```

### Git tag already exists

```bash
# Delete local tag
git tag -d v0.2.0

# Delete remote tag if pushed
git push origin :refs/tags/v0.2.0
```

### GitHub Actions fails

Check workflow logs for:
- Missing `WICID_WEB_TOKEN` secret
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
SYSTEM_UPDATE_CHECK_HOUR = 2
WEATHER_UPDATE_INTERVAL = 1200
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
├── build.py                 # Build tool
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
