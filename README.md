# WICID Weather Indicator

## Overview
WICID (Weather Indicator and Climate Information Device) is an intelligent weather indicator that provides at-a-glance weather information through colored LED feedback. The device is designed to be simple, intuitive, and visually appealing, providing weather updates without requiring a screen. It features an easy Wi-Fi setup through a captive portal for seamless network configuration.

See the product website at: https://www.wicid.ai

## Features

- **Temperature Display**: Shows current temperature through LED color gradients
- **Precipitation Alerts**: Visual precipitation probability indication through blinking patterns
- **Multiple Modes**: Includes both live weather and demonstration modes
- **WiFi Connectivity**: Fetches real-time weather data using WiFi
- **Setup Portal**: Easy Wi-Fi network setup through a web interface
- **Button Control**: Simple button interface to cycle through different modes and access setup
- **Over-the-Air (OTA) Updates**: Automatic firmware updates from remote server
  - First scheduled check runs shortly after startup
  - Subsequent checks follow a configurable hourly cadence
  - Support for production and development release channels
  - Automatic download and installation with device restart

## How It Works

### Hardware Components
- Microcontroller with WiFi capability (e.g., Adafruit Feather)
- NeoPixel LED
- Tactile button (for mode switching and setup access)
- Power supply

### Software Architecture

WICID uses a manager-based architecture with clear separation of concerns:

1. **Main Orchestrator** (`code_support.py`):
   - Coordinates system initialization and startup
   - Handles fatal error recovery
   - Delegates responsibilities to specialized managers

2. **Configuration Manager**:
   - Manages the complete configuration lifecycle
   - Automatically enters setup mode when configuration is missing or invalid
   - Validates WiFi credentials before committing changes
   - Integrates firmware update checks after successful connection

3. **WiFi Manager**:
   - Centralizes all WiFi operations (station mode and access point)
   - Manages connection retry logic with exponential backoff
   - Provides HTTP sessions for weather and update services

4. **Mode Manager**:
   - Orchestrates user-selectable operating modes (weather display, demos)
   - Handles button-based mode switching
   - Provides consistent error recovery across modes
   - Extensible design for adding new display modes

5. **Update Manager**:
   - Schedules an initial post-boot update check (default 60 seconds after startup)
   - Performs recurring checks using the configured interval
   - Downloads and verifies update packages
   - Performs full-reset installations to ensure consistency

6. **System Monitor**:
   - Performs periodic health checks
   - Coordinates scheduled maintenance operations

7. **Shared Resources** (singletons):
   - **Pixel Controller**: LED animations and visual feedback
   - **Logging**: Structured logging with configurable verbosity
   - **Weather Service**: Fetches data from Open-Meteo API

The architecture emphasizes encapsulation, error resilience, and extensibility. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for detailed design documentation.

### Weather Data

The device fetches weather data including:
- Current temperature
- Daily high temperature
- Precipitation probability

### Visual Feedback

- **Temperature**: Displayed through LED color (blue for cold, green for moderate, red for hot)
- **Precipitation**: Indicated through blinking patterns (number of blinks corresponds to precipitation probability)

## Initial Setup

### Initial Setup

1. **Enter Setup Mode**:
   - On first boot (or after a factory reset), the device will automatically enter Access Point (AP) mode
   - The LED will pulse white to indicate setup mode is active
   - Alternatively, manually enter setup mode by pressing and holding the mode button for 3+ seconds until the LED begins pulsing white

2. **Connect to WICID**:
   - Using a smartphone or computer, connect to the "WICID-Setup" Wi‑Fi network
   - Navigate to: **http://192.168.4.1/**
   - Important: Use HTTP (not HTTPS) and include the trailing slash to avoid browser search behavior.

3. **Configure Settings**:
   - The web interface will show all configurable settings
   - Any previously configured settings will be pre-populated
   - Configure the following:
     - Wi-Fi network credentials
     - Location (ZIP code or coordinates)
     - Weather API settings

