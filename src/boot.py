"""
WICID Boot Configuration

CircuitPython requires "boot.py" to be a non-compiled (source) Python file.
This file cannot be replaced by a compiled .mpy file.

All boot logic is in boot_support.py (compiled to bytecode for efficiency).
"""

# CRITICAL: Configure USB serial console FIRST, before anything that could fail
# This ensures serial debugging is available even if boot_support.py is corrupted
import usb_cdc  # pyright: ignore[reportMissingImports]  # CircuitPython-only module

usb_cdc.enable(console=True, data=False)

# Now proceed with main boot logic
import core.boot_support as boot_support  # noqa: E402

boot_support.main()
