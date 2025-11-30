# WICID Weather Indicator

[![License](https://img.shields.io/badge/license-Proprietary-blue)](LICENSE)

## Overview

WICID (Weather Indicator and Climate Information Device) is an intelligent weather indicator that provides at-a-glance weather information through colored LED feedback. The device is designed to be simple, intuitive, and visually appealing, providing weather updates without requiring a screen. It features an easy Wi-Fi setup through a captive portal for seamless network configuration.

See the product website at: [https://www.wicid.ai](https://www.wicid.ai)

## Features

- **Temperature Display**: Shows current temperature through LED color gradients
- **Precipitation Alerts**: Visual precipitation probability indication through blinking patterns
- **Multiple Modes**: Includes both live weather and demonstration modes
- **WiFi Connectivity**: Fetches real-time weather data using WiFi
- **Setup Portal**: Easy Wi-Fi network setup through a web interface
- **Button Control**: Simple button interface to cycle through different modes and access setup
- **Over-the-Air (OTA) Updates**: Automatic firmware updates from a remote server

## How It Works

### Hardware Components
- Microcontroller with WiFi capability (e.g., Adafruit Feather)
- NeoPixel LED
- Tactile button (for mode switching and setup access)
- Power supply

### Visual Feedback
- **Temperature**: Displayed through LED color (blue for cold, green for moderate, red for hot)
- **Precipitation**: Indicated through blinking patterns (number of blinks corresponds to precipitation probability)

## Quick Start

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

   *Note*: If saving fails with a read‑only filesystem error, the device is likely connected over USB. Unplug the USB cable or eject the CIRCUITPY drive before saving, then try again.

5. **Exit Setup (Without Changes)**:
   - To exit setup mode without saving changes, press the mode button
   - The device will reboot with previous settings

### Usage

1. **Power On**:
   - The device will attempt to connect to the configured Wi-Fi network
   - If no network is configured, it will automatically enter setup mode (LED pulses white)

2. **Normal Operation**:
   - LED displays current weather information using color gradients
   - Press the mode button to cycle through different display modes
   - In demo modes, the LED will cycle through temperature and precipitation patterns

3. **Setup Mode**:
   - LED pulses white when in setup mode
   - On successful setup, LED will flash green 3 times before rebooting

### Setup Portal Troubleshooting

#### Captive Portal
WICID includes intelligent captive portal detection that automatically redirects devices to the setup interface. When you connect to "WICID-Setup", most devices will automatically detect the captive portal and show a notification or popup.

**If captive portal doesn't appear automatically**:
- Wait 10-15 seconds after connecting for detection to complete
- Try opening a web browser and navigating to any website (e.g., google.com)
- Navigate directly to http://192.168.4.1/
- Ensure you type "http://192.168.4.1/" exactly (include http:// and trailing slash)

**Mobile device issues**:
- Disable mobile data or enable *Airplane Mode* (keeping WiFi on) to prevent bypassing the captive portal
- Some devices may show "No internet connection" - this is normal, tap "Use network as is" or similar option

**Desktop browser issues**:
- Browsers may default to search or HTTPS if you don't include the full URL
- Try a different browser if one doesn't work
- Clear browser cache if you've connected to WICID-Setup before

**Saving settings**: If you see a read‑only filesystem error while saving, try plugging the WICID into a power-only USB cable (when connected to a computer with a data-enabled USB cable, the WICID may behave like a thumbdrive and prevent config updates through the setup interface)

## Error Handling

The device includes robust error handling and will:
- Automatically enter setup mode if it cannot connect to the configured Wi-Fi network
- Attempt to reconnect to the last known good network
- Enter setup mode if no valid network configuration is found
- Handle API request failures gracefully
- Recover from invalid data responses

For detailed error handling strategy, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Developer Setup

### Prerequisites
- Python version 3.13+
- `pipenv` for managing Python dependencies
- (Optional) Mu Editor for code editing and serial console

### Quick Start

1. **Install `pipenv`** (if not already installed):
   ```bash
   pip install --user pipenv
   ```

2. **Install Project Dependencies**:
   ```bash
   pipenv install --dev
   pipenv sync --dev
   ```

3. **Install Git Hooks**:
   ```bash
   pipenv run pre-commit install
   ```

Now, when you run `git commit`, your code will be automatically formatted, checked for errors, and unit tests will be executed.

### Filesystem Modes

The boot script controls filesystem access. By default, it runs in **Production Mode** which allows the setup portal to save configuration files but disables USB mass storage.

**Production Mode** (default):
- Filesystem is writable from code (setup portal can save credentials)
- USB mass storage is disabled
- USB serial console is enabled for monitoring and debugging

**Safe Mode** (for development):
- USB mass storage is enabled (CIRCUITPY drive appears on your computer)
- Filesystem is read-only from code
- Automatically triggered by holding mode button for 10 seconds (LED flashes blue/green)

**To Access Files for Development:**
1. While the device is running, press and HOLD the mode button
2. At 3 seconds: LED pulses white (setup mode threshold)
3. At 10 seconds: LED changes to flashing blue/green (Safe Mode threshold)
4. Release the button when you see blue/green flashing
5. The device will automatically reboot into **Safe Mode**

**Return to Production Mode:**
- Simply press RESET without holding any button

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

- **`settings.toml`**: System-level settings deployed with firmware updates (version, update URLs, intervals). Read via `os.getenv()` in device code. Managed by build system.

- **`secrets.json`**: User-specific credentials (WiFi SSID/password, location), preserved across firmware updates. Created by Setup Mode.

### Testing

**Unit tests** can be run locally in your development environment. They are fully mocked and require no hardware:

```bash
python tests/run_tests.py
```

Unit tests are automatically executed as part of the pre-commit checks.

For complete testing documentation, including TDD workflow, integration tests, and best practices, see [`tests/README.md`](tests/README.md).

### Code Quality

This project uses `ruff` for code formatting/linting and `mypy` for static type checking. These tools are enforced automatically using `pre-commit` git hooks.

For detailed style guidelines, see [`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md). For code review guidelines, see [`docs/CODE_REVIEW_GUIDELINES.md`](docs/CODE_REVIEW_GUIDELINES.md).

### Building and Deployment

For information on:
- Building firmware releases
- Installing firmware manually
- OTA update architecture
- Release process

See [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md).

### Initial Board Setup

For new Adafruit Feather ESP32-S3 boards, you must initialize with CircuitPython before flashing the application. This process updates the bootloader and installs CircuitPython. See [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md) for build and deployment information.

### Managing CircuitPython Libraries

The `/src/lib/` directory is maintained in source control to facilitate OTA updates. For instructions on adding or removing libraries, see the build process documentation.

## Over-the-Air (OTA) Updates

WICID devices support automatic firmware updates with a full-reset strategy for guaranteed consistency. The system:
- Checks for updates on boot and at configured intervals
- Self-identifies hardware type and OS version at runtime
- Downloads and verifies update packages with checksum validation
- Performs full-reset installations (preserves user data)
- Supports production and development release channels

For complete OTA update documentation, including architecture, configuration, and troubleshooting, see [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md).

## Documentation

- **Architecture**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - System design, manager patterns, error handling
- **Patterns Cookbook**: [`docs/PATTERNS_COOKBOOK.md`](docs/PATTERNS_COOKBOOK.md) - Concrete code examples and patterns
- **Style Guide**: [`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md) - Coding conventions and standards
- **Scheduler Architecture**: [`docs/SCHEDULER_ARCHITECTURE.md`](docs/SCHEDULER_ARCHITECTURE.md) - Cooperative scheduler design
- **Code Review Guidelines**: [`docs/CODE_REVIEW_GUIDELINES.md`](docs/CODE_REVIEW_GUIDELINES.md) - Review checklist and standards
- **Build Process**: [`docs/BUILD_PROCESS.md`](docs/BUILD_PROCESS.md) - Release process, OTA updates, deployment
- **Testing**: [`tests/README.md`](tests/README.md) - Testing strategy, TDD workflow, best practices

## License

© 2025 WICID. All rights reserved.

This software and its documentation are proprietary and confidential. Unauthorized copying, distribution, modification, public display, or public performance of this software is strictly prohibited.

No part of this software may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of WICID, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.

For permission requests, please contact the copyright holder.
