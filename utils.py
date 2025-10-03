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
            
            # At 3 seconds, start pulsing white for Setup Mode indicator (same as setup mode)
            if elapsed >= 3.0 and not setup_indicated and pixel_controller:
                setup_indicated = True
                print("3 second threshold reached - pulsing Setup Mode indicator")
                # Use the same pulsing pattern as setup mode
                pixel_controller.start_pulsing(
                    color=(255, 255, 255),
                    min_b=0.1,
                    max_b=0.7,
                    step=0.03,
                    interval=0.04,
                    start_brightness=0.4,
                )
            
            # At 10 seconds, start flashing blue/green for Safe Mode indicator
            if elapsed >= 10.0 and not safe_mode_indicated and pixel_controller:
                safe_mode_indicated = True
                print("10 second threshold reached - flashing Safe Mode indicator")
                # Stop pulsing and switch to flashing
                pixel_controller.stop_pulsing()
            
            if pixel_controller:
                if safe_mode_indicated:
                    # Flash blue and green alternately (4 times per second)
                    cycle = int((time.monotonic() - start_time) * 4) % 2
                    if cycle == 0:
                        pixel_controller.set_color((0, 0, 255))  # Blue
                    else:
                        pixel_controller.set_color((0, 255, 0))  # Green
                elif setup_indicated:
                    # Tick the pulsing animation
                    pixel_controller.tick()
            
            time.sleep(0.05)
        
        # Button released - clean up LED state
        if pixel_controller:
            if setup_indicated:
                pixel_controller.stop_pulsing()
            if setup_indicated or safe_mode_indicated:
                pixel_controller.set_color((0, 0, 0))
        
        # Determine which mode based on hold duration
        final_duration = time.monotonic() - start_time
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
    import microcontroller
    print("Triggering Safe Mode for development access...")
    print("Device will reboot with USB enabled")
    microcontroller.on_next_reset(microcontroller.RunMode.SAFE_MODE)
    microcontroller.reset()
