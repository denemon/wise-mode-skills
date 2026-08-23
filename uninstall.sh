#!/usr/bin/env bash
# uninstall.sh — Uninstaller for wise-mode Claude Code skills and hooks
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/uninstall.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/uninstall.sh | bash -s -- --yes
#
# Removal order is the REVERSE of install.sh: the settings wiring is removed
# first, files second. If the run dies halfway, what remains is inert files;
# the opposite order would leave settings.local.json pointing at deleted
# hooks, and every subsequent prompt would surface a hook error.
#
# Data is never deleted: .claude/log/ (session logs) and .claude/flow/
# (wise-flow phase artifacts) are kept, with a cleanup command printed
# instead.
#
# The entire script is wrapped in main() so that a partial download
# never executes incomplete code.

main() {
    set -euo pipefail

    # ── Manifest ───────────────────────────────────────────────────
    # Mirrors install.sh; parity is enforced mechanically by
    # tests/test_packaging.py (UninstallScriptParityTest).
    SKILL_DIRS=(
        "terse-mode"
        "swarm"
        "wise"
        "wise-cont"
        "wise-flow"
        "attack-on-hacker"
        "pr-self-review"
    )

    # Retired skill names install.sh removes on upgrade; sweep them too.
    REMOVED_SKILLS=(
        "dev-with-review"
        "wise-flow-source-recon"
        "wise-flow-plan"
        "wise-flow-implement-review"
        "wise-flow-validate"
        "wise-flow-security-gate"
        "wise-flow-pr-gate"
        "wise-flow-handoff"
    )

    # session_log.py is included: only install.sh --with-session-log ever
    # places it, and its removal is listed in the consent prompt below.
    HOOK_FILES=(
        "mode_persistence.py"
        "flag_guard.py"
        "session_log.py"
    )

    # wise_mode.py was renamed to mode_persistence.py; install.sh deletes it
    # on upgrade, so the uninstaller sweeps it too. cclog-hook.sh is NOT
    # swept — the installer no longer carries removal code for it (README
    # "Uninstall" covers it); only its wiring is removed below.
    LEGACY_HOOK_FILES=(
        "wise_mode.py"
    )

    # Mode flags written next to the skills; removing them turns the modes
    # off. .claude/log/ and .claude/flow/ hold data and are kept.
    STATE_FLAGS=(
        ".wise-mode"
        ".terse-mode"
    )

    # Every hook command this project's installers ever wrote, matched
    # FULL-STRING against settings.local.json. Substring matching would also
    # delete third-party hooks that merely mention a file name (a user-owned
    # /opt/acme/session_log.py wiring was lost that way once).
    # shellcheck disable=SC2016  # $CLAUDE_PROJECT_DIR is literal in settings.
    CANONICAL_COMMANDS='[
        "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" UserPromptSubmit",
        "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" SessionStart",
        "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\" PreToolUse",
        "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" PostToolUse",
        "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" Stop",
        ".claude/hooks/cclog-hook.sh PostToolUse",
        ".claude/hooks/cclog-hook.sh Stop",
        "python3 .claude/hooks/session_log.py",
        "python3 .claude/hooks/session_log.py PostToolUse",
        "python3 .claude/hooks/session_log.py Stop"
    ]'

    YES=0
    for arg in "$@"; do
        case "$arg" in
            --yes) YES=1 ;;
            *)
                printf '[error] unknown option: %s\n' "$arg" >&2
                printf 'usage: uninstall.sh [--yes]\n' >&2
                exit 1
                ;;
        esac
    done

    # ── Colors (disabled when piped) ──────────────────────────────
    if [ -t 1 ]; then
        RED='\033[0;31m'
        GREEN='\033[0;32m'
        YELLOW='\033[0;33m'
        CYAN='\033[0;36m'
        BOLD='\033[1m'
        RESET='\033[0m'
    else
        RED='' GREEN='' YELLOW='' CYAN='' BOLD='' RESET=''
    fi

    info()  { printf "${CYAN}[info]${RESET}  %s\n" "$1"; }
    ok()    { printf "${GREEN}[ok]${RESET}    %s\n" "$1"; }
    warn()  { printf "${YELLOW}[warn]${RESET}  %s\n" "$1"; }
    error() { printf "${RED}[error]${RESET} %s\n" "$1" >&2; }

    # ── Preflight ─────────────────────────────────────────────────
    if ! command -v python3 >/dev/null 2>&1; then
        error "python3 is required to edit the hooks configuration but was not found."
        exit 1
    fi

    PROJECT_ROOT="$(pwd)"
    CLAUDE_DIR="${PROJECT_ROOT}/.claude"
    SETTINGS_PATH="${CLAUDE_DIR}/settings.local.json"

    if [ ! -d "${CLAUDE_DIR}" ]; then
        info "No .claude directory in $(pwd) — nothing to remove."
        exit 0
    fi

    # ── Validate settings BEFORE anything is removed ──────────────
    # Same principle as install.sh: a malformed settings file must abort
    # here, with nothing touched. Aborting halfway through removal would
    # leave wiring that points at deleted hooks.
    if [ -f "${SETTINGS_PATH}" ]; then
        if ! python3 -c "
