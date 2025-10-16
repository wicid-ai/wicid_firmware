# WICID Update Server Specification

## Overview

This document specifies how to implement an update server for WICID devices. The update system uses a JSON manifest to advertise available firmware versions and provides ZIP file downloads for full-reset installation.

## Update Strategy

WICID uses a **full reset** strategy for firmware updates:
- Every update replaces **all** firmware files (all-or-nothing)
- Only exceptions: `/secrets.json` and `/incompatible_releases.json` are preserved
- No partial updates, no file removal lists, no install scripts
- Guarantees consistent device state regardless of previous version
- Simplifies update logic and eliminates edge cases

## Update Flow

1. Device boots and connects to WiFi
2. Device determines its characteristics at runtime:
   - Current firmware version (from `settings.toml`)
   - Machine type (from `os.uname().machine`)
   - OS version (from `sys.implementation.version`)
   - Update manifest URL (from `settings.toml`)
3. Device checks for `/development` file to determine release channel
4. Device requests manifest from server with device information in User-Agent header
5. Server responds with manifest containing available releases
6. Device checks compatibility for each release:
   - Machine type must match
   - OS version must be compatible (semantic versioning)
   - Version must be newer than current
   - Release must not be marked as incompatible
7. If compatible update found, device downloads ZIP file
8. Device extracts ZIP to `/pending_update/root/` directory
9. Device restarts immediately
10. On boot, boot loader:
    - Reads `/pending_update/root/manifest.json`
    - Verifies compatibility (machine, OS, version)
    - If compatible: performs full reset and installs
    - If incompatible: marks release as incompatible and aborts
11. Device boots into new version

## Manifest Format

### URL
The manifest URL is configurable in `settings.toml` and defaults to:
```
https://www.wicid.ai/releases.json
```

### Request Headers
Devices include identification information in the User-Agent header:
```
User-Agent: WICID/{version} ({machine_type}; {os_version}; ZIP:{weather_zip})
```

Example:
```
User-Agent: WICID/0.1.0 (Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3; circuitpython_10_1; ZIP:12345)
```

### Manifest Schema

Multi-platform releases.json structure:

```json
{
  "schema_version": "1.0.0",
  "last_updated": "2025-10-16T12:00:00Z",
  "releases": [
    {
      "target_machine_types": [
        "Adafruit Feather ESP32S3 4MB Flash 2MB PSRAM with ESP32S3"
      ],
      "target_operating_systems": [
        "circuitpython_9_3",
        "circuitpython_10_1"
      ],
      "production": {
        "version": "0.2.0",
        "release_notes": "Added OTA update support",
        "zip_url": "https://github.com/bmcnaboe/wicid_firmware/releases/download/v0.2.0/wicid_install.zip",
        "release_date": "2025-10-15T12:00:00Z",
        "git_commit": "abc123"
      },
      "development": {
        "version": "0.2.1",
        "release_notes": "New experimental features",
        "zip_url": "https://github.com/bmcnaboe/wicid_firmware/releases/download/v0.2.1/wicid_install.zip",
        "release_date": "2025-10-16T12:00:00Z",
        "git_commit": "def456"
      }
    }
  ]
}
```

### Schema Fields

- `schema_version`: Version of the manifest format (currently "1.0.0")
- `last_updated`: ISO 8601 timestamp of last manifest update
- `releases`: Array of release entries (one per hardware/OS combination)
  - `target_machine_types`: Array of machine type strings (from `os.uname().machine`)
  - `target_operating_systems`: Array of OS version strings (format: `os_major_minor`)
  - `production`: Stable release channel (default)
  - `development`: Development/beta release channel
    - `version`: Semantic version string (e.g., "1.2.3" or "1.3.0-beta.2")
    - `release_notes`: Human-readable description of changes
    - `zip_url`: HTTPS URL to downloadable ZIP file (always named `wicid_install.zip`)
    - `release_date`: ISO 8601 timestamp
    - `git_commit`: Git commit hash

### Device Compatibility Matching

Devices use the following logic to find compatible releases:

1. **Machine Type**: Device's `get_machine_type()` must be in `target_machine_types` array
2. **OS Version**: Device's OS must match one of the `target_operating_systems` using semantic versioning
   - Example: Device with `circuitpython_10_1` matches `circuitpython_10_1` and `circuitpython_10_0`
   - Does not match `circuitpython_9_3` or `circuitpython_11_0`
3. **Version**: Release version must be newer than device's current version
4. **Not Incompatible**: Release must not be in `/incompatible_releases.json`

## Release Package Format

### ZIP File Structure

Release packages are always named `wicid_install.zip` and contain **complete** firmware files. The device performs a full reset installation (all-or-nothing).

