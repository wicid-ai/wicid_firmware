"""
Utility functions shared across the WICID firmware.

This module contains common utility functions used throughout the codebase,
including button handling, configuration validation, and other shared logic.
"""

import os
import sys
import time
import board
import microcontroller
import json


def get_os_name():
    """
    Get the OS name.
    
    Returns:
        str: Operating system name
    """
    return sys.implementation.name

def get_os_version():
    """
    Get the OS version.
    
    Returns:
        tuple: OS version tuple (major, minor, micro, releaselevel, serial)
    """
    return sys.implementation.version


def get_board_id():
    """
    Get the board identifier.
    
    Returns:
        str: Board ID string
    """
    return board.board_id


def get_os_port_name():
    """
    Get the OS/Port name.
    
    Returns:
        str: Operating system port name
    """
    return os.uname().sysname


def get_machine_type():
    """
    Get the machine type.
    
    Returns:
        str: Machine type string
    """
    return os.uname().machine


def get_cpu_uid():
    """
    Get the CPU's unique identifier.
    
    Returns:
        str: Hexadecimal string representation of the CPU unique ID
    """
    chip_uid_binary = microcontroller.cpu.uid
    return ''.join('{:02x}'.format(b) for b in chip_uid_binary)


def get_mac_address():
    """
    Get the MAC address via WiFiManager.
    
    Returns:
        str: MAC address in colon-separated hex format, or None if Wi-Fi unavailable
    """
    try:
        # Lazy import to avoid circular dependency (wifi_manager imports from utils)
        from wifi_manager import WiFiManager
        wifi_manager = WiFiManager.get_instance()
        return wifi_manager.get_mac_address()
    except Exception:
        return None


def get_os_version_string():
    """
    Get the OS version in a standardized format for compatibility checks.
    
    Returns:
        str: OS version string in format 'os_major_minor' (e.g., 'circuitpython_10_1')
    """
    name = get_os_name()
    version = get_os_version()
    return f"{name}_{version[0]}_{version[1]}_{version[2]}"

def get_os_version_string_pretty_print():
    """
    Get the OS version in a pretty print format for display.
    
    Returns:
        str: OS version string in format 'OS major.minor.micro' (e.g., 'CircuitPython 10.1.4')
    """
    name = get_os_name()
    version = get_os_version()
    name_camel = (name[0].upper() + name[1:]) if name else ""
    return f"{name_camel} {version[0]}.{version[1]}.{version[2]}"


def os_matches_target(device_os_string, target_os_array):
    """
    Check if device OS matches any target OS in array using semantic versioning.
    
    A device OS is compatible if its major.minor version is >= the target major.minor.
    For example, circuitpython 10.1.4 matches target 'circuitpython_10_1' and
    'circuitpython_10_0', but not 'circuitpython_11_0'.
    
    Args:
        device_os_string: Device OS version string (e.g., 'circuitpython_10_1')
        target_os_array: Array of target OS strings (e.g., ['circuitpython_9_3', 'circuitpython_10_1'])
    
    Returns:
        bool: True if device OS matches any target OS
    """
    device_parts = device_os_string.split('_')
    device_name = device_parts[0]
    device_major = int(device_parts[1])
    device_minor = int(device_parts[2]) if len(device_parts) > 2 else 0
    
    for target_os_string in target_os_array:
        parts = target_os_string.split('_')
        target_name = parts[0]
        target_major = int(parts[1])
        target_minor = int(parts[2]) if len(parts) > 2 else 0
        
        if device_name == target_name:
            if device_major > target_major:
                return True
            if device_major == target_major and device_minor >= target_minor:
                return True
    
    return False


