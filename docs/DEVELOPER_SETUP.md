# WICID Developer Setup

Complete development environment setup and workflow for contributing to the WICID firmware.

## Prerequisites

- Python version 3.13+
- `pipenv` for managing Python dependencies
- (Optional) Mu Editor for code editing and serial console

## Quick Start

1. **Install `pipenv`** (if not already installed):
   ```bash
   pip install --user pipenv
   ```

2. **Install Project Dependencies**:
   ```bash
   pipenv install --dev
   pipenv sync --dev
   ```

3. **Install Git Hooks**:
   ```bash
   pipenv run pre-commit install
   ```

Now, when you run `git commit`, your code will be automatically formatted, checked for errors, and unit tests will be executed.

## Filesystem Modes

The boot script controls filesystem access. By default, it runs in **Production Mode** which allows the setup portal to save configuration files but disables USB mass storage.

**Production Mode** (default):
- Filesystem is writable from code (setup portal can save credentials)
- USB mass storage is disabled
- USB serial console is enabled for monitoring and debugging

**Safe Mode** (for development):
- USB mass storage is enabled (CIRCUITPY drive appears on your computer)
- Filesystem is read-only from code
- Automatically triggered by holding mode button for 10 seconds (LED flashes blue/green)

### Entering Safe Mode

1. While the device is running, press and HOLD the mode button
2. At 3 seconds: LED pulses white (setup mode threshold)
3. At 10 seconds: LED changes to flashing blue/green (Safe Mode threshold)
4. Release the button when you see blue/green flashing
5. The device will automatically reboot into **Safe Mode**

### Return to Production Mode

Simply press RESET without holding any button.

### Force Safe Mode via Serial Console

If needed, you can also trigger Safe Mode from the REPL:
1. Connect to serial console (115200 baud) in Mu Editor or Terminal
2. Press RESET to get to the REPL prompt (`>>>`)
3. Paste this command:
   ```python
   import microcontroller; microcontroller.on_next_reset(microcontroller.RunMode.SAFE_MODE); microcontroller.reset()
   ```
4. The device will boot into Safe Mode with USB access enabled

## Configuration Files

WICID uses two configuration files:

- **`settings.toml`**: System-level settings deployed with firmware updates (version, update URLs, intervals). Read via `os.getenv()` in device code. Managed by build system.

- **`secrets.json`**: User-specific credentials (WiFi SSID/password, location), preserved across firmware updates. Created by Setup Mode.

## Testing

**Unit tests** can be run locally in your development environment. They are fully mocked and require no hardware:

```bash
python tests/run_tests.py
```

Unit tests are automatically executed as part of the pre-commit checks.

For complete testing documentation, including TDD workflow, integration tests, and best practices, see [`tests/README.md`](../tests/README.md).

## Code Quality

This project uses `ruff` for code formatting/linting and `mypy` for static type checking. These tools are enforced automatically using `pre-commit` git hooks.

Run all checks manually:

```bash
pipenv run pre-commit run --all-files
```

For detailed style guidelines, see [STYLE_GUIDE.md](STYLE_GUIDE.md). For code review guidelines, see [CODE_REVIEW_GUIDELINES.md](CODE_REVIEW_GUIDELINES.md).

## Building and Deployment

For information on building firmware releases, installing firmware manually, OTA update architecture, and the release process, see [BUILD_PROCESS.md](BUILD_PROCESS.md).

## Initial Board Setup

For new Adafruit Feather ESP32-S3 boards, you must initialize with CircuitPython before flashing the application. This process updates the bootloader and installs CircuitPython. See [BUILD_PROCESS.md](BUILD_PROCESS.md) for detailed instructions.

## Managing CircuitPython Libraries

The `/src/lib/` directory is maintained in source control to facilitate OTA updates. For instructions on adding or removing libraries, see [BUILD_PROCESS.md](BUILD_PROCESS.md).
