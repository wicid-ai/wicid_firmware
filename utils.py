"""
Utility functions shared across the WICID firmware.

This module contains common utility functions used throughout the codebase,
including button handling, configuration validation, and other shared logic.
"""

import time


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


def check_secrets_complete():
    """
    Check if secrets.py exists and contains all required configuration values.
    
    Returns:
        tuple: (is_complete: bool, missing_keys: list)
    """
    required_keys = ['ssid', 'password', 'weather_zip']
    
    try:
        import secrets
        
        # Check if secrets module has the 'secrets' dictionary
        if not hasattr(secrets, 'secrets'):
            return False, required_keys
        
        config = secrets.secrets
        
        # Validate all required keys exist and have non-empty values
        return validate_config_values(config, required_keys)
        
    except (ImportError, AttributeError):
        return False, required_keys


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