def compare_versions(version1, version2):
    """
    Compare two semantic version strings.
    
    Args:
        version1: First version string (e.g., '1.2.3' or '1.2.3-beta')
        version2: Second version string
    
    Returns:
        int: 1 if version1 > version2, -1 if version1 < version2, 0 if equal
    """
    def parse_version(version_str):
        # Split on '-' to separate prerelease
        if '-' in version_str:
            main_ver, prerelease = version_str.split('-', 1)
        else:
            main_ver = version_str
            prerelease = None
        
        # Parse main version numbers
        parts = main_ver.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        
        return (major, minor, patch, prerelease)
    
    v1_parsed = parse_version(version1)
    v2_parsed = parse_version(version2)
    
    # Compare major, minor, patch
    for i in range(3):
        if v1_parsed[i] > v2_parsed[i]:
            return 1
        elif v1_parsed[i] < v2_parsed[i]:
            return -1
    
    # If versions are equal, check prerelease
    # Release versions (no prerelease) are > prerelease versions
    if v1_parsed[3] is None and v2_parsed[3] is not None:
        return 1
    elif v1_parsed[3] is not None and v2_parsed[3] is None:
        return -1
    elif v1_parsed[3] is not None and v2_parsed[3] is not None:
        # Both have prerelease, compare as strings
        if v1_parsed[3] > v2_parsed[3]:
            return 1
        elif v1_parsed[3] < v2_parsed[3]:
            return -1
    
    return 0


def mark_incompatible_release(version, reason="Unknown"):
    """
    Mark a release version as incompatible to prevent retry loops.
    
    Args:
        version: Release version string to mark as incompatible
        reason: Why the release is incompatible
    """
    try:
        try:
            with open("/incompatible_releases.json", "r") as f:
                incompatible = json.load(f)
        except (OSError, ValueError):
            incompatible = {"releases": {}}
        
        # Migrate old format (list) to new format (dict)
        if "versions" in incompatible:
            old_versions = incompatible["versions"]
            incompatible = {"releases": {v: {"reason": "Unknown (migrated)", "attempts": 1} for v in old_versions}}
        
        # Initialize releases dict if needed
        if "releases" not in incompatible:
            incompatible["releases"] = {}
        
        # Increment attempt counter or create new entry
        if version in incompatible["releases"]:
            incompatible["releases"][version]["attempts"] += 1
            incompatible["releases"][version]["last_reason"] = reason
        else:
            incompatible["releases"][version] = {"reason": reason, "attempts": 1}
        
        # Keep only last 10 to prevent file growth
        if len(incompatible["releases"]) > 10:
            # Sort by attempts (keep ones with fewer attempts for retry opportunity)
            sorted_releases = sorted(incompatible["releases"].items(), key=lambda x: x[1]["attempts"], reverse=True)
            incompatible["releases"] = dict(sorted_releases[:10])
        
        with open("/incompatible_releases.json", "w") as f:
            json.dump(incompatible, f)
        os.sync()
        
        attempts = incompatible["releases"][version]["attempts"]
        print(f"Marked {version} as incompatible (attempt {attempts}): {reason}")
    except Exception as e:
        print(f"Warning: Could not mark incompatible release: {e}")


def is_release_incompatible(version, max_attempts=3):
    """
    Check if a release version is marked as incompatible.
    
    Args:
        version: Release version string to check
        max_attempts: Maximum retry attempts before permanent block (default: 3)
    
    Returns:
        tuple: (is_blocked: bool, reason: str or None, attempts: int)
               is_blocked is True only if attempts >= max_attempts
    """
    try:
        with open("/incompatible_releases.json", "r") as f:
            incompatible = json.load(f)
            
            # Support old format (list of versions) - treat as permanent block
            if "versions" in incompatible:
                if version in incompatible["versions"]:
                    return (True, "Unknown (old format)", max_attempts)
            
            # New format (dict with reasons and attempt counts)
            if "releases" in incompatible and version in incompatible["releases"]:
                info = incompatible["releases"][version]
                attempts = info.get("attempts", 1)
                reason = info.get("last_reason") or info.get("reason", "Unknown")
                is_blocked = attempts >= max_attempts
                return (is_blocked, reason, attempts)
                
        return (False, None, 0)
    except (OSError, ValueError):
        return (False, None, 0)