```
wicid_install.zip
├── manifest.json           # Compatibility information
├── settings.toml          # System configuration (includes VERSION)
├── boot.mpy               # Compiled bytecode
├── code.mpy
├── modes.mpy
├── pixel_controller.mpy
├── setup_portal.mpy
├── update_manager.mpy
├── utils.mpy
├── weather.mpy
├── wifi_manager.mpy
├── zipfile_lite.mpy
├── lib/                   # Device libraries
│   └── (CircuitPython libraries)
└── www/                   # Web UI
    ├── design-tokens.css
    ├── favicon.svg
    ├── index.html
    └── main.js
```

**Notes**:
- All `.py` files are compiled to `.mpy` bytecode
- `secrets.json` is NOT included (device-specific, preserved during update)
- No `install.py` script (full reset strategy doesn't need it)
- No file removal lists (everything is replaced)

### Manifest File (manifest.json)

Each ZIP package includes a simplified `manifest.json` for compatibility verification:

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
  "release_notes": "Added OTA update support",
  "release_date": "2025-10-15T12:00:00Z",
  "git_commit": "abc123"
}
```

### Manifest Fields

- `schema_version`: Manifest format version ("1.0.0")
- `version`: Firmware semantic version
- `target_machine_types`: Array of compatible machine type strings
- `target_operating_systems`: Array of compatible OS version strings  
- `release_type`: "production" or "development"
- `release_notes`: Human-readable changelog
- `release_date`: ISO 8601 timestamp
- `git_commit`: Short git commit hash

### Installation Process

1. **Download**: Device downloads ZIP to `/pending_update/`
2. **Extract**: ZIP contents extracted to `/pending_update/root/`
3. **Restart**: Device reboots immediately
4. **Verify**: Boot loader reads `/pending_update/root/manifest.json`
5. **Check Compatibility**:
   - Machine type must match
   - OS version must be compatible (semantic)
   - Version must be newer
   - Not marked as incompatible
6. **Full Reset** (if compatible):
   - Delete ALL files/directories in root
   - Preserve `/secrets.json` and `/incompatible_releases.json`
   - Move all files from `/pending_update/root/` to `/`
   - Delete `/pending_update/` directory
7. **Reboot**: Device restarts into new firmware
8. **Rollback** (if incompatible):
   - Mark version as incompatible
   - Delete `/pending_update/` directory
   - Boot into current firmware

### Important Notes

1. **Full Reset Strategy**: Every update is complete replacement of all firmware files
2. **ZIP Extraction**: Custom `zipfile_lite.py` parser with `zlib` decompression
3. **Bytecode Compilation**: All `.py` files compiled to `.mpy` for speed and size
4. **Preservation**: Only `/secrets.json` and `/incompatible_releases.json` survive updates
5. **Compatibility First**: Updates verify compatibility before making any changes
6. **Incompatible Tracking**: Failed installs are remembered to prevent retry loops
7. **Guaranteed Consistency**: Full reset ensures identical state across all devices

## Incompatible Release Tracking

If a device determines that a downloaded update is incompatible (wrong machine type, OS version, or other issue), it marks that release as incompatible to prevent retrying the same failed update.

### incompatible_releases.json Structure

```json
{
  "versions": [
    "0.1.5",
    "0.2.0-beta.1"
  ]
}
```

### Tracking Logic

1. Device downloads and extracts update
2. Boot loader verifies compatibility
3. If incompatible:
   - Add version to `/incompatible_releases.json`
   - Delete `/pending_update/` directory
   - Boot into current firmware
4. On future update checks:
   - Skip versions in incompatible list
   - Keeps last 10 entries (prevents file growth)

This prevents endless retry loops when a device encounters an incompatible release.

## Version Comparison

The device uses semantic versioning with the following comparison rules:

1. Version strings are parsed as `MAJOR.MINOR.PATCH[-PRERELEASE]`
2. Numeric comparison of MAJOR, MINOR, PATCH (left to right)
3. Pre-release versions (with `-` suffix) are considered lower than release versions with the same MAJOR.MINOR.PATCH
4. Examples:
   - `0.1.0` < `0.2.0` < `1.0.0` < `1.0.1`
   - `1.2.3-beta.1` < `1.2.3` (pre-release < release)
   - `1.2.3` = `1.2.3` (no update)

## Release Channels

Devices select release channel based on filesystem state:

- **Production channel** (default): Device downloads from `releases.production`
- **Development channel**: Device downloads from `releases.development` if `/development` file exists on device

To switch a device to development channel:
```python
# Create empty marker file
with open("/development", "w") as f:
    f.write("")
