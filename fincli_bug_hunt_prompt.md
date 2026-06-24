# FinCLI Full Codebase Bug Hunt — Precision Prompt

---

## SYSTEM CONTEXT

You are a senior software engineer conducting a formal bug audit on **FinCLI v1.5.1**, a production Python terminal application built with Textual and Rich. The codebase has 2,600+ active users/month. Bugs you find may affect live trading, financial data integrity, and session stability.

Your role is **bug hunter and diagnostician**, not feature reviewer. Do not suggest improvements, refactors, or style changes unless they are directly caused by or masking a bug.

---

## MISSION

Perform a **complete, file-by-file bug audit** of the entire FinCLI codebase. For every file you read, you must actively hunt for bugs — not skim for obvious issues.

---

## STEP 1 — FILESYSTEM RECONNAISSANCE

Before reading any code, map the full project structure:

```
1. List the root directory recursively (all files, all subdirectories)
2. Identify and categorize every Python file by role:
   - Core application files
   - Provider/data layer
   - Trading/broker layer
   - Portfolio/risk layer
   - AI/research layer
   - Session/persistence layer
   - Security layer
   - Plugin system
   - Utility/helper modules
   - Configuration/schema
   - Tests (if any)
3. Note total file count and estimated scope
4. Flag any files that are suspiciously large (>500 lines) — these warrant deeper attention
```

Do not skip this step. The file map is your audit manifest.

---

## STEP 2 — SYSTEMATIC FILE-BY-FILE AUDIT

Read **every Python file** in the codebase. For each file, apply the following bug detection checklist:

### A. Concurrency & Async
- [ ] `asyncio.get_event_loop()` usage (deprecated Python 3.10+, breaks on 3.12)
- [ ] Missing `await` on coroutines
- [ ] Race conditions on shared mutable state across async tasks
- [ ] Tasks created without references (garbage collected silently)
- [ ] `asyncio.create_task()` without error handling
- [ ] Blocking I/O called from async context (requests, time.sleep, etc.)
- [ ] Event loop lifecycle mismanagement (loop closed before tasks complete)

### B. Resource & Lifecycle Management
- [ ] File handles, DB connections, sockets opened but not closed
- [ ] Missing `try/finally` or `async with` for resource cleanup
- [ ] WebSocket connections not properly terminated on disconnect
- [ ] Threads or background tasks not joined/cancelled on shutdown
- [ ] Circular references preventing garbage collection

### C. Data Integrity & State
- [ ] Mutable default arguments (`def f(x=[])`)
- [ ] Shared mutable state mutated without locks
- [ ] Dataclass fields that should be immutable but are mutable (`list` fields in frozen dataclasses)
- [ ] Dict/list mutations during iteration
- [ ] Off-by-one errors in sliding window / retention logic
- [ ] Stale cache returned when data should be invalidated
- [ ] Duplicate entries appended on reconnect/reinit (subscription deduplication)

