# AGENTS.md

## Shell Baseline

Shell scripts must run under **bash 3.2** — the default on macOS, and what the
primary development machine uses. CI only exercises Ubuntu's bash 5, so nothing
automated catches a bash 4+ construct.

Do not use: `mapfile` / `readarray`, associative arrays (`declare -A`),
`${var^^}` / `${var,,}`, or `timeout` (GNU coreutils; absent from a stock macOS).

## Guards, Not Just Fixes

A fix without a guard is not a correction — it holds until the next edit and then
silently reverts. When you fix something, add the check that fails if it comes
back, then register a mutation in `tools/mutants.py` proving that check works.

`./check.sh --mutants` reverts every registered fix one at a time and requires
the corresponding test to fail. An entry that survives means the guard is absent.

## Deleting

**Quote what you delete.** Removing a range by computing offsets — find marker A,
find marker B, drop everything between — deletes text you never read. That is how
`cp` and `chmod` disappeared from the installer's hook loop while removing an
unrelated feature: the essential lines happened to sit between the two markers.
Use an exact-match edit whose old text is the entire block being removed, so the
thing leaving the file is in front of you.

**Check the whole manifest, not a sample.** The installer test passed through
that breakage because it asserted the hook's *name appeared in the generated
settings* rather than that the *file was on disk*. A claim about the output is
not the output. Where a manifest exists — `SKILLS`, `HOOK_FILES`, the uninstall
list — compare it to reality exhaustively and in both directions; a spot check
only covers the spot you thought of.

## Verification Machinery Has a Budget

The rule above pulls in one direction only, and following it without a
counterweight produced a repository where **89% of one session's new lines were
machinery and 2% were product** — while that machinery generated twice as many
defects as the product code it was protecting, and required seven manual
repairs of a corrupted working tree.

Three limits keep it honest:

**Test machinery that runs by itself; don't test machinery that reports.** The
Stop gate and the edit-time linter fire automatically every turn — a bug there
either blocks the session or passes silently, so they need tests. The mutation
runner is invoked by hand and prints its verdict; when it breaks, the report is
wrong in a visible way, and the guard it failed to check will be caught by the
next audit. Testing *it* is where the cost ran away: six incidents, zero product
defects found, and a working tree that needed manual repair seven times.

Counting nesting depth is the wrong test — that rule would also delete the gate's
tests, which have never caused an incident. Ask instead: *if this breaks, does
anything say so?*

**Machinery is justified by product defects caught, not by its own.** A mechanism
whose only finds are inside itself is a net loss. Delete it and accept that its
failures will surface indirectly, through a guard that stops guarding.

**Machinery must not write to the working tree.** `tools/mutants.py` is the one
exception and it needs a lock, restore-on-exit, leak detection, and a baseline
check to be safe — four mechanisms that exist purely because it mutates real
files. Do not add a second such tool.

## Core Principles

Choose the simplest implementation that fully satisfies the current requirements.

Avoid speculative abstractions, configuration, indirection, and extensibility. Do not design for hypothetical future requirements. At the same time, avoid known architectural dead ends that would make the stated requirements unnecessarily difficult to extend or maintain.

## Compatibility and Cleanup

Unless backward compatibility is an explicit requirement, do not preserve it.

Remove obsolete code paths, interfaces, configuration, and tests instead of adding compatibility layers, fallbacks, aliases, or migrations. Update callers to use the current design directly.

Do not keep dead code or deprecated behavior “just in case.”

## Incremental Development

Grow the system in working layers.

Start with the smallest version that works end to end. Add each capability on top of a product that is already functional, tested, and internally consistent.

Prefer small, complete increments over broad, partially implemented architecture. Never replace a working system with unfinished complexity.

Intermediate implementations may be limited in scope, but production code should not be intentionally disposable or depend on a planned rewrite.

## Architecture and Modularity

Keep components modular and concerns clearly separated.

Introduce abstractions only when they remove demonstrated duplication, isolate a meaningful responsibility, or make the current implementation easier to understand and maintain.

Make architectural decisions that are appropriate for the known requirements and likely lifetime of the system. Do not accept a knowingly fragile stopgap merely because it is faster to implement.

## Dependencies

Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability.

Before implementing functionality yourself or adding a new package:

1. Inspect the dependencies already used by the project.
2. Check the relevant documentation, source code, and type definitions.
3. Confirm that the required capability is not already available.

Do not reimplement common functionality without a clear project-specific reason. Do not add a dependency when the existing stack can solve the problem cleanly.

## Decision Priority

When principles appear to conflict, use this order of priority:

1. Correctly satisfy the explicit requirements.
2. Preserve a working end-to-end system.
3. Minimize complexity.
4. Maintain clear boundaries and long-term maintainability.
5. Avoid speculative flexibility and unnecessary compatibility.
