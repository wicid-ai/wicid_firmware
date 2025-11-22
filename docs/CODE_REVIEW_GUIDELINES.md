# WICID Firmware Code Review Guidelines

## 1. Objective & Philosophy

Code reviews ensure the long-term health, reliability, and maintainability of the WICID firmware. The goal is to catch architectural drifts, enforce patterns, and ensure every line of code looks like it belongs in this specific project.

**For Reviewers (Human & AI):** Your job is to act as a gatekeeper for quality. You must verify that changes are not just "working" code, but "correct" code according to our specific project rules.

---

## 2. Phase 1: Automated Checks

Before inspecting logic, ensure the code passes all automated static analysis.

Run the pre-commit hooks on all files.
```bash
pipenv run pre-commit run --all-files
```

**Action:**
- If these commands fail, the review **fails immediately**.
- Report the specific linting, formatting, or typing errors found.
- Do not proceed to logic review until these are resolved.

---

## 3. Phase 2: Comprehensive Review Checklist

Evaluate the code against the following criteria. Use the referenced documentation as the source of truth.

### 3.1 Architectural Adherence
*Reference: `docs/ARCHITECTURE.md`, `docs/PATTERNS_COOKBOOK.md`*

- **[ ] Manager Pattern**: Are Managers implemented as Singletons? Do they use `instance()` for access?
- **[ ] Component Roles**:
  - **Managers**: Orchestrate logic and state?
  - **Controllers**: Wrap hardware only (no business logic)?
  - **Services**: encapsulate external/network logic?
- **[ ] Dependency Injection**: Are dependencies (like pins) passed into `instance()` to allow for testing?
- **[ ] Error Handling**:
  - Are recoverable errors raised as `TaskNonFatalError`?
  - Are fatal hardware failures raised as `TaskFatalError`?
  - **No silent failures**: Are errors caught and logged, not ignored?

### 3.2 Scheduler & Async Logic
*Reference: `docs/SCHEDULER_ARCHITECTURE.md`, `docs/PATTERNS_COOKBOOK.md`*

- **[ ] Cooperative Multitasking**:
  - Does the code use `await Scheduler.sleep()` instead of `time.sleep()` or `asyncio.sleep()`?
  - Do long loops (`while True`) contain `await Scheduler.yield_control()`?
- **[ ] No Blocking**: Are there any synchronous network calls or long computations that would starve the scheduler?
- **[ ] Task Priorities**: Are tasks assigned appropriate priorities (Critical vs Background)?

### 3.3 Testing & Verification
*Reference: `tests/README.md`, `docs/PATTERNS_COOKBOOK.md`*

- **[ ] Hardware Mocks**: Does the code use mocks (e.g., `create_mock_button_pin`) instead of importing `board` in logic tests?
- **[ ] Coverage**: Do new features have corresponding unit tests?
- **[ ] Layered Approach**: Are logic tests separated from hardware integration tests?

### 3.4 Style & Quality
*Reference: `docs/STYLE_GUIDE.md`*

- **[ ] Type Hinting**: Do all new functions have full type hints (`def foo(x: int) -> bool:`)?
- **[ ] App Typing**: Are types imported from `app_typing` (e.g. `from app_typing import List`) instead of `typing`?
- **[ ] Docstrings**: Do public methods have Google-style docstrings?
- **[ ] Comments**: Do comments explain "Why", not "What"? (Avoid "Increment i" style comments).
- **[ ] Naming**: Do variables use `snake_case` and constants use `UPPER_CASE`?

---

## 4. Phase 3: The Actionable Report

When the review is complete, generate a report in the following format.

### 4.1 Severity Levels

Rank every issue found using these levels:

- **🔴 CRITICAL**: Blocking. The code is broken, dangerous, or violates core architecture (e.g., using `time.sleep`, bypassing Singletons). **Must fix immediately.**
- **🟠 MAJOR**: Important. Functional bugs, missing tests, or significant style violations (e.g., missing type hints on public APIs). **Should fix before merge.**
- **🟡 MINOR**: Nitpicks. Typographical errors, comment clarity, or minor refactoring suggestions. **Can fix later.**

### 4.2 Report Template

```markdown
# Code Review Report

## Summary
[Pass/Fail]. [Brief summary of the overall quality and readiness].

## 🔴 Critical Issues
1. **[Category]**: [Description of the issue].
   - *File*: `src/example.py`
   - *Fix*: [Specific instruction on how to fix it]

## 🟠 Major Issues
1. **[Category]**: [Description].

## 🟡 Minor Issues
1. **[Category]**: [Description].

## ✅ Verification
- [ ] Pre-commit checks passed?
- [ ] Type checks (mypy) passed?
- [ ] Architecture patterns followed?
- [ ] Scheduler rules respected?
```
