---
name: verify
description: How to actually run this repo's artifacts so a change can be observed at its real surface. Use before claiming a change to install.sh, hooks/, or skills/*/scripts/ works.
---

# Verifying wise-mode

Regressions are `./check.sh`'s job — it runs the suites and the linters and
answers "did anything break". It never executes the change. This file is the
other half: how to actually run each artifact so a change can be *observed*.

Nothing here is a long-running app. The surfaces are: an installer executed by
`curl | bash`, two hooks Claude Code invokes with JSON on stdin, and one shell
script a skill shells out to. Each needs a different handle.

## Check the installed tree, not the settings file

A hook's name appearing in the generated `settings.local.json` is a *claim* that
it was installed. It is not the file being on disk. Removing an unrelated feature
once took `cp` and `chmod` out of the hook loop, and the installer shipped zero
hooks while the suite stayed green — because the test read the settings.

`tests/test_install.py::test_installed_tree_matches_the_manifest` now compares
the whole installed tree against `SKILLS` + `HOOK_FILES` in both directions. When
verifying by hand, do the same: `ls .claude/hooks/` before believing anything.

## install.sh — serve a local snapshot archive

`REPO_ARCHIVE_BASE` points at GitHub's tarball endpoint, so running it
unmodified verifies the *published* snapshot, not your working tree. Build a
tar.gz of the working tree, serve it, and swap that one line:

```bash
mkdir -p /tmp/wise-serve/tar.gz
tar -czf /tmp/wise-serve/tar.gz/main --exclude .git --exclude __pycache__ \
  -s '|^\./|wise-mode-main/|' .   # GNU tar: --transform 's|^\./|wise-mode-main/|'
python3 -m http.server 8731 --directory /tmp/wise-serve &
sed 's|REPO_ARCHIVE_BASE="https://codeload.github.com/den-emon/wise-mode/tar.gz"|REPO_ARCHIVE_BASE="http://127.0.0.1:8731/tar.gz"|' \
  install.sh > /tmp/install-local.sh
mkdir -p /tmp/proj/.claude && cd /tmp/proj && bash /tmp/install-local.sh </dev/null
```

Create `.claude/` in the target first — otherwise the "Install here anyway?"
prompt blocks on `/dev/tty`. `tests/test_install.py` automates all of this.

### Gotcha: `printf 'y' | script` does NOT answer the prompts

It looks like it works — you get output, no error, and the target directory
looks plausible. The run actually stops at `Overwrite? [y/N]` and everything
after it never executes. Any "it worked" conclusion drawn this way is
meaningless: nothing was overwritten.

Drive prompts with a real pty (`pty.fork()` + `select`, answer when `[y/N]`
appears), and always capture the full output to confirm the run reached the
end.

## Hooks — use the exact command line from settings.local.json

Not `python3 hooks/x.py`. Run what Claude Code runs:

```bash
export CLAUDE_PROJECT_DIR=/tmp/proj
echo '{"session_id":"s1","cwd":"/tmp/proj","prompt":"/wise-cont"}' \
  | python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py" UserPromptSubmit
```

Payload shapes live in `hooks/fixtures/*.json` — that is the single source of
truth for what Claude Code actually sends. Do not hand-write a payload; a wrong
key there passed unnoticed for a long time because the tests shared the
mistake.

Persistence is the point of `mode_persistence.py`: send a *second, unrelated*
prompt and confirm the reminder is re-injected. A single call proves nothing.

## ai_review.sh — fake `claude` on PATH

```bash
cd /tmp/proj
git init -q
printf '.claude/\nfakebin/\n' >> .git/info/exclude
printf 'review fixture\n' >> ai-review-fixture.txt
git add ai-review-fixture.txt
mkdir -p fakebin
printf '#!/bin/sh\ncat >/dev/null\necho %s\n' "'{\"summary\":\"ok\",\"score\":8,\"coverage\":\"complete\",\"findings\":[],\"positive_notes\":[]}'" > fakebin/claude
chmod +x fakebin/claude
PATH="$PWD/fakebin:$PATH" bash .claude/skills/wise-flow/scripts/ai_review.sh --lang python --worktree
```

**Always shadow `claude`.** A dev machine has the real one; forgetting the fake
makes a billed API call and silently passes. `tests/test_ai_review.py` installs
a guard stub that exits 97 for exactly this reason.

The disposable `/tmp/proj` fixture intentionally stages a change before running:
plain `git diff` is empty once staged, which is the situation this script is
used in. Do not use this fixture recipe in a real working repository.

## Skills (Markdown) — behaviour has a live eval surface

Static checks (`tests/test_packaging.py`, `tests/test_skill_review_safety.py`)
only prove the desired sentences exist in the SKILL.md — not that Claude
follows them. The runtime surface is:

```bash
./check.sh --evals            # real claude -p calls — billed, needs auth
```

It builds a fresh fixture repo, installs the skills into it, runs
representative prompts in fresh sessions — including a skill-off baseline, per
the official recommendation — and asserts the MANDATORY markers each SKILL.md
defines. Run it after a meaningful behaviour change to a skill. Report SKIP
only for changes no eval can observe (wording-only edits), and name the eval
that covers the rest. Long-horizon effect is still
`benchmarks/fix_follow_rate.py`.

## Strip ANSI before grepping

Colors turn on whenever stdout is a tty, which includes anything run under a
pty. `^\[warn\]` will not match `\033[0;33m[warn]`. Pipe through
`sed 's/\x1b\[[0-9;]*m//g'` first.

## Full verification

```bash
./check.sh            # everything: bash -n, shellcheck, py syntax, 3 suites (~25s)
./check.sh --fast     # skips the slow integration suites (~3s)
./check.sh --mutants  # audits the guards themselves (~2.5min)
```

Do not assemble the checks by hand — the scope then depends on whoever is
running them, which is how "all tests pass" ends up meaning different things.

### Never run the audit alongside anything else

`--mutants` rewrites files in the live tree and restores them. Anything reading
the tree concurrently sees corruption. Both of these actually happened:

- a parallel `./check.sh` produced a **false FAILED** (36s instead of 3s)
- a `git add -A` **staged a mutated file into the index**

A lock now blocks a second audit and makes the Stop gate report *inconclusive*
instead of a bogus failure, but a plain `git` command in another terminal is
still on you. Also: a recursive audit once left **93 accumulated trailing
spaces** on README line 1, so if a file looks subtly off after an interrupted
run, check whitespace.

### Registering a mutation for your own fix

Every fix needs an entry in `tools/mutants.py`. The `before` string must occur
**exactly once** in the target file, or the audit rewrites the wrong place and
reports a meaningless verdict. When the target *is* `tools/mutants.py`, write
the string as a concatenation (`"def foo()" + " -> int:"`) so the registry
literal does not itself match.
