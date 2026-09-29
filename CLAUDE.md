# CLAUDE.md  
**Colaberry Agent Project Rules & Operating Model**

This file defines how Claude (and other AI coding agents) must behave when working in this repository.

This project does **not** use Moltbot.  
Claude Code and other coding agents are used to **build and maintain** the system — they are **not the runtime system itself**.

---

## Secret Safety — `NEON_DATABASE_URL`

`NEON_DATABASE_URL` in the root `.env` is the connection string for this
fork's Neon Postgres project (`inboxgenius-fork`), used by GitHub Actions and
the local dashboard-viewer mode ([RUNBOOK.md §4b](RUNBOOK.md)). Like every
other credential in `.env`: **never print, log, or echo its value in a
conversation, commit, or command output.** Reference it only by key name
(`grep '^NEON_DATABASE_URL=' .env | wc -c` to confirm presence, never
`cat`/`echo` the value). When pushing it to a GitHub secret, pipe it directly
inside a single shell command so the value never appears in tool output.

---

## ⚠️ Read `RUNBOOK.md` first

**Before debugging any production issue, deploy question, or "what is the current
setup" question — read [`RUNBOOK.md`](RUNBOOK.md).** It is the single source of
truth for live infrastructure (hosting, database, scheduler, URLs, the processing
pipeline, the frontend stack). Older chat sessions and memory frequently point at
**deprecated infra** (Railway, Windows Task Scheduler, and — since 2026-09-29 —
the GitHub Actions / Render / Vercel / Neon setup, now a frozen fallback; production
runs on a Hetzner server, `RUNBOOK.md` §4c) — `RUNBOOK.md` §0 lists what changed,
and §14 has commands to confirm the doc is still accurate against live systems.
Do not diagnose from memory; verify against `RUNBOOK.md`.

**When you change hosting, the database, the scheduler, the processing pipeline,
secrets, or the frontend stack, update `RUNBOOK.md` (and its "Last verified" date
and changelog) in the same commit.**

---

## ⚠️ Maintain `progress.md` after every code change

`RUNBOOK.md` §16 only logs infra/architecture incidents. Nothing tracked
day-to-day code changes (cleanups, refactors, small fixes) — which is exactly
why dead files and duplicate fixes kept slipping through unnoticed across
sessions: nobody had a single place to check "what already happened here"
before starting new work.

**After any code change, append a dated entry to `progress.md`** (repo root)
in the same commit: what changed, why, files touched, and any deferred
follow-up. Read `progress.md` before starting new work, the same way you read
`RUNBOOK.md` before diagnosing production issues.

---

## Core Principle

LLMs are probabilistic.  
Production systems must be deterministic.

Claude’s role is to:
- reason
- plan
- orchestrate
- modify instructions and code **carefully**

Claude is **not** the runtime executor of business logic.

---

## High-Level Architecture

This project follows an **Agent-First, Deterministic-Execution** model.

---

### Layer 1 — Directives (What to do)
- Human-readable SOPs
- Stored in `/directives`
- Written in plain language
- Describe:
  - goals
  - inputs
  - outputs
  - edge cases
  - safety constraints

Directives are **living documents** and must be updated as the system learns.

---

### Layer 2 — Orchestration (Decision making)
- This is **Claude**
- Responsibilities:
  - read relevant directives
  - plan changes
  - decide which tools/scripts are required
  - ask clarifying questions when needed
  - update directives with learnings

Claude **never** executes business logic directly.

---

### Layer 3 — Execution (Doing the work)
- Deterministic scripts
- Stored in `/execution` and optionally `/services/worker`
- Responsibilities:
  - API calls
  - data processing
  - database reads/writes
  - file operations
  - scheduled jobs

Execution code must be:
- repeatable
- testable
- auditable
- safe to rerun

---

## Folder Responsibilities

Claude must respect the following boundaries.

### `/agents`
- Agent personas and role definitions
- Behavioral descriptions
- No executable logic

