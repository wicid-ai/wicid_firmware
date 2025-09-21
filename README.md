# WICID Weather Indicator

## Overview
WICID (Weather Indicator and Climate Information Device) is an intelligent weather indicator that provides at-a-glance weather information through colored LED feedback. The device is designed to be simple, intuitive, and visually appealing, providing weather updates without requiring a screen.

## Features

- **Temperature Display**: Shows current temperature through LED color gradients
- **Precipitation Alerts**: Visual precipitation probability indication through blinking patterns
- **Multiple Modes**: Includes both live weather and demonstration modes
- **WiFi Connectivity**: Fetches real-time weather data using WiFi
- **Button Control**: Simple button interface to cycle through different modes

## How It Works

### Hardware Components
- Microcontroller with WiFi capability (e.g., Adafruit Feather)
- NeoPixel LED
- Tactile button
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

### Weather Data

The device fetches weather data including:
- Current temperature
- Daily high temperature
- Precipitation probability

### Visual Feedback

- **Temperature**: Displayed through LED color (blue for cold, green for moderate, red for hot)
- **Precipitation**: Indicated through blinking patterns (number of blinks corresponds to precipitation probability)

## Setup

1. Configure `secrets.py` with:
   - WiFi credentials
   - Weather API settings
   - Location information (ZIP code)
   - Timezone

2. Install required CircuitPython libraries:
   - `adafruit_requests`
   - `neopixel`
   - Other board-specific libraries

3. Upload the code to your device

## Usage

1. Power on the device
2. The device will connect to WiFi and fetch weather data
3. The LED will display the current weather information
4. Press the button to cycle through different display modes
5. In demo modes, the LED will cycle through different temperature and precipitation patterns

## Error Handling

The device includes basic error handling and will attempt to recover from:
- WiFi connection issues
- API request failures
- Invalid data responses

## Configuration

Customize the behavior by modifying:
- `secrets.py` for network and location settings
- `code.py` for update intervals and mode selection
- `modes.py` for LED behavior and color schemes

## Dependencies

- CircuitPython
- Adafruit CircuitPython libraries
- Open-Meteo API (or compatible weather service)

## License

© 2025 WICID. All rights reserved.

This software and its documentation are proprietary and confidential. Unauthorized copying, distribution, modification, public display, or public performance of this software is strictly prohibited.

No part of this software may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of WICID, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.

For permission requests, please contact the copyright holder.

## Contributing

This is a proprietary project. External contributions are not currently being accepted.
