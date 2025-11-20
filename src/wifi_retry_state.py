"""
WiFi Retry State - Persistent retry counter across reboots.

Manages a simple JSON file that tracks how many boot cycles have attempted
WiFi connection without success. Used to implement smart retry logic with
eventual fallback to indefinite Setup Mode.
"""

import json
from logging_helper import logger

STATE_FILE = "/wifi_retry_state.json"


def load_retry_count():
    """
    Load the retry count from persistent storage.
    
    Returns:
        int: Current retry count (0 if file doesn't exist or is corrupt)
    """
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return int(data.get("retry_count", 0))
    except (OSError, ValueError, KeyError):
        # File doesn't exist, is corrupt, or has wrong format
        return 0


def increment_retry_count():
    """
    Increment the retry count and save to persistent storage.
    
    Returns:
        int: New retry count value
    """
    current = load_retry_count()
    new_count = current + 1
    _save_retry_count(new_count)
    return new_count


def clear_retry_count():
    """
    Clear the retry count (set to 0) and save to persistent storage.
    """
    _save_retry_count(0)


def _save_retry_count(count):
    """
    Save retry count to persistent storage.
    
    Args:
        count: Integer retry count to save
    """
    try:
        data = {"retry_count": count}
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except OSError as e:
        log = logger('wicid.wifi_retry')
        log.warning(f"Failed to save retry state: {e}")
