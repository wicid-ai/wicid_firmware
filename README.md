<div align="center">

# WICID

**Weather in a flash. Super simple weather forecasts for a complicated world.**

[![CI](https://github.com/wicid-ai/wicid_firmware/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/wicid-ai/wicid_firmware/actions/workflows/ci.yml)
[![code style: ruff](https://img.shields.io/badge/code_style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![CircuitPython](https://img.shields.io/badge/CircuitPython-10.x-blueviolet.svg)](https://circuitpython.org/)
[![Python](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)

A minimalist, connected weather display that keeps you informed at a glance — no screens, no apps, no noise. Just a single LED that communicates local weather using color and blink patterns.

[Features](#features) • [Quick Start](#quick-start) • [Developer Setup](#developer-setup) • [Documentation](#documentation)

</div>

---

## Why WICID?

**Less noise, more clarity.**

WICID (Weather Information Center Internet-of-things Device) gives you real-world, local weather at a glance, without making you scroll through an app, listen to an AI voice assistant, or get distracted by yet another screen.

- **Simplicity first** — Dead simple 3-step setup: plug in, scan QR code, let it shine
- **Quick clarity** — One look and you know if it's cold, wet, or WICID nice out
- **Low attention required** — Check it when you need it, ignore it the rest of the time

The color of the LED shows the current temperature (blue for cold, green for pleasant, red for hot), while blink patterns indicate the chance of precipitation in the next few hours.

See the product website at: [https://www.wicid.ai](https://www.wicid.ai)

---

## Features

- **Temperature Display** — Current temperature through LED color gradients
- **Precipitation Alerts** — Precipitation probability indicated through blink patterns
- **Multiple Modes** — Live weather and demonstration modes
- **WiFi Connected** — Real-time weather data with auto-reconnect
- **Setup Portal** — Easy Wi-Fi configuration through a captive portal web interface
- **Button Control** — Simple button interface to cycle modes and access setup
- **Over-the-Air Updates** — Automatic firmware updates with checksum verification
- **Privacy-First** — No microphones, cameras, or personal tracking

### Hardware

Built on the **Adafruit Feather ESP32-S3** — a powerful yet efficient microcontroller with built-in Wi-Fi, USB-C power, and a programmable RGB LED.

---

## Quick Start

1. **Plug in** — Connect WICID to a USB-C power source
2. **Connect** — Join the "WICID-Setup" Wi-Fi network from your phone or computer
3. **Configure** — Enter your Wi-Fi credentials and ZIP code in the setup portal
4. **Done** — WICID connects and starts displaying weather automatically

For detailed setup instructions, captive portal troubleshooting, and usage details, see the [User Guide](docs/USER_GUIDE.md).

---

## Developer Setup

```bash
pip install --user pipenv
pipenv install --dev
pipenv sync --dev
pipenv run pre-commit install
```

Run all quality checks (formatting, linting, type checking, unit tests):

```bash
pipenv run pre-commit run --all-files
```

For filesystem modes, configuration files, board setup, and CircuitPython library management, see the [Developer Setup Guide](docs/DEVELOPER_SETUP.md).

---

## Documentation

| Guide | Description |
|-------|-------------|
| [User Guide](docs/USER_GUIDE.md) | Device setup, usage, and troubleshooting |
| [Developer Setup](docs/DEVELOPER_SETUP.md) | Development environment and workflow |
| [Architecture](docs/ARCHITECTURE.md) | System design, manager patterns, error handling |
| [Patterns Cookbook](docs/PATTERNS_COOKBOOK.md) | Concrete code examples and patterns |
| [Style Guide](docs/STYLE_GUIDE.md) | Coding conventions and standards |
| [Scheduler Architecture](docs/SCHEDULER_ARCHITECTURE.md) | Cooperative scheduler design |
| [Code Review Guidelines](docs/CODE_REVIEW_GUIDELINES.md) | Review checklist and standards |
| [Build Process](docs/BUILD_PROCESS.md) | Release process, OTA updates, deployment |
| [Testing](tests/README.md) | Testing strategy, TDD workflow, best practices |

---

## Contributing

WICID is open source — fork it and have fun. Pull requests are not actively reviewed. Bug reports are welcome via issues.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

## About

Built by [**WICID**](https://www.wicid.ai) — Simple, smart weather forecasting.
