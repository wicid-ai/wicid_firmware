"""
WICID Boot Configuration

CircuitPython requires "boot.py" to be a non-compiled (source) Python file.
This file cannot be replaced by a compiled .mpy file.

All boot logic is in boot_support.py (compiled to bytecode for efficiency).
"""

import boot_support
boot_support.main()