import json, sys
settings = json.load(open(sys.argv[1]))
hooks = settings.get('hooks', {})
if not isinstance(hooks, dict):
    raise SystemExit(1)
for entries in hooks.values():
    if not isinstance(entries, list):
        raise SystemExit(1)
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(1)
        if not isinstance(entry.get('hooks', []), list):
            raise SystemExit(1)
        for hook in entry.get('hooks', []):
            if not isinstance(hook, dict):
                raise SystemExit(1)
" "${SETTINGS_PATH}" 2>/dev/null; then
            error "Existing .claude/settings.local.json is not valid JSON, or its hooks section is malformed."
            error "Fix or remove it first — nothing was removed."
            exit 1
        fi
    fi

    # ── Inventory: what is actually installed here? ───────────────
    FOUND_SKILLS=()
    for name in "${SKILL_DIRS[@]}" "${REMOVED_SKILLS[@]}"; do
        if [ -d "${CLAUDE_DIR}/skills/${name}" ]; then
            FOUND_SKILLS+=("${name}")
        fi
    done

    FOUND_HOOKS=()
    for hook_file in "${HOOK_FILES[@]}" "${LEGACY_HOOK_FILES[@]}"; do
        if [ -f "${CLAUDE_DIR}/hooks/${hook_file}" ]; then
            FOUND_HOOKS+=("${hook_file}")
        fi
    done

    FOUND_FLAGS=()
    for flag in "${STATE_FLAGS[@]}"; do
        if [ -f "${CLAUDE_DIR}/${flag}" ]; then
            FOUND_FLAGS+=("${flag}")
        fi
    done

    SETTINGS_WIRED=0
    if [ -f "${SETTINGS_PATH}" ]; then
        if python3 -c "
import json, sys
canonical = set(json.loads(sys.argv[2]))
settings = json.load(open(sys.argv[1]))
for entries in settings.get('hooks', {}).values():
    for entry in entries:
        for hook in entry.get('hooks', []):
            command = hook.get('command', '')
            if command in canonical or 'wise_mode.py' in command:
                raise SystemExit(0)
