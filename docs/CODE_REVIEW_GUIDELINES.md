# WICID Firmware Code Review Guidelines

## 1. Philosophy

Code reviews are a critical process for maintaining the quality, consistency, and long-term health of the WICID firmware. The goal of every review is to ensure that new code is not only correct but also aligns with our established architectural patterns and design principles.

Reviews should be constructive, collaborative, and educational. They are an opportunity to share knowledge and collectively improve the codebase.

---

## 2. Core Review Checklist

Before approving a pull request, please evaluate the changes against the following criteria. Reference the project's documentation as the primary source of truth.

### 2.1. Architectural Adherence

All code changes must align with the principles and patterns documented across the project's `README.md` files and design documents in the `/docs` directory.

- **[ ] Overall Architecture (`docs/ARCHITECTURE.md`)**:
  - Does the code adhere to the `Manager`, `Controller`, and `Service` naming conventions and roles?
  - Does it correctly use the `ManagerBase` singleton lifecycle pattern (`instance()`, `_init()`, `shutdown()`) for shared resources?
  - Is the error handling strategy consistent (recoverable errors handled locally, unrecoverable errors propagated)?

- **[ ] Scheduler Usage (`docs/SCHEDULER_ARCHITECTURE.md`)**:
  - Does all asynchronous work use the `Scheduler` facade instead of `asyncio` primitives directly?
  - Do long-running tasks yield control cooperatively via `Scheduler.sleep()` or `Scheduler.yield_control()`?
  - Are task priorities chosen correctly based on their user-facing impact (e.g., `CRITICAL_UI`, `BACKGROUND`)?

- **[ ] Testing Philosophy (`tests/README.md`)**:
  - Does the code follow the **layered testing hierarchy**?
  - **High-level components** (Managers, Modes): **MUST** use mocks for hardware dependencies.
  - **Low-level components** (Controllers): **MAY** use real hardware only when safe and contention-free, but mocks are preferred.
  - Are shared mocks from `test_helpers.py` used where applicable?

- **[ ] Project Overview (`README.md`)**:
  - Do changes align with the high-level features and user interaction flows described in the main project `README.md`?
  - Are developer-facing concepts, like filesystem modes (Production vs. Safe Mode), respected?

- **[ ] General Consistency**:
  - Does the code feel consistent with the surrounding codebase in terms of style, naming, and structure? It should look like it was written by the original author.

### 2.2. Code Quality and Best Practices

Is the code clean, efficient, and maintainable?

- **[ ] DRY (Don't Repeat Yourself)**: Is there duplicated code that could be refactored into a shared function, helper, or base class?

- **[ ] Readability**: Is the code clear, concise, and easy to understand? Favor simplicity over unnecessary complexity.

- **[ ] Static Analysis**: Is the code free of unused imports, variables, methods, or unreachable code paths (dead code)?

### 2.3. Comment Quality

Do comments add real value?

- **[ ] Explain the "Why", Not the "What"**: Comments should explain the intent, trade-offs, or complex logic behind a piece of code. They should **never** describe obvious implementation details.
  - **Bad**: `i += 1 # Increment counter`
  - **Good**: `# We must yield here to allow the network stack to process incoming packets.`

- **[ ] No Historical Comments**: Comments must not describe historical changes or previous states of the code. This information belongs in the `git` history, not in the source.
  - **Bad**: `# Timeout was increased from 5s to 10s to accommodate slower networks.`
  - **Good**: (No comment is needed; the code `TIMEOUT = 10` speaks for itself).

### 2.4. Error Handling

Does the code handle potential failures gracefully?

- **[ ] Resilience**: Does the code align with the error handling strategy in `ARCHITECTURE.md`?
  - **Recoverable errors** (e.g., network timeout) should be handled gracefully within the component.
  - **Unrecoverable errors** (e.g., filesystem corruption) should propagate up by raising an exception.

- **[ ] Resource Management**: Are resources like files, network sockets, and hardware pins always released correctly, even when errors occur? (e.g., using `try...finally` or context managers).

### 2.5. Scheduler and Asynchronous Code

If the code involves asynchronous operations, does it use the scheduler correctly?

- **[ ] Scheduler-Only**: Does the code use the `Scheduler` facade for all async operations, as defined in `SCHEDULER_ARCHITECTURE.md`? Direct calls to `asyncio` primitives (like `asyncio.create_task` or `asyncio.sleep`) are forbidden outside the scheduler itself.

- **[ ] Cooperation**: Do long-running tasks yield control appropriately using `await Scheduler.sleep()` or `await Scheduler.yield_control()` to prevent blocking other tasks?

- **[ ] Task Priority**: If a new task is scheduled, is its priority chosen correctly based on its impact on user experience (e.g., `CRITICAL_UI`, `CONNECTIVITY`, `BACKGROUND`)?

### 2.6. Testing

Does the code include adequate tests that follow our testing philosophy?

- **[ ] Test Coverage**: Are new features, code paths, and bug fixes covered by new or updated tests?

- **[ ] Layered Testing Hierarchy**: Do the tests adhere to the rules in `tests/README.md`?
  - **High-Level Components** (Managers, Modes): **MUST** use mocks for all hardware dependencies. Testing with real hardware at this level is a blocking issue.
  - **Mid-Level Components** (Services): Should prefer mocks. Real hardware is only for specific integration tests.
  - **Low-Level Components** (Controllers): **MAY** use real hardware only when it is safe and contention-free, but mocks are still preferred for automated testing.

- **[ ] Test Independence**: Are tests independent and able to run in any order? Do they clean up their resources in `tearDown()` or `tearDownClass()`?
