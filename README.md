# WICID Weather Indicator

## Overview
WICID (Weather Indicator and Climate Information Device) is an intelligent weather indicator that provides at-a-glance weather information through colored LED feedback. The device is designed to be simple, intuitive, and visually appealing, providing weather updates without requiring a screen. It features an easy Wi-Fi setup through a captive portal for seamless network configuration.

## Features

- **Temperature Display**: Shows current temperature through LED color gradients
- **Precipitation Alerts**: Visual precipitation probability indication through blinking patterns
- **Multiple Modes**: Includes both live weather and demonstration modes
- **WiFi Connectivity**: Fetches real-time weather data using WiFi
- **Setup Portal**: Easy Wi-Fi network setup through a web interface
- **Button Control**: Simple button interface to cycle through different modes and access setup

## How It Works

### Hardware Components
- Microcontroller with WiFi capability (e.g., Adafruit Feather)
- NeoPixel LED
- Tactile button (for mode switching and setup access)
- Power supply

### Software Architecture

The firmware is organized into several key components:

1. **Main Loop** (`code.py`):
   - Initializes hardware components
   - Manages mode switching
   - Handles error recovery

2. **Weather Module** (`weather.py`):
   - Manages WiFi connectivity
   - Fetches weather data from Open-Meteo API
   - Handles geocoding of ZIP codes
   - Provides weather data to other components

3. **Modes** (`modes.py`):
   - `run_current_weather_mode`: Shows live weather data
   - `run_temp_demo_mode`: Demonstrates temperature color range
   - `run_precip_demo_mode`: Demonstrates precipitation indication
   - `run_setup_mode`: Handles Wi-Fi and location configuration via setup portal

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

- **Direct access**: Always use **http://192.168.4.1/** to reach the setup interface while connected to WICID-Setup.

- **Use HTTP, not HTTPS**: Always use HTTP URLs for setup access.

- **Troubleshooting**:
  - Navigate directly to http://192.168.4.1/
  - Ensure you type "http://192.168.4.1/" exactly (include http:// and trailing slash)
  - Desktop browsers may default to search or HTTPS if you don't include the full URL

- **Saving settings**: If you see a read‑only filesystem error while saving, unplug USB or eject the CIRCUITPY drive and try again.

## Error Handling

The device includes robust error handling and will:
- Automatically enter setup mode if it cannot connect to the configured Wi-Fi network
- Attempt to reconnect to the last known good network
- Enter setup mode if no valid network configuration is found
- Handle API request failures gracefully
- Recover from invalid data responses

## Developer Setup

### Prerequisites
- CircuitPython installed on your device
- `circup` for managing CircuitPython libraries
- (Optional) Mu Editor for code editing and serial console

### Filesystem Modes

The device uses `boot.py` to control filesystem access. By default, it runs in **Production Mode** which allows the setup portal to save configuration files but disables USB mass storage.

**Production Mode** (default):
- Filesystem is writable from code (setup portal can save credentials)
- USB mass storage is disabled
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
   - The device will automatically reboot into Safe Mode
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

### Manual Configuration
For development purposes, you can manually configure settings by editing `secrets.py`:

```python
secrets = {
    'ssid': 'your_wifi_ssid',
    'password': 'your_wifi_password',
    'weather_zip': '12345',  # ZIP code for weather location
    'update_interval': 1200  # Update interval in seconds (20 minutes)
}
```

### Code Structure
- `code.py`: Main application loop and mode switching
- `boot.py`: Controls filesystem access modes (production vs development)
- `modes.py`: LED behavior and display modes
- `weather.py`: Weather data fetching and processing
- `setup_portal.py`: Handles the web-based setup interface
- `secrets.py`: Configuration (sensitive data)
- `www/`: Web interface files for the setup portal
- `requirements.txt`: Python dependencies for development

### Building and Flashing
1. Install required dependencies:
   ```bash
   pip install circup
   circup install
   ```

2. Copy all files to your device's CIRCUITPY drive
3. The device will automatically restart and run the new code

### Dependencies

- CircuitPython
- Adafruit CircuitPython libraries
- Open-Meteo API (or compatible weather service)

## License

© 2025 WICID. All rights reserved.

This software and its documentation are proprietary and confidential. Unauthorized copying, distribution, modification, public display, or public performance of this software is strictly prohibited.

No part of this software may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of WICID, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.

For permission requests, please contact the copyright holder.