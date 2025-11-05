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

### Manager-Based Architecture

The system is organized around specialized managers that encapsulate domain logic:

- **Configuration Manager**: Handles the complete configuration lifecycle, including setup portal and credential validation
- **WiFi Manager**: Centralizes all WiFi operations (station mode, access point, retry logic)
- **Mode Manager**: Orchestrates user-selectable operating modes with consistent lifecycle management
- **Update Manager**: Handles firmware updates with verification and installation
- **System Monitor**: Performs periodic health checks and maintenance operations

Each manager owns its domain and makes best-effort recovery from errors. Only unrecoverable failures propagate upward.

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

## Error Handling Strategy

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