### `/directives`
- SOPs and runbooks
- Step-by-step instructions
- Human-readable
- Claude reads these before acting

### `/execution`
- Deterministic tools and scripts
- One script = one clear responsibility
- Core logic must be importable and testable
- No orchestration logic
- No prompts

### `/services/worker` (if present)
- Long-running or scheduled jobs
- Calls scripts from `/execution`
- Represents the **actual runtime system**

### `/config`
- Environment wiring (dev vs prod identifiers)
- No secrets

### `/tests`
- Automated tests (unit + integration)
- Mirrors execution and worker structure

### `/tmp`
- Scratch space
- Always safe to delete
- Never committed

---

## Testing & Validation Rules

Testing is **mandatory**.

### Unit Testing
- All non-trivial execution logic must have unit tests
- Pure logic should be tested without I/O
- External dependencies must be mocked
- Unit tests must:
  - be fast
  - be deterministic
  - run locally

### Integration Testing
- Integration tests may touch:
  - dev sandboxes
  - test sheets
  - mock APIs
- Integration tests must:
  - never touch production
  - require explicit opt-in (env flag or CI label)

### Worker Testing
- Worker logic is tested as routing logic:
  - given inputs → correct execution scripts are called
  - retries, idempotency, and error handling are verified
- Workers must never send real comms during tests

### Directive Validation
Directives are not unit tested, but must be validated:
- required sections exist
- referenced files/scripts exist
- markdown is well-formed

---

## Claude Operating Rules

### 1. Never act blindly
- Always read relevant directives first
- If no directive exists, ask before creating one

### 2. Never mix layers
- No business logic in directives
- No orchestration logic in execution scripts
- No execution inside Claude responses

### 3. Prefer deterministic tools
If a task can be done via a script, **do not simulate it in natural language**.

---

### 4. Approval-gated changes
Claude must request approval before:
- large refactors
- schema changes
- deleting files
- production-impacting logic
- modifying safety or compliance directives

---

### 5. Self-Annealing Loop (Mandatory)

When something fails:
1. Identify the root cause
2. Fix the script or logic
3. Add or update tests
4. Update the relevant directive
5. Update `RUNBOOK.md` if infra / architecture / the pipeline changed
6. Confirm the system is stronger

Failures are inputs, not mistakes.

### 6. Verify current state before diagnosing

`RUNBOOK.md` is authoritative for the live setup, but treat it as *verifiable*,
not infallible. When a production symptom doesn't match it, run the checks in
`RUNBOOK.md` §14 (health endpoint, `gh run list`, workflow entrypoint, model
constant) and reconcile — update the doc if reality has moved.

### 7. Log every code change to `progress.md`

Same commit as the change, not a follow-up. See "Maintain `progress.md`"
above. This applies to cleanups and deletions too, not just features/fixes —
those are the changes most likely to get silently forgotten and rediscovered
the hard way.

---

## Tooling Assumptions

Claude may assume:
- Claude Code is available as a terminal coding agent
- VS Code / VSCodium / Cursor may be used for inspection and debugging
- Git is always present
- CI runs automated tests

Claude must **not** assume:
- Moltbot exists
- proprietary automation platforms exist
- production credentials are available locally

---

## Intern Safety Rules

This repository may be worked on by interns.

Therefore:
- No destructive scripts without confirmation
- No production writes without explicit environment checks
- No secrets in repo
- Clear setup instructions must exist in `/docs`
- One-command test execution must exist (e.g., `scripts/test`)

Claude should optimize for:
- clarity
- reproducibility
- teachability

---

## Definition of Done

A change is not complete unless:
- relevant unit tests exist and pass
- behavior-changing logic updates directives
- no secrets are introduced
- validation scripts pass
- changes are understandable by a junior developer
- `progress.md` has a dated entry for the change

---

## Summary

Claude is the **planner and orchestrator**, not the worker.

- Directives define intent
- Scripts do the work
- Workers run the system
- Tests protect correctness
- Claude improves the system over time

**Be deliberate.  
Be safe.  
Prefer systems over cleverness.**
