# WICID User Guide

Complete setup and usage instructions for the WICID Weather Indicator.

## Initial Setup

1. **Enter Setup Mode**:
   - On first boot (or after a factory reset), the device will automatically enter Access Point (AP) mode
   - The LED will pulse white to indicate setup mode is active
   - Alternatively, manually enter setup mode by pressing and holding the mode button for 3+ seconds until the LED begins pulsing white

2. **Connect to WICID**:
   - Using a smartphone or computer, connect to the "WICID-Setup" Wi-Fi network
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

   *Note*: If saving fails with a read-only filesystem error, the device is likely connected over USB. Unplug the USB cable or eject the CIRCUITPY drive before saving, then try again.

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
   - On successful setup, LED will flash green 3 times before rebooting

## Visual Feedback

- **Temperature**: Displayed through LED color (blue for cold, green for moderate, red for hot)
- **Precipitation**: Indicated through blinking patterns (number of blinks corresponds to precipitation probability)

## Setup Portal Troubleshooting

### Captive Portal

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

**Saving settings**: If you see a read-only filesystem error while saving, try plugging the WICID into a power-only USB cable (when connected to a computer with a data-enabled USB cable, the WICID may behave like a thumbdrive and prevent config updates through the setup interface)

## Error Handling

The device includes robust error handling and will:
- Automatically enter setup mode if it cannot connect to the configured Wi-Fi network
- Attempt to reconnect to the last known good network
- Enter setup mode if no valid network configuration is found
- Handle API request failures gracefully
- Recover from invalid data responses

For detailed error handling strategy, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Over-the-Air (OTA) Updates

WICID devices support automatic firmware updates with a full-reset strategy for guaranteed consistency. The system:
- Checks for updates on boot and at configured intervals
- Self-identifies hardware type and OS version at runtime
- Downloads and verifies update packages with checksum validation
- Performs full-reset installations (preserves user data)
- Supports production and development release channels

For complete OTA update documentation, including architecture, configuration, and troubleshooting, see [BUILD_PROCESS.md](BUILD_PROCESS.md).