4. **Save and Reboot**:
   - Click "Save & Reboot" (or "Save & Connect") to apply settings
   - The LED will flash green 3 times to confirm successful configuration
   - The device will automatically reboot and connect to your Wi-Fi network

   Note: If saving fails with a read‑only filesystem error, the device is likely connected over USB. Unplug the USB cable or eject the CIRCUITPY drive before saving, then try again.

5. **Exit Setup (Without Changes)**:
   - To exit setup mode without saving changes, press the mode button
   - The device will reboot with previous settings

## Usage

1. **Power On**:
   - The device will attempt to connect to the configured Wi-Fi network
   - If no network is configured, it will automatically enter setup mode (LED pulses white)

2. **Normal Operation**:
   - LED displays current weather information using color gradients
   - Press the mode button to cycle through different display modes
   - In demo modes, the LED will cycle through temperature and precipitation patterns

3. **Setup Mode**:
   - LED pulses white when in setup mode
   - See the "Initial Setup" section for complete instructions
   - On successful setup, LED will flash green 3 times before rebooting

## Setup Portal Notes and Troubleshooting

### Captive Portal Functionality

WICID includes intelligent captive portal detection that automatically redirects devices to the setup interface:

- **Automatic Detection**: When you connect to "WICID-Setup", most devices will automatically detect the captive portal and show a notification or popup
- **Cross-Platform Support**: Works with Android, iOS, Windows, macOS, and Linux devices
- **DNS Interception**: All domain name requests are redirected to the setup portal (192.168.4.1)
- **Fallback Mode**: If DNS interception fails, the setup portal continues to work via direct HTTP access

**How It Works**:
- Your device performs connectivity checks when joining the WICID-Setup network
- WICID intercepts these checks and redirects them to the setup interface
- This triggers your device's captive portal detection, showing a "Sign in to network" notification
- Tapping the notification opens the WICID setup interface automatically

### Setup Access

- **Automatic (Recommended)**: Connect to "WICID-Setup" and follow the captive portal notification
- **Direct access**: Navigate to **http://192.168.4.1/** if automatic detection doesn't work
- **Use HTTP, not HTTPS**: Always use HTTP URLs for setup access

### Troubleshooting

