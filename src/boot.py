"""
WICID Boot Configuration

CircuitPython requires "boot.py" to be a non-compiled (source) Python file.
This file cannot be replaced by a compiled .mpy file.

All boot logic is in boot_support.py (compiled to bytecode for efficiency).
"""

# CRITICAL: Configure USB serial console FIRST, before anything that could fail
# This ensures serial debugging is available even if boot_support.py is corrupted
import usb_cdc  # type: ignore[import-untyped]  # CircuitPython-only module

import boot_support

usb_cdc.enable(console=True, data=False)

# Now proceed with main boot logic
boot_support.main()