def check_release_compatibility(release_data, current_version):
    """
    DRY compatibility check used by both update_manager and boot.
    
    Checks:
    1. Machine type compatibility
    2. OS version compatibility (semantic versioning)
    3. Version is newer than current
    4. Not previously marked as incompatible (with retry support)
    
    Args:
        release_data: Dict with target_machine_types, target_operating_systems, version
        current_version: Current installed version string
    
    Returns:
        tuple: (is_compatible: bool, error_message: str or None)
    """
    device_machine = get_machine_type()
    device_os = get_os_version_string()
    
    # Check machine type
    if device_machine not in release_data.get("target_machine_types", []):
        return (False, f"Incompatible hardware: {device_machine} not in {release_data.get('target_machine_types', [])}")
    
    # Check OS compatibility
    if not os_matches_target(device_os, release_data.get("target_operating_systems", [])):
        return (False, f"Incompatible OS: {device_os} not compatible with {release_data.get('target_operating_systems', [])}")
    
    # Check version is newer
    if compare_versions(release_data["version"], current_version) <= 0:
        return (False, f"Version not newer: {release_data['version']} <= {current_version}")
    
    # Check if previously marked incompatible (with retry logic)
    is_blocked, reason, attempts = is_release_incompatible(release_data["version"])
    if is_blocked:
        return (False, f"Blocked after {attempts} attempts: {reason}")
    elif attempts > 0:
        print(f"Warning: Version had {attempts} failed attempts: {reason}")
        print("Retrying compatibility check...")
    
    return (True, None)


def get_system_info():
    """
    Get comprehensive system information.
    
    Returns:
        dict: Dictionary containing all system attributes
    """
    return {
        'os_version': get_os_version(),
        'os_version_string': get_os_version_string(),
        'board_id': get_board_id(),
        'os_name': get_os_name(),
        'machine_type': get_machine_type(),
        'cpu_uid': get_cpu_uid(),
        'mac_address': get_mac_address(),
    }


def wait_for_button_release(button, debounce_delay=0.1):
    """
    Wait for button to be released with optional debounce delay.
    
    Args:
        button: Button instance to monitor
        debounce_delay: Delay in seconds after release for debouncing (default: 0.1)
    """
    while not button.value:
        time.sleep(0.05)
    
    if debounce_delay > 0:
        time.sleep(debounce_delay)


def check_button_held(button, hold_duration=3.0):
    """
    Check if button is held for a specified duration.
    
    Args:
        button: Button instance to monitor
        hold_duration: Duration in seconds to consider as "held" (default: 3.0)
    
    Returns:
        bool: True if button was held for the duration, False otherwise
    """
    if not button.value:  # Button is pressed (active low)
        start_time = time.monotonic()
        while not button.value:
            if time.monotonic() - start_time >= hold_duration:
                return True
            time.sleep(0.1)
    return False


def is_button_pressed(button):
    """
    Check if button is currently pressed.
    
    Args:
        button: Button instance to check
    
    Returns:
        bool: True if button is pressed, False otherwise
    """
    # Button is active low (pressed = False)
    return not button.value


def validate_config_values(config_dict, required_keys):
    """
    Validate that all required configuration keys exist and have non-empty values.
    
    Args:
        config_dict: Dictionary containing configuration values
        required_keys: List of required key names
    
    Returns:
        tuple: (is_valid: bool, missing_keys: list)
    """
    missing_keys = []
    
    for key in required_keys:
        if key not in config_dict:
            missing_keys.append(key)
        elif not config_dict[key] or str(config_dict[key]).strip() == '':
            missing_keys.append(key)
    
    return len(missing_keys) == 0, missing_keys