**If captive portal doesn't appear automatically**:
- Wait 10-15 seconds after connecting for detection to complete
- Try opening a web browser and navigating to any website (e.g., google.com)
- Navigate directly to http://192.168.4.1/
- Ensure you type "http://192.168.4.1/" exactly (include http:// and trailing slash)

**Mobile device issues**:
- Disable mobile data or enable *Airplane Mode* (keeping WiFi on) to prevent bypassing the captive portal
- Some devices may show "No internet connection" - this is normal, tap "Use network as is" or similar option
- If the setup page doesn't load, try navigating directly to http://192.168.4.1/

**Desktop browser issues**:
- Browsers may default to search or HTTPS if you don't include the full URL
- Try a different browser if one doesn't work
- Clear browser cache if you've connected to WICID-Setup before

**Connection problems**:
- Ensure you're connected to "WICID-Setup" network (not your regular WiFi)
- Check that WiFi is enabled and airplane mode is off (except for mobile data)
- Restart WiFi on your device if connection fails

**Saving settings**: If you see a read‑only filesystem error while saving, try plugging the WICID into a power-only USB cable (when connected to a computer with a data-enabled USB cable, the WICID may behave like a thumbdrive and prevent config updates through the setup interface)

## Error Handling

The device includes robust error handling and will:
- Automatically enter setup mode if it cannot connect to the configured Wi-Fi network
- Attempt to reconnect to the last known good network
- Enter setup mode if no valid network configuration is found
- Handle API request failures gracefully
- Recover from invalid data responses

## Developer Setup

### Prerequisites
- Python version 3.13+
- `circup` for managing CircuitPython libraries
- (Optional) Mu Editor for code editing and serial console

### Required Libraries

Install the following Python packages for building firmware:

```bash
pip install circup rcssmin rjsmin htmlmin beautifulsoup4
```

**Note**: For consistent package versions across the project, consider using `pipenv` with the included `Pipfile` and `Pipfile.lock`. See [pipenv](https://pipenv.pypa.io/) for installation and usage instructions.

**Required packages:**
- `circup`: Manages CircuitPython libraries in `/src/lib/`
- `rcssmin`: CSS minification for captive portal web assets
- `rjsmin`: JavaScript minification for captive portal web assets
- `htmlmin`: HTML minification for captive portal web assets
- `beautifulsoup4`: HTML parsing for combining CSS/JS into single-file HTML

**Build tools:**
- `mpy-cross`: CircuitPython bytecode compiler (must match target CircuitPython version)
  - See [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md) for installation instructions

**Optional packages:**
- `python-dotenv`: For `.env` file support in `installer.py` (simulated OTA updates)

### Filesystem Modes

The device uses `boot.py` to control filesystem access. By default, it runs in **Production Mode** which allows the setup portal to save configuration files but disables USB mass storage.

**Production Mode** (default):
- Filesystem is writable from code (setup portal can save credentials)
- USB mass storage is disabled
- USB serial console is enabled for monitoring and debugging
- Used for normal operation and by customers

**Safe Mode** (for development):
- USB mass storage is enabled (CIRCUITPY drive appears on your computer)
- Filesystem is read-only from code
- Used for development and file updates
- Automatically triggered by special button sequence

**To Access Files for Development:**

1. **While the device is running** (in any mode - weather, demo, setup, etc.):
   - Press and HOLD the mode button
   - At 3 seconds: LED pulses white (setup mode threshold)
   - At 10 seconds: LED changes to flashing blue/green (Safe Mode threshold)
   - Release the button when you see blue/green flashing
   - The device will automatically reboot into **Safe Mode**
   - The CIRCUITPY drive will appear and you can edit files

2. **Return to Production Mode:**
   - Simply press RESET without holding any button
   - Or make your changes and the device returns to production mode on next normal boot

**Button Hold Durations:**
- **Short press** (< 3 seconds): Switch to next mode
- **3 second hold**: Enter setup mode (LED pulses white at 3s)
- **10 second hold**: Enter Safe Mode (LED flashes blue/green at 10s)

**Alternative: Force Safe Mode via Serial Console**

If needed, you can also trigger Safe Mode from the REPL:
1. Connect to serial console (115200 baud) in Mu Editor or Terminal
2. Press RESET to get to the REPL prompt (`>>>`)
3. Paste this command:
   ```python
   import microcontroller; microcontroller.on_next_reset(microcontroller.RunMode.SAFE_MODE); microcontroller.reset()
   ```
4. The device will boot into Safe Mode with USB access enabled

### Configuration Files

WICID uses two configuration files:

#### `settings.toml` - System Configuration
System-level settings deployed with firmware updates:
```toml
VERSION = "0.5.0"
SYSTEM_UPDATE_MANIFEST_URL = "https://www.wicid.ai/releases.json"
SYSTEM_UPDATE_CHECK_INTERVAL = 4  # hours
PERIODIC_REBOOT_INTERVAL = 24  # hours (0 to disable)
WEATHER_UPDATE_INTERVAL = 1200  # seconds
```

Read via `os.getenv()` in device code. Managed by build system.

#### `secrets.json` - User Data
User-specific credentials, preserved across firmware updates:
```json
{
  "ssid": "your_wifi_ssid",
  "password": "your_wifi_password",
  "weather_zip": "12345"
}
```

**Note**: `secrets.json` is created by Setup Mode and preserved during OTA updates.

### Code Structure
- `code_support.py`: Main orchestrator and system initialization
- `boot_support.py`: Bootloader with compatibility checks and update installation
- `configuration_manager.py`: Configuration lifecycle and setup portal orchestration
- `wifi_manager.py`: WiFi connectivity and credential management
- `mode_manager.py`: Mode orchestration and button handling
- `mode_interface.py`: Base class defining mode contract
- `modes.py`: Mode implementations (weather display, demos)
- `update_manager.py`: OTA update logic with device self-identification
- `system_monitor.py`: Periodic health checks and maintenance
- `weather.py`: Weather data fetching and processing
- `pixel_controller.py`: LED control and animations
- `dns_interceptor.py`: Captive portal DNS for setup interface
- `logging_helper.py`: Structured logging configuration
- `wifi_retry_state.py`: Connection retry state tracking
- `zipfile_lite.py`: Custom ZIP extraction using zlib
- `utils.py`: Device detection, compatibility checks, and shared utilities
- `settings.toml`: System configuration (version controlled)
- `secrets.json`: User credentials (device-specific, preserved during updates)
- `lib/`: CircuitPython libraries
- `www/`: Web interface files for the setup portal
- `docs/`: Architecture and build process documentation
- `wicid_circuitpy_requirements.txt`: CircuitPython library dependencies

### Flashing and Building

#### Initial Board Setup (for new Adafruit Feather ESP32-S3 boards)

Before flashing the application, new boards must be initialized with CircuitPython. This process updates the bootloader and installs CircuitPython:

1. **Enter Bootloader Mode**:
   - Connect the Feather to your development computer using a data-enabled USB-C cable
   - Press and HOLD the BOOT button
   - While holding BOOT, press and release the RESET button
   - Release the BOOT button once the board enters bootloader mode (LED should not be flashing)

2. **Update Bootloader**:
   - Visit: https://circuitpython.org/board/adafruit_feather_esp32s3_4mbflash_2mbpsram/
   - Click "OPEN INSTALLER"
   - Select "Install Bootloader Only" and follow the prompts
   - After installation completes, you should see an updated `FTHRS3BOOT` drive

3. **Install CircuitPython**:
   - While in bootloader mode (indicated by solid green LED and availability of `FTHRS3BOOT` drive)
   - From the same CircuitPython page, download the latest `.UF2` file
   - Drag the downloaded `.UF2` file to the `FTHRS3BOOT` drive
   - The board will reboot automatically and you should now see a `CIRCUITPY` drive

   **Note**: If installing a new OS without first updating the Bootloader, follow the steps in number 1 to get into bootloader mode.

The board is now ready for library installation and application deployment.

#### Managing CircuitPython Libraries in /src/lib/

The `/src/lib/` directory is maintained in source control to facilitate OTA updates. Unlike the typical CircuitPython workflow where libraries are installed directly on the microcontroller, this project requires managing libraries from your development machine.

**Adding or Removing Libraries:**

1. **Install circup** (if not already installed):
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

### Installing Firmware with the Installer Script (Optional)

After building a release package, you can use the `installer.py` script for guided firmware installation:

```bash
python installer.py
```

The installer provides three installation modes:

**SOFT Update (OTA-like)**
- Safer installation method
- Files are staged in `/pending_update/` on the device
- Installation completes automatically on next reboot
- Recommended for most users

**HARD Update (Full Replacement)**
- Immediate installation
- Deletes all files on CIRCUITPY drive (except `secrets.json`)
- Useful for clean installations or troubleshooting
- Requires explicit confirmation

**Simulated OTA Update (Local Development)**
- Starts local WICID Web application server
- Points device to local server for OTA updates
- Tests complete OTA update flow in development environment
- Requires WICID Web repository at `../wicid_web` (configurable via `.env` file)
- Optional: Install `python-dotenv` for `.env` support (`pip install python-dotenv`)

The installer will:
1. Auto-detect your CIRCUITPY device
2. Verify the `releases/wicid_install.zip` package exists
3. Guide you through the installation process
4. Clean up temporary files and system artifacts
5. Provide next steps for completing the update

This is particularly useful for:
- Initial device setup and flashing
- Manual firmware updates during development
- Testing OTA update mechanisms locally
- Troubleshooting device issues with clean installations

## Over-the-Air (OTA) Updates

WICID devices support automatic firmware updates with a full-reset strategy for guaranteed consistency.

### How It Works

1. **Automatic Checking**: Device checks for updates on every boot and daily at 2am (configurable)
2. **Device Identification**: Device determines its own hardware type and OS version at runtime
3. **Compatibility Check**: Compares available releases against device capabilities using semantic versioning
4. **Download**: If compatible newer version found, downloads complete firmware package
5. **Verification**: On next boot, bootloader verifies compatibility before installation, marks incompatible releases to prevent retry loops
6. **Full Reset Installation**: If verification passes, device replaces all firmware files (preserves user data) and reboots

### Update Strategy

WICID uses **full reset** updates:
- Every update completely replaces all firmware files
- User data (`secrets.json`) is always preserved
- No partial updates or migrations needed
- Guarantees consistent device state

### Release Channels

- **Production** (default): Stable releases
- **Development**: Beta/experimental releases

To switch to development channel, create an empty `/DEVELOPMENT` file on the device:
```python
with open("/DEVELOPMENT", "w") as f:
    f.write("")
```

### Configuration

Update behavior is configured in `settings.toml`:
- `SYSTEM_UPDATE_MANIFEST_URL`: URL of update manifest (default: `https://www.wicid.ai/releases.json`)
- `SYSTEM_UPDATE_CHECK_INTERVAL`: Hours between update checks (default: 24)
- `VERSION`: Current firmware version

Devices self-identify their hardware type and OS version at runtime - no hardcoded platform IDs needed.

### Server Setup

To host firmware updates, you need:
1. A JSON manifest listing available versions
2. ZIP files containing firmware releases
3. HTTPS hosting (GitHub Releases, static hosting, etc.)


### Creating Update Packages

Use the automated build tool:

```bash
# Interactive build - prompts for all options
./builder.py

# Non-interactive build (for GitHub Actions)
python builder.py --build
```

The build tool:
- Compiles Python to bytecode (`.mpy`) for faster loading
- Generates `manifest.json` with version and installation instructions
- Updates `releases.json` for device discovery
- Creates GitHub tag for automated deployment
- Packages everything into a ZIP file

See [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md) for complete build guide.

### Monitoring Updates

Device logs show update activity:
```
Checking for firmware updates...
Update available: 1.2.3
Release notes: Stability improvements
Downloading update...
Update downloaded successfully
Restarting to install update...
```

After restart:
```
FIRMWARE UPDATE DETECTED
Installing update from: firmware-1.2.3.zip
Update installation complete
```

### Current Implementation Status

The OTA update system is **fully functional**:
- ✅ Device self-identification (hardware type and OS version)
- ✅ Multi-platform release support
- ✅ Compatibility verification before installation
- ✅ Full reset installation strategy
- ✅ Incompatible release tracking
- ✅ Checking for updates on boot and scheduled times
- ✅ ZIP extraction and installation (custom implementation using `zlib`)
- ✅ Automatic cleanup after installation
- ✅ GitHub Actions automated build and deployment
- ✅ Cross-repository manifest synchronization



### Repository Structure
Note this structure is subject to frequent changes. See the actual source for the most up-to-date information.

```
wicid_firmware/
├── src/                    # Device firmware
│   ├── settings.toml      # System configuration
│   ├── manifest.json      # Build defaults (gitignored)
│   ├── boot.py            # Bootloader with compatibility checks
│   ├── code.py            # Main application loop
│   ├── update_manager.py  # OTA update logic
│   ├── zipfile_lite.py    # Custom ZIP extraction
│   ├── weather.py         # Weather API integration
│   ├── wifi_manager.py    # WiFi connectivity
│   ├── modes.py           # Display modes
│   ├── utils.py           # Device detection and utilities
│   ├── pixel_controller.py # LED control
│   ├── setup_portal.py    # Setup portal
│   ├── lib/               # Device libraries
│   └── www/               # Setup portal web UI
├── builder.py             # Build tool (interactive + CI)
├── installer.py           # Manual firmware installer (SOFT/HARD modes)
├── releases.json          # Master update manifest
├── releases/              # Build artifacts (gitignored)
├── .github/
│   ├── workflows/
│   │   └── release.yml    # Automated build pipeline
│   └── files-sync-config.yml # Cross-repo sync config
└── docs/
    └── BUILD_PROCESS.md   # Build guide
```



## License

© 2025 WICID. All rights reserved.

This software and its documentation are proprietary and confidential. Unauthorized copying, distribution, modification, public display, or public performance of this software is strictly prohibited.

No part of this software may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of WICID, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.

For permission requests, please contact the copyright holder.