"""
WICID Boot Configuration

CircuitPython requires "boot.py" to be a non-compiled (source) Python file.
This file cannot be replaced by a compiled .mpy file.

All boot logic is in boot_support.py (compiled to bytecode for efficiency).

EMERGENCY RECOVERY:
This file includes inline emergency recovery for boot-critical files.
If boot_support.mpy or its dependencies are missing/corrupted, the normal
recovery mechanism in boot_support.py cannot run (because boot_support.py
itself fails to import). This inline recovery uses ONLY the built-in 'os'
module to restore these files from /recovery/ before attempting the import.
"""

import os

# BOOT_CRITICAL: Minimum files needed to reach RecoveryManager.
# These files allow boot_support.py to import and load RecoveryManager,
# which can then restore the full set of CRITICAL_FILES.
# Dependency chain: boot.py → boot_support → {app_typing, logging_helper, utils} → recovery_manager
_BOOT_CRITICAL = [
    "/core/boot_support.mpy",
    "/core/app_typing.mpy",
    "/core/logging_helper.mpy",
    "/utils/utils.mpy",
    "/managers/recovery_manager.mpy",
]

_RECOVERY_DIR = "/recovery"


def _emergency_recovery() -> None:
    """
    Emergency recovery using only built-in os module.

    Runs BEFORE any imports that could fail. If boot-critical files are missing,
    attempts to restore them from /recovery/. This is a last-resort mechanism
    to prevent complete device bricking.
    """
    for path in _BOOT_CRITICAL:
        try:
            os.stat(path)
        except OSError:
            # File missing - try to restore from recovery
            recovery_path = _RECOVERY_DIR + path
            try:
                # Read from recovery
                with open(recovery_path, "rb") as src:
                    content = src.read()

                # Create parent directory if needed
                # Note: Can't use contextlib.suppress here - boot.py uses minimal imports
                parent_dir = path.rsplit("/", 1)[0]
                if parent_dir:
                    try:  # noqa: SIM105
                        os.mkdir(parent_dir)
                    except OSError:
                        pass  # Directory exists

                # Write to target location
                with open(path, "wb") as dst:
                    dst.write(content)

                os.sync()
                print(f"EMERGENCY RECOVERY: Restored {path}")
            except OSError as e:
                print(f"EMERGENCY RECOVERY FAILED: {path} - {e}")
                print("Device may not boot. Enter Safe Mode and run installer.py")


# Run emergency recovery BEFORE any imports that could fail
_emergency_recovery()

# CRITICAL: Configure USB serial console, before anything else that could fail
# This ensures serial debugging is available even if boot_support.py is corrupted
import usb_cdc  # pyright: ignore[reportMissingImports]  # noqa: E402

usb_cdc.enable(console=True, data=False)

# Now proceed with main boot logic
import core.boot_support as boot_support  # noqa: E402

boot_support.main()