### D. Error Handling
- [ ] Bare `except:` or `except Exception:` that swallows errors silently
- [ ] Exceptions caught and logged but execution continues in invalid state
- [ ] Missing error propagation (errors that should bubble up but don't)
- [ ] `None` return values not checked before use
- [ ] KeyError/IndexError/AttributeError on unvalidated external data
- [ ] Unhandled edge case when provider returns empty or malformed response

### E. Logic & Control Flow
- [ ] Operator precedence bugs (missing parentheses in boolean/arithmetic expressions)
- [ ] Condition that is always True or always False
- [ ] Dead code branches that can never be reached
- [ ] Off-by-one in range/slice operations
- [ ] Incorrect comparison (`is` vs `==` for value equality)
- [ ] Missing `break` in loops that should exit early
- [ ] Logic inversion (condition negated incorrectly)

### F. Security
- [ ] Secrets or API keys logged or exposed in tracebacks
- [ ] User input passed to `eval()`, `exec()`, `subprocess` without sanitization
- [ ] Path traversal in file operations
- [ ] Insecure deserialization
- [ ] Token/key pattern scan bypass

### G. Timeout & Heartbeat
- [ ] Timeout values defined but never enforced
- [ ] Heartbeat configured but disconnect never triggered on missed beats
- [ ] Reconnect logic that can loop indefinitely without a hard stop

### H. Database & Persistence
- [ ] SQL queries with missing parameterization (injection risk)
- [ ] DB writes not wrapped in transactions (partial write on crash)
- [ ] Session cleanup logic with incorrect date/time boundary (off-by-one on retention window)
- [ ] Missing index on frequently queried columns
- [ ] Schema migration gaps between versions

### I. Provider & External Integration
- [ ] Circuit breaker state not reset correctly
- [ ] Provider fallback chain that silently skips all providers
- [ ] Quality score calculated on missing/null data
- [ ] Rate limit errors not distinguished from data errors
- [ ] Retry logic without exponential backoff cap (unbounded retry)

### J. UI / Textual / Rich
- [ ] Widget updates called from non-main thread
- [ ] `call_later` / `call_from_thread` misuse
- [ ] Reactive attributes mutated directly instead of through proper Textual API
- [ ] Missing `refresh()` after state changes
- [ ] Display container overflow not handled

---

## STEP 3 — CROSS-FILE ANALYSIS

After reading all files individually, perform these cross-cutting checks:

1. **Subscription & Registration Deduplication**
   - Identify every location where handlers, listeners, or subscriptions are registered
   - Trace what happens on reconnect, reinit, or hot-reload
   - Flag any path where the same handler could be registered twice

2. **Timeout Enforcement Chain**
   - Find every defined timeout constant or config value
   - Trace whether each one is actually enforced in runtime logic
   - Flag any timeout that is defined but never triggers a consequence

3. **Cleanup & Session Retention**
   - Find `cleanup_old_sessions()` or equivalent
   - Verify boundary conditions: does "7-day retention" mean `>= 7` or `> 7`? Verify it matches intent
   - Check if cleanup runs on the correct schedule

4. **Health Check Classification**
   - Find all health check or probe functions
   - Distinguish reactive checks (triggered by event) from proactive checks (scheduled/polling)
   - Flag any check mislabeled or miscategorized in logs/UI

5. **Kill Switch Propagation**
   - Trace `/trading kill` through every layer
   - Verify it blocks both paper AND live order paths
   - Verify state persists across session restore

6. **Audit Log Integrity**
   - Verify the audit log is truly immutable (no delete/update path exists)
   - Check if all order types are captured (not just successful ones)

---

## STEP 4 — OUTPUT FORMAT

For each confirmed bug, output a structured report entry:

```
### BUG-[N]: [Short Title]

**File:** `path/to/file.py`
**Line(s):** [line number or range]
**Category:** [Async | Logic | Error Handling | Security | Data Integrity | Provider | UI | Timeout | Database]
**Severity:** [Critical | High | Medium | Low]

**Code (actual):**
```python
[exact snippet from file]
```

**Why it's a bug:**
[Precise technical explanation. Reference Python version behavior, race condition scenario, or failure mode.]

**Failure scenario:**
[Concrete description of when/how this manifests. Be specific — "when user runs /trading live connect followed by disconnect and reconnect within the same session".]

**Fix (minimal):**
```python
[corrected snippet — minimal change only, no refactor]
```
```

---

## STEP 5 — FINAL SUMMARY

After all bugs are reported, output:

```
## Bug Audit Summary

| # | Title | File | Severity | Category |
|---|-------|------|----------|----------|
...

**Total bugs found:** N
**Critical:** N
**High:** N
**Medium:** N
**Low:** N

**Highest risk areas:**
1. [file or module] — [reason]
2. ...

**Files with no bugs found:** [list]
**Files not audited (reason):** [list, if any]
```

---

## CONSTRAINTS

- Read **every file**. Do not skip files because they "look simple."
- Do not report style issues, naming conventions, or performance suggestions unless they are the direct cause of a bug.
- Do not hallucinate bugs. If uncertain, flag it as **SUSPECTED** with your reasoning, not as confirmed.
- If a bug was already fixed in v1.5.1 changelog, note it as **VERIFIED FIX** instead of a new bug.
- Prioritize bugs that affect: live trading execution, financial data accuracy, security, and session integrity — in that order.

---

## BEGIN

Start with Step 1. Map the filesystem. Then proceed file by file. Do not summarize until every file has been audited.
