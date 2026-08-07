# Wise Flow Source Recon

Build the evidence pack that lets the next phase plan without guessing.

## Principle

Source first, questions later.

If the answer can be discovered from files, commands, local history, tests, or
nearby patterns, discover it instead of asking. Do not turn uncertain guesses
into facts. Mark them as unknowns.

## Stop Condition

Do not move to planning until you can state:

- where the relevant behavior enters the system
- which files likely own the behavior
- how current behavior works, with file-backed evidence
- which tests or validation commands are relevant
- what risks and unknowns remain

If any item is still unknown, continue searching unless further progress would
require product intent, credentials, external systems, or a risky assumption —
or the exploration ceiling in `SKILL.md` (25 calls) is reached. This condition
says when you may stop; the ceiling says when you must.

## Recon Steps

### 1. Request Signals

Extract search signals from the user request:

- feature names, errors, stack traces, routes, commands, UI labels
- function, class, component, table, config, env var, or package names
- expected behavior, observed behavior, constraints, and non-goals

Use these as initial search terms. Expand terms only when source evidence points
to aliases or adjacent concepts.

### 2. Repository Orientation

Start with cheap global context:

1. `git status --short`
2. `rg --files`
3. project guidance: `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`, docs, PR templates
4. manifests and build files: `package.json`, `pyproject.toml`, `Cargo.toml`,
   `go.mod`, `pom.xml`, `build.gradle`, lockfiles, framework configs
5. test and CI hints: test directories, config files, workflow files

Capture language, framework, package manager, test runner, and validation
commands if discoverable.

### 3. Entry Point Discovery

Find where the relevant behavior enters the system:

- web routes, controllers, handlers, API endpoints, middleware
- CLI commands, jobs, schedulers, event consumers, webhooks
- UI components, forms, actions, stores, hooks
- library/public APIs, exported functions, package entrypoints
- config/env-driven behavior

Use `rg` for request terms, route fragments, error strings, public symbols, and
config keys. Prefer reading the smallest files that prove entry points.

### 4. Target Surface

Read the files closest to the behavior:

- owner implementation
- immediate callers and consumers
- dependencies called by the owner
- related config, schema, types, migrations, fixtures, and generated interfaces
- nearby examples that show local style

Map both directions: callers -> target -> dependencies.

### 5. Behavior Model

Explain current behavior from source evidence:

- input shape and trust boundary
- data flow and transformations
- state changes, persistence, cache, network, filesystem, or queue side effects
- error handling and fallback paths
- boundary cases: null, empty, missing, duplicate, large, concurrent, unauthorized
- invariants that must remain true

Use file references in notes. If behavior is inferred, label it `inferred`.

### 6. Test Surface

Find how this area is tested:

- direct unit/integration/e2e tests
- fixtures, factories, snapshots, golden files
- nearby tests for similar behavior
- documented validation commands
- CI commands if local commands are unclear

Identify the smallest useful test command and any broader command needed for
shared behavior.

### 7. Risk Surface

Flag risks that planning must account for:

- shared state, concurrency, transactions, idempotency
- public API, schema, serialization, or response shape changes
- auth/authz, tenant boundaries, secrets, external input, file I/O
- migrations, generated code, dependency changes, CI/deployment behavior
- user-visible behavior or backwards compatibility

If security-sensitive signals appear, mark `security_gate_required: yes`.

### 8. Scope Control

Do not read the whole repository by default. Expand only when:

- entry point is still unknown
- caller/dependency map is incomplete
- tests cannot be located
- risk surface suggests hidden coupling

Prefer `rg`, file lists, and narrow reads over broad file dumps.

## Output

Return an Evidence Pack:

```markdown
## Evidence Pack

### Request Signals
- <signal> -> <where it was searched/found>

### Repo Orientation
- Language/framework/tooling:
- Test runner / validation commands:
- Project guidance read:

### Entry Points
- `path:line` -> <route/command/component/API and why it matters>

### Target Surface
- Owner files:
- Callers/consumers:
- Dependencies/config/schema:
- Related tests/fixtures:

### Current Behavior
- <source-backed behavior summary>

### Patterns To Preserve
- <naming/errors/logging/state/test patterns>

### Risks
- shared-state/concurrency:
- contract/schema/API:
- security:
- data/side effects:

### Validation Candidates
- Targeted:
- Broader:

### Unknowns
- <unknown> — blocks planning? yes/no

### Next Route
- classification: simple | normal | complex | security-sensitive | review-only
- swarm candidate: yes/no and why
- security_gate_required: yes/no
```

Ask at most one question after the Evidence Pack, only if a blocking unknown
cannot be resolved from source.
