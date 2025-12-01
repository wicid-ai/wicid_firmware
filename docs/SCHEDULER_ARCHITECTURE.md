# Scheduler Architecture for WICID System

## 1. Purpose
The scheduler provides a single cooperative multitasking layer for the firmware. It abstracts the platform's asyncio loop and exposes an intent-focused API for managers and services that need periodic or on-demand work. This document captures the guiding concepts so the firmware stays understandable even as implementation details evolve.

## 2. Role in the Firmware
- Presents one facade (`Scheduler`) that wraps asyncio and shields the rest of the code from event-loop mechanics.
- Coordinates periodic work (LED refresh, connectivity checks, telemetry) and deferred operations (OTA updates, cleanup tasks).
- Encourages modular managers: each manager requests the cadence it needs and leaves fairness, timing, and instrumentation to the scheduler.

## 3. Guiding Principles
1. **Cooperative work model** – Every long-running operation is structured as an async coroutine that yields regularly. Pre-emption is intentionally avoided to keep behavior predictable on constrained hardware.
2. **Priority-aware fairness** – Tasks declare an intent-driven priority (critical UI, connectivity, maintenance, background) and the scheduler enforces ordering plus starvation prevention without exposing heap or queue details to callers.
3. **Scheduler as source of truth** – There is no parallel `tick()` convention. Managers either register periodic tasks during startup or schedule one-off work when needed.
4. **Isolation of asyncio** – Only the scheduler interacts with asyncio primitives. This keeps business logic simple, allows easier unit testing, and enables future experimentation with alternative backends.
5. **Observability-first** – Tasks are tracked with lightweight statistics (execution counts, cumulative runtime, overruns) so we can reason about device health without instrumenting every coroutine.

## 4. Conceptual Model

### 4.1 Tasks
- A *task* represents intent: "run this coroutine every few milliseconds", "run once after connection", or "run again after it finishes".
- Each registration provides a human-readable name, an async callable, an interval/delay policy, and an optional priority hint.
- Periodic tasks target fixed cadences (good for LED animation or button sampling). Recurring tasks reschedule after completion (useful for operations whose duration may vary). One-shot tasks execute once and then retire themselves.

### 4.2 Scheduler Lifecycle
1. **Registration** – Managers call helper methods such as `schedule_periodic` or `schedule_recurring`. No direct event-loop usage is allowed outside the scheduler.
2. **Dispatch** – The scheduler continually evaluates ready tasks, orders them by their intent (priority and due time), and runs them by awaiting their coroutine.
3. **Cooperation** – Tasks use `Scheduler.sleep()` or `Scheduler.yield_control()` inside long loops so that other work can make progress. The scheduler never forcefully interrupts a coroutine.
4. **Rescheduling** – Once a task completes, the scheduler updates the next-run timestamp using the policy associated with that task type and re-queues it automatically (unless it was one-shot or cancelled).
5. **Cancellation and teardown** – Callers hold `TaskHandle` objects that let them cancel future runs if a feature is disabled or a manager shuts down.

### 4.3 Priorities and Fairness
- Priorities are qualitative buckets (critical UI, connectivity, user experience, maintenance, background). The actual numbers in code are implementation details; the important part is consistent ordering in line with user impact.
- Starvation prevention periodically boosts long-waiting work so maintenance jobs eventually run even if high-priority workloads are busy.
- The scheduler tracks ready vs. blocked time so overruns and head-of-line blocking can be logged and debugged without each manager duplicating that logic.

### 4.4 System Integration
- **Managers** (system, update, mode, configuration, etc.) register the work they own. For example, the System Manager registers the reboot watchdog and update-check cadence, while LED control registers a high-priority periodic task.
- **Shared Resources** (logging, HTTP client, hardware abstractions) rely on the scheduler's cooperative nature to avoid blocking each other. They never call `asyncio.sleep()` directly; instead they import the scheduler facade.
- **Boot process** – The main orchestrator initializes managers, registers their tasks, and then transfers control to `Scheduler.run_forever()`. After that, no code should spin its own loop.

### 4.5 Extensibility
- Wall-clock scheduling, resource budgeting, or additional event sources can be layered on by adding new task types or helper APIs without rewriting existing managers.
- Because asyncio usage is isolated, the firmware could transition to another event-loop implementation or a future RTOS-friendly layer with minimal surface area changes.
- Diagnostics (`describe()` / `dump_state()`) expose conceptual information (queued tasks, execution counts). Custom tooling can build on that without depending on private attributes.

## 5. Working With the Scheduler

### 5.1 Writing Tasks
- Keep coroutine bodies short and composable. Delegate blocking work (network fetches, file access) to helper coroutines that include their own cooperative yields.
- Prefer explicit sleeps (`await Scheduler.sleep(x)`) over busy loops. The scheduler treats short sleeps as hints about desired cadence rather than absolute guarantees.
- Throw `TaskNonFatalError` for recoverable failures; the scheduler will log the incident and reschedule according to the task's policy. Reserve fatal errors for cases where the device should restart.

### 5.2 Choosing Priorities
- Critical UI responsiveness (button sampling, LED updates) should use the highest priority tier.
- Connectivity, mode transitions, and Wi-Fi work stay in the next tier down.
- Maintenance and telemetry work use background tiers so they never disrupt user-visible behavior.
- Treat the numeric values in code as implementation detail; when adding new tasks, focus on which user experience they influence and select the matching priority bucket.

### 5.3 Observability
- Use `Scheduler.describe()` in the REPL to understand what tasks are queued, how soon they will run, and whether any are starved.
- Long-running managers can log their task handles or names at startup so troubleshooting can map scheduler state back to features.
- The scheduler's counters (total scheduled/executed/failed) help detect runaway retries or systemic errors.

## 6. Future Opportunities
- **Wall-clock jobs** – Wrap cron-style tasks (e.g., daily restarts, scheduled OTA windows) so they look identical to periodic work.
- **Event-driven hooks** – Integrate button/input libraries or message queues by translating signal callbacks into scheduler tasks.
- **Dynamic prioritization** – Allow tasks to self-tune their priority tiers based on context (e.g., boost telemetry when diagnosing issues).
- **Deeper metrics** – Emit aggregate runtime statistics that can be collected by the logging subsystem for remote diagnostics.

---

This document purposefully focuses on *intent*. Code-level mechanics (heap structures, concrete constants, asyncio wiring) live in `src/scheduler.py`. When changing the scheduler, keep this document aligned with the overall goals—describe why the scheduler behaves the way it does, not just how the code happens to be written today.