raise SystemExit(1)
" "${SETTINGS_PATH}" "${CANONICAL_COMMANDS}"; then
            SETTINGS_WIRED=1
        fi
    fi

    if [ "${#FOUND_SKILLS[@]}" -eq 0 ] && [ "${#FOUND_HOOKS[@]}" -eq 0 ] \
        && [ "${#FOUND_FLAGS[@]}" -eq 0 ] && [ "${SETTINGS_WIRED}" -eq 0 ]; then
        info "wise-mode is not installed in $(pwd) — nothing to remove."
        exit 0
    fi

    # ── Consent ───────────────────────────────────────────────────
    warn "The following wise-mode components will be removed from ${PROJECT_ROOT}:"
    for name in ${FOUND_SKILLS[@]+"${FOUND_SKILLS[@]}"}; do
        echo "    .claude/skills/${name}/"
    done
    for hook_file in ${FOUND_HOOKS[@]+"${FOUND_HOOKS[@]}"}; do
        echo "    .claude/hooks/${hook_file}"
    done
    for flag in ${FOUND_FLAGS[@]+"${FOUND_FLAGS[@]}"}; do
        echo "    .claude/${flag}"
    done
    if [ "${SETTINGS_WIRED}" -eq 1 ]; then
        echo "    wise-mode hook wiring in .claude/settings.local.json"
    fi

    if [ "${YES}" -ne 1 ]; then
        printf "  Remove? [y/N] "
        if ! read -r answer </dev/tty 2>/dev/null; then
            echo ""
            error "No terminal available to confirm. Re-run with --yes."
            exit 1
        fi
        case "$answer" in
            [yY]|[yY][eE][sS]) : ;;
            *) info "Aborted. Nothing was removed."; exit 0 ;;
        esac
    fi

    # ── Unwire settings FIRST ─────────────────────────────────────
    # Full-string match against the canonical commands only; everything the
    # user or other tools wired stays byte-identical.
    if [ "${SETTINGS_WIRED}" -eq 1 ]; then
        TMPDIR_WORK="$(mktemp -d)"
        trap 'rm -rf "${TMPDIR_WORK}"' EXIT
        CLEANED_SETTINGS="${TMPDIR_WORK}/settings.local.json"
        python3 -c "
import json, sys

settings_path, canonical_json, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
canonical = set(json.loads(canonical_json))

with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
for event in list(hooks):
    kept_entries = []
    for entry in hooks[event]:
        kept = [
            hook for hook in entry.get('hooks', [])
            if hook.get('command', '') not in canonical
            # wise_mode.py was renamed away; install.sh drops it by
            # substring too, so no legitimate wiring can mention it.
            and 'wise_mode.py' not in hook.get('command', '')
        ]
        if kept:
            updated_entry = dict(entry)
            updated_entry['hooks'] = kept
            kept_entries.append(updated_entry)
    if kept_entries:
        hooks[event] = kept_entries
    else:
        del hooks[event]
settings['hooks'] = hooks

with open(output_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
" "${SETTINGS_PATH}" "${CANONICAL_COMMANDS}" "${CLEANED_SETTINGS}"
        cp "${CLEANED_SETTINGS}" "${SETTINGS_PATH}"
        ok "wise-mode hook wiring removed from .claude/settings.local.json"
    fi

    # ── Remove files ──────────────────────────────────────────────
    for name in ${FOUND_SKILLS[@]+"${FOUND_SKILLS[@]}"}; do
        rm -rf "${CLAUDE_DIR}/skills/${name}"
    done
    for hook_file in ${FOUND_HOOKS[@]+"${FOUND_HOOKS[@]}"}; do
        rm -f "${CLAUDE_DIR}/hooks/${hook_file}"
    done
    for flag in ${FOUND_FLAGS[@]+"${FOUND_FLAGS[@]}"}; do
        rm -f "${CLAUDE_DIR}/${flag}"
    done

    # Leftover staging from a killed install is the installer's own artifact.
    rm -rf "${CLAUDE_DIR}/.install-staging"

    # Drop the now-empty containers; rmdir never touches a non-empty one.
    rmdir "${CLAUDE_DIR}/skills" 2>/dev/null || true
    rmdir "${CLAUDE_DIR}/hooks" 2>/dev/null || true

    # ── Summary ───────────────────────────────────────────────────
    echo ""
    printf '%s\n' "${BOLD}${GREEN}  wise-mode uninstalled.${RESET}"
    echo ""
    # Relative paths on purpose: interpolating ${CLAUDE_DIR} would hand the
    # user a copy-paste command that splits on a space in the project path.
    if [ -d "${CLAUDE_DIR}/log" ]; then
        warn "Session logs were kept (masked, but still sensitive): .claude/log/"
        warn "Remove them yourself if unwanted: rm -r .claude/log"
    fi
    if [ -d "${CLAUDE_DIR}/flow" ]; then
        warn "wise-flow phase artifacts were kept: .claude/flow/"
        warn "Remove them yourself if unwanted: rm -r .claude/flow"
    fi
}

# Run everything inside main() to guard against partial downloads
main "$@"
