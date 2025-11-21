"""
WiFiRadioController - Hardware abstraction for the WiFi radio.

This controller wraps the underlying `wifi.radio` object so higher-level
components (e.g., connection managers) can interact with WiFi hardware
via a testable, injectable dependency.
"""

import wifi  # type: ignore[import-untyped]  # CircuitPython-only module


class WiFiRadioController:
    """
    Thin wrapper around the global `wifi.radio` instance.

    Higher-level code should depend on this controller rather than using
    `wifi.radio` directly. In tests, a fake or stub implementation with a
    compatible API can be injected.
    """

    def __init__(self, radio=None):
        """
        Args:
            radio: Optional radio-like object for dependency injection.
                   Defaults to the global `wifi.radio`.
        """
        self._radio = radio or wifi.radio

    @property
    def radio(self):
        """Underlying radio object (typically `wifi.radio`)."""
        return self._radio
