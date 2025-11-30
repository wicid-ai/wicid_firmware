# WICID Architecture

This document describes the architectural principles and patterns that guide the WICID firmware design.

## Design Philosophy

The WICID architecture follows these core principles:

- **Encapsulation**: Related functionality is grouped within manager classes that own their domain
- **Separation of Concerns**: Each component has a clear, well-defined responsibility
- **DRY (Don't Repeat Yourself)**: Common patterns are abstracted and reused
- **Error Resilience**: Recoverable errors are handled internally; only fatal errors propagate up
- **Singleton Pattern**: Shared resources (WiFi, LED, Configuration) use singletons for consistent state management

## System Patterns

> **Note**: For concrete code examples of these patterns, see the [Patterns Cookbook](PATTERNS_COOKBOOK.md).

### Manager-Based Architecture

The system is organized around specialized managers that encapsulate domain logic:

- **Configuration manager**: Handles the complete configuration lifecycle, including setup portal and credential validation
- **Connectivity manager**: Centralizes all network operations (station mode, access point, retry logic)
- **Mode manager**: Orchestrates user-selectable operating modes with consistent lifecycle management
- **Update manager**: Handles firmware updates with verification and installation
- **Weather manager**: Schedules and caches weather data fetched from the weather service API client
- **Input manager**: Manages button input events using a dedicated button controller
- **System manager**: Performs periodic health checks and maintenance operations

Each manager owns its domain and makes best-effort recovery from errors. Only unrecoverable failures propagate upward.

### Naming Conventions

To keep responsibilities predictable and discoverable, components follow these naming conventions:

- **`*Manager`**: Orchestrates a domain, lifecycle, or workflow and may coordinate multiple collaborators.
  - Examples: `FooManager`, `ConfigManager`.
- **`*Controller`**: Encapsulates direct interaction with a specific hardware component and exposes intent-level operations.
  - Examples: `DeviceController`, `LedController`.
- **`*Service`**: Encapsulates access to an external or logical service (typically network-backed or domain-specific).
  - Examples: `ExampleService`, `ExternalApiService`.

Modules are generally named to match the primary class they expose (for example, `ExampleManager` would live in `example_manager.py`), which keeps module and class names aligned over time.

Utility/helper functionality is kept in dedicated utility modules rather than helper classes whenever possible.

### Main Orchestrator

A lightweight orchestrator coordinates system initialization and delegates to managers. It handles fatal exceptions and triggers system recovery when necessary.

### Mode System

User-selectable modes follow a consistent interface pattern:
- Modes declare their requirements (e.g., WiFi connectivity)
- Modes implement lifecycle hooks (initialize, run, cleanup)
- One primary mode serves as the default
- Secondary modes are ordered and cycled through by user interaction

The mode system is extensible—new modes can be added by implementing the mode interface and registering them.

### Shared Resources

Critical shared resources (WiFi, LED, Logging) use the singleton pattern to ensure consistent state management across the system.

#### Manager Lifecycle Pattern

All managers inherit from `ManagerBase` which provides a consistent lifecycle pattern:

- **Singleton Access**: Managers are accessed via `instance()` class methods
- **Encapsulated Resource Management**: All resource allocation (pins, tasks, sessions) happens in `_init()` method
- **Automatic Cleanup**: All resource cleanup happens in `shutdown()` method
- **Smart Reinitialization**: When dependencies change (e.g., in tests), managers automatically shut down and reinitialize
- **Context Manager Support**: Managers can be used in `with` blocks for explicit lifetime management

**Key Principles:**
- Callers only ever call `instance(...)` - never manipulate `_instance` directly
- Resource cleanup is encapsulated inside each manager's `shutdown()` method
- Tests can inject dependencies (pins, sessions, fake radios) via `instance(deps...)` without special test APIs
- All managers follow the same lifecycle pattern, even if they don't own external resources (use no-op `shutdown()`)

**Example:**
```python
# Production code - simple singleton access
input_mgr = InputManager.instance()

# Test code - inject test dependencies (auto-reinitializes if needed)
test_pin = DigitalInOut(board.BUTTON)
input_mgr = InputManager.instance(button_pin=test_pin)

# Context manager (optional, for explicit lifetime)
with InputManager.instance() as mgr:
    # Use manager
    pass
# Manager is automatically shut down here
```

**Benefits:**
- Tests don't need special `reset_for_test()` APIs or manual `_instance` manipulation
- Resource ownership is clear - each manager owns its resources and cleans them up
- Safe reinitialization when dependencies change (common in tests)
- Consistent pattern across all managers makes the codebase easier to understand

## Error Handling Strategy

## Module Boundaries and Dependencies

To maintain encapsulation and a clear, predictable structure, the firmware enforces strict rules about how components can interact.

### Dependency Direction

The dependency flow is one-way. Higher-level components can depend on lower-level ones, but not the other way around.

- **Managers** can depend on Services and Controllers.
- **Services** can depend on Controllers.
- **Controllers** MUST NOT depend on Managers or Services. They are self-contained hardware abstractions.

### `asyncio` Isolation

The `Scheduler` is the sole owner of the `asyncio` event loop.

- **Only `scheduler.py`** is permitted to import and use `asyncio` primitives directly (e.g., `asyncio.create_task`, `asyncio.sleep`).
- All other modules **MUST** use the `Scheduler` facade for any asynchronous work (e.g., `await Scheduler.sleep(0.1)`). This is a critical architectural constraint enforced during code review.

### Public vs. Private APIs

For general rules on how to respect module boundaries in code (e.g., handling of `_private` members), see the Public vs. Private APIs section in the Style Guide.


### Error Classification

**Recoverable Errors**: Handled internally by managers, return status codes for callers to handle appropriately. Examples include network unavailability, bad credentials, API errors.

**Unrecoverable Errors**: Raise exceptions that propagate to the orchestrator, triggering system reboot. Examples include hardware failure, filesystem corruption, missing critical files.

### Manager Responsibility

Each manager makes best effort to gracefully recover from all errors. Recoverable errors never propagate beyond the manager handling them. Only when recovery is impossible and the condition is fatal should an exception be raised.

## System Recovery

### Reboot vs Restart

- **Reboot**: Hard reset (runs bootloader). Used for firmware updates and unrecoverable errors.
- **Restart**: Soft reset (skips bootloader). Used for configuration changes and recoverable failures.

### Recovery Triggers

- Configuration changes and user-initiated actions trigger restarts
- Firmware updates and unrecoverable errors trigger reboots
- Periodic maintenance may trigger reboots for system stability

## OTA Update Architecture

### Atomic Staging

OTA updates use a two-phase staging approach to prevent partial installations:

1. **Download Phase**: Update ZIP is downloaded to `/pending_update/update.zip`
2. **Staging Phase**: Files are extracted to `/pending_update/.staging/`
3. **Verification Phase**: Critical files are validated against `RecoveryManager.CRITICAL_FILES`
4. **Atomic Rename**: `.staging/` is renamed to `root/` only after verification passes
5. **Ready Marker**: A `.ready` file is written containing the manifest hash

Boot.py only processes updates when both `/pending_update/root/` exists AND the `.ready` marker is valid. This ensures incomplete downloads or extractions are never installed.

### Failure Cleanup

On any failure during download, verification, or extraction:
- The entire `/pending_update/` directory is removed
- The failed version is recorded in `incompatible_releases.json`
- The device continues running the current firmware

### Preserved Files

The following files are NEVER overwritten during OTA updates:
- `secrets.json` - WiFi credentials and API keys (user-provided)
- `DEVELOPMENT` - Development mode flag (user-set)

Other files like `settings.toml`, `wifi_retry_state.json`, and `incompatible_releases.json` are intentionally replaced during updates as new firmware versions may include schema changes that invalidate previous versions.

### Recovery Backup

After successful installation, critical boot files are backed up to `/recovery/`. If boot detects missing critical files, it automatically restores from this backup and marks the failed version as incompatible.

## Configuration Lifecycle

1. System checks for valid configuration on boot
2. Missing or invalid configuration triggers setup portal
3. User configures WiFi and settings via web interface
4. Credentials are validated before committing
5. Successful configuration enables normal operation
6. Failed validation allows user to retry without system restart

## Logging Strategy

Structured logging with hierarchical loggers organized by component. Log levels are configurable and follow standard conventions:
- `DEBUG`: Detailed diagnostics
- `INFO`: Normal operations
- `WARNING`: Recoverable issues
- `ERROR`: Errors handled internally
- `CRITICAL`: Unrecoverable errors (about to raise exception)

## Extensibility

The architecture supports extension through:
- **New Modes**: Implement the mode interface and register
- **New Services**: Modes can initialize their own services
- **New Features**: Managers can be extended without affecting callers
- **Configuration Options**: Add fields to configuration storage and update portal UI

---

This architecture provides a clean separation of concerns, making the system easier to understand, maintain, and extend.