def interruptible_sleep(duration, button=None, check_interval=0.05):
    """
    Sleep for the specified duration, optionally checking for button interrupts.
    
    Args:
        duration: Sleep duration in seconds
        button: Optional button instance to check for interrupts
        check_interval: How often to check button (default: 0.05 seconds)
    
    Returns:
        bool: True if sleep completed, False if interrupted by button press
    """
    if button is None:
        time.sleep(duration)
        return True
    
    elapsed = 0
    
    while elapsed < duration:
        if is_button_pressed(button):
            return False
        
        sleep_time = min(check_interval, duration - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time
    
    return True


def check_button_hold_duration(button, pixel_controller=None):
    """
    Check how long button is held and provide progressive visual feedback.
    
    Monitors the button from the moment it's pressed until released, detecting:
    - Short press (< 3 seconds) - no feedback
    - Setup mode (3-10 seconds) - pulsing white at 3s (same as setup mode)
    - Safe Mode (10+ seconds) - flashing blue/green at 10s
    
    Args:
        button: Button instance to monitor (must already be pressed when called)
        pixel_controller: Optional PixelController instance for visual feedback
    
    Returns:
        str: 'short', 'setup', or 'safe_mode' depending on hold duration
    """
    if not button.value:  # Button is pressed (active low)
        start_time = time.monotonic()
        setup_indicated = False
        safe_mode_indicated = False
        
        while not button.value:
            elapsed = time.monotonic() - start_time
            
            # At 3 seconds, start pulsing white for Setup Mode indicator
            if elapsed >= 3.0 and not setup_indicated and pixel_controller:
                setup_indicated = True
                print("3 second threshold reached - pulsing Setup Mode indicator")
                pixel_controller.indicate_setup_mode()
            
            # At 10 seconds, start flashing blue/green for Safe Mode indicator
            if elapsed >= 10.0 and not safe_mode_indicated and pixel_controller:
                safe_mode_indicated = True
                print("10 second threshold reached - flashing Safe Mode indicator")
                pixel_controller.indicate_safe_mode()
            
            # Keep animation running
            if pixel_controller:
                pixel_controller.tick()
            
            time.sleep(0.05)
        
        # Determine which mode based on hold duration
        final_duration = time.monotonic() - start_time
        
        # Button released - clean up LED state
        # Only clean up for short presses; leave LED active for mode entry
        if pixel_controller:
            if final_duration < 3.0:
                # Short press - turn off LED
                pixel_controller.clear()
            # For setup mode (3-10s) or safe mode (10+), leave LED state as-is
            # so the mode can continue with the visual indicator
        
        if final_duration >= 10.0:
            return 'safe_mode'
        elif final_duration >= 3.0:
            return 'setup'
        else:
            return 'short'
    
    return 'short'  # Button not pressed


def trigger_safe_mode():
    """
    Trigger Safe Mode on next reboot.
    This enables USB mass storage for development.
    """
    print("Triggering Safe Mode for development access...")
    print("Device will reboot with USB enabled")
    microcontroller.on_next_reset(microcontroller.RunMode.SAFE_MODE)
    microcontroller.reset()


# Cache for geocoding results to avoid redundant API calls
_location_cache = {}


def get_location_data_from_zip(session, zip_code):
    """
    Retrieve latitude, longitude, and timezone from ZIP code using Open-Meteo's geocoding API.
    
    Uses fallback behavior: tries full 5-digit ZIP, then 4 digits, then 3 digits.
    Results are cached per ZIP code to avoid redundant API calls during a session.
    
    Args:
        session: An active adafruit_requests.Session instance for making HTTP requests
        zip_code: The ZIP code to look up (should be 5 digits)
    
    Returns:
        tuple: (latitude, longitude, timezone) or (None, None, None) if all attempts fail
    """
    # Check cache first
    if zip_code in _location_cache:
        print(f"Using cached location data for ZIP: {zip_code}")
        return _location_cache[zip_code]
    
    zip_attempts = [
        zip_code,  # Full 5-digit ZIP
        zip_code[:4],  # First 4 digits
        zip_code[:3],  # First 3 digits
    ]
    
    for zip_attempt in zip_attempts:
        if not zip_attempt:  # Skip if truncated to empty string
            continue
            
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={zip_attempt}&count=1&language=en&format=json&countryCode=US"
        response = session.get(geocode_url)
        data = response.json()
        response.close()

        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            lat = result.get("latitude")
            lon = result.get("longitude")
            timezone = result.get("timezone")
            location_data = (lat, lon, timezone)
            
            # Cache the result
            _location_cache[zip_code] = location_data
            
            if zip_attempt != zip_code:
                print(f"Location found using {len(zip_attempt)}-digit prefix: {zip_attempt}")
            return location_data
    
    # Cache the failure result too to avoid repeated failed lookups
    print("No geocoding results found for ZIP code:", zip_code)
    _location_cache[zip_code] = (None, None, None)
    return None, None, None