```

To switch back to production:
```python
import os
os.remove("/development")
```

## Update Schedule

Devices check for updates:
1. **On every boot**: Immediate check after WiFi connection
2. **Daily scheduled check**: At configured hour (default 2:00 AM local time)

Schedule is configurable via `SYSTEM_UPDATE_CHECK_HOUR` in `settings.toml`.

## Implementation Using GitHub Releases

### Build and Release Workflow

WICID uses a two-step automated release process:

1. **Local Build Tool** (`build.py`):
   - Interactive CLI prompts for release details
   - Updates `VERSION` in `src/settings.toml`
   - Generates `src/manifest.json` 
   - Updates `releases.json` with new release info
   - Creates git tag (`v{version}`)
   - Stages files for commit

2. **GitHub Actions Automation**:
   - Triggered on push of `v*` tags
   - Compiles all `.py` files to `.mpy` bytecode
   - Creates `wicid_install.zip` package
   - Attaches ZIP to GitHub Release
   - Syncs `releases.json` to `wicid_web` repository

### Example Release Process

```bash
# Run interactive build tool
./build.py

# Interactive prompts:
#   1. Target Machine Types: [Adafruit Feather ESP32S3...]
#   2. Target Operating Systems: [circuitpython_10_1]
#   3. Release Type: [Production]
#   4. Version: [0.2.0]
#   5. Release Notes: > Added OTA updates

# Review staged changes
git diff --staged

# Commit and push (triggers GitHub Actions)
git commit -m "Release 0.2.0"
git push && git push --tags

# GitHub Actions automatically:
#   - Builds wicid_install.zip
#   - Creates GitHub Release v0.2.0
#   - Attaches wicid_install.zip to release
#   - Syncs releases.json to wicid_web repo
#   - Netlify deploys updated releases.json
```

### GitHub Asset URLs

Release assets use stable GitHub URLs:
```
https://github.com/{owner}/{repo}/releases/download/v{version}/wicid_install.zip
```

Example:
```
https://github.com/bmcnaboe/wicid_firmware/releases/download/v0.2.0/wicid_install.zip
```

Note: ZIP file is always named `wicid_install.zip` (not version-specific)

## Security Considerations

### Current Implementation

- No cryptographic verification of update packages
- Relies on HTTPS for transport security
- Update server URL is configurable but not authenticated

### Future Enhancements

Consider implementing:
1. **Checksum verification**: SHA256 hash in manifest, verified before installation
2. **Code signing**: Cryptographic signatures on update packages
3. **Rollback protection**: Version monotonicity enforcement
4. **Secure storage**: Protected update manifest URL

## Server Requirements

### Minimum Requirements

- Static file hosting with HTTPS
- Ability to serve JSON and ZIP files
- Support for CORS headers (if updates accessed from web interface)

### Recommended Hosting Options

1. **GitHub Pages**: Free static hosting, integrates with GitHub releases
2. **Cloudflare Pages**: Free static hosting with CDN
3. **AWS S3 + CloudFront**: Scalable, pay-per-use
4. **Netlify**: Free static hosting with automatic HTTPS

### Example nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name www.wicid.ai;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    root /var/www/wicid;
    
    # Serve manifest
    location = /releases.json {
        add_header Content-Type application/json;
        add_header Cache-Control "no-cache, must-revalidate";
    }
    
    # Serve update packages
    location /releases/ {
        add_header Content-Type application/zip;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }
}
```

## Testing

### Test Manifest

Create a test manifest for development:

```json
{
  "schema_version": "2.0.0",
  "target_systems": [
    {
      "id": "ESP32S3_FEATHER_4MBFLASH_2MB_PSRAM",
      "releases": {
        "production": {
          "version": "999.0.0",
          "release_notes": "Test update - will always trigger update",
          "zip_url": "https://localhost:8000/test-update.zip"
        }
      }
    }
  ]
}
```

### Local Testing Server

```python
# simple_server.py
from http.server import HTTPServer, SimpleHTTPRequestHandler
import ssl

httpd = HTTPServer(('0.0.0.0', 8000), SimpleHTTPRequestHandler)
# For HTTPS testing:
# httpd.socket = ssl.wrap_socket(httpd.socket, certfile='./cert.pem', keyfile='./key.pem', server_side=True)
httpd.serve_forever()
```

### Testing Update Flow

1. Set test manifest URL in device `config.json`
2. Create test update package with higher version number
3. Observe device boot logs for update detection and download
4. Verify device restarts and installs update
5. Check version in `config.json` after update

## Troubleshooting

### Device not checking for updates

- Verify `system_update_manifest_url` in `config.json`
- Check WiFi connection status
- Review device logs for network errors

### Update downloads but doesn't install

- Check `/pending_update/` directory exists and contains ZIP file
- Review boot logs for installation errors
- Verify ZIP file format and contents

### Device keeps downloading same update

- Verify version string format in manifest
- Check that boot loader updates `version` in `config.json`
- Ensure version comparison logic matches expectations

## Appendix: Target System IDs

Current supported platforms:

- `ESP32S3_FEATHER_4MBFLASH_2MB_PSRAM`: Adafruit Feather ESP32-S3 (4MB Flash, 2MB PSRAM)

Additional platforms can be added as hardware variants are supported.

