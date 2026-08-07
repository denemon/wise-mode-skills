#!/usr/bin/env bash
# install.sh — Installer for wise-mode Claude Code skills and hooks
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash
#   wget -qO- https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash
#
# The entire script is wrapped in main() so that a partial download
# never executes incomplete code.

main() {
    set -euo pipefail

    # ── Configuration ──────────────────────────────────────────────
    REPO_RAW_BASE="https://raw.githubusercontent.com/den-emon/wise-mode/main"

    # Skills to install: "source_path|install_name|file1,file2,..."
    SKILLS=(
        "terse-mode|terse-mode|SKILL.md"
        "swarm|swarm|SKILL.md"
        "wise|wise|SKILL.md,CHECKLISTS.md,PATTERNS.md"
        "wise-cont|wise-cont|SKILL.md"
        "wise-flow|wise-flow|SKILL.md,references/source-recon.md,references/plan.md,references/implement-review.md,references/validate.md,references/security-gate.md,references/handoff.md"
        "dev-with-review|dev-with-review|SKILL.md,scripts/ai_review.sh,references/reviewer_prompt.md"
        "attack-on-hacker|attack-on-hacker|SKILL.md,references/diff-mode.md,references/quick-wins.md,references/language-hints.md,references/report-format.md"
        "pr-self-review|pr-self-review|SKILL.md,references/diff-acquisition.md,references/output-format.md"
    )

    # Skills that used to be installed separately and are now phases of another
    # skill. Left in place they keep firing and compete with the new router.
    REMOVED_SKILLS=(
        "wise-flow-source-recon"
        "wise-flow-plan"
        "wise-flow-implement-review"
        "wise-flow-validate"
        "wise-flow-security-gate"
        "wise-flow-pr-gate"
        "wise-flow-handoff"
    )

    # Hook files to install
    HOOK_FILES=(
        "session_log.py"
        "mode_persistence.py"
    )

    # Hooks configuration to merge into settings.local.json.
    # shellcheck disable=SC2016  # $CLAUDE_PROJECT_DIR must reach the JSON literally;
    # Claude Code expands it at hook-run time, not at install time.
    HOOKS_CONFIG='{
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" UserPromptSubmit",
                        "timeout": 5
                    }
                ]
            }
        ],
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact|fork",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" SessionStart",
                        "timeout": 5
                    }
                ]
            }
        ],
        "PostToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" PostToolUse",
                        "timeout": 10
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" Stop",
                        "timeout": 10
                    }
                ]
            }
        ]
    }'

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

    # ── Preflight checks ─────────────────────────────────────────
    if command -v curl >/dev/null 2>&1; then
        fetch() { curl -fsSL --retry 3 --retry-delay 2 "$1"; }
    elif command -v wget >/dev/null 2>&1; then
        fetch() { wget -qO- --tries=3 "$1"; }
    else
        error "curl or wget is required but neither was found."
        exit 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        error "python3 is required for hooks configuration but was not found."
        exit 1
    fi

    # ── Detect project root ───────────────────────────────────────
    if [ -d ".git" ] || [ -d ".claude" ]; then
        PROJECT_ROOT="$(pwd)"
    else
        warn "No .git or .claude directory found in $(pwd)."
        printf "  Install here anyway? [y/N] "
        read -r answer </dev/tty
        case "$answer" in
            [yY]|[yY][eE][sS]) PROJECT_ROOT="$(pwd)" ;;
            *) error "Aborted. cd into your project root and retry."; exit 1 ;;
        esac
    fi

    # ── Check for existing installation ───────────────────────────
    EXISTING=0
    for skill_entry in "${SKILLS[@]}"; do
        rest="${skill_entry#*|}"
        install_name="${rest%%|*}"
        target=".claude/skills/${install_name}"
        if [ -d "${PROJECT_ROOT}/${target}" ] && [ -f "${PROJECT_ROOT}/${target}/SKILL.md" ]; then
            EXISTING=1
            break
        fi
    done
    for hook_file in "${HOOK_FILES[@]}"; do
        if [ -f "${PROJECT_ROOT}/.claude/hooks/${hook_file}" ]; then
            EXISTING=1
            break
        fi
    done

    if [ "${EXISTING}" -eq 1 ]; then
        warn "One or more skills/hooks already exist in .claude/"
        printf "  Overwrite? [y/N] "
        read -r answer </dev/tty
        case "$answer" in
            [yY]|[yY][eE][sS]) : ;;
            *) info "Aborted. Existing installation unchanged."; exit 0 ;;
        esac
    fi

    # ── Download to temp dir first (atomic install) ───────────────
    TMPDIR_DOWNLOAD="$(mktemp -d)"
    trap 'rm -rf "${TMPDIR_DOWNLOAD}"' EXIT

    FAIL=0
    INSTALLED_FILES=()

    # Download skills
    for skill_entry in "${SKILLS[@]}"; do
        source_path="${skill_entry%%|*}"
        rest="${skill_entry#*|}"
        install_name="${rest%%|*}"
        skill_files_str="${rest#*|}"
        IFS=',' read -ra skill_files <<< "${skill_files_str}"

        info "Downloading ${install_name} skill files..."

        for file in "${skill_files[@]}"; do
            url="${REPO_RAW_BASE}/skills/${source_path}/${file}"
            dest="${TMPDIR_DOWNLOAD}/skills/${source_path}/${file}"
            mkdir -p "$(dirname "${dest}")"
            if fetch "${url}" > "${dest}" 2>/dev/null; then
                if [ ! -s "${dest}" ]; then
                    error "Downloaded ${source_path}/${file} is empty."
                    FAIL=1
                fi
            else
                error "Failed to download ${source_path}/${file} from ${url}"
                FAIL=1
            fi
        done

        # Verify SKILL.md has expected frontmatter
        if [ -f "${TMPDIR_DOWNLOAD}/skills/${source_path}/SKILL.md" ]; then
            if ! head -1 "${TMPDIR_DOWNLOAD}/skills/${source_path}/SKILL.md" | grep -q "^---"; then
                error "${source_path}/SKILL.md does not look like a valid skill file (missing frontmatter)."
                FAIL=1
            fi
        fi
    done

    # Download hooks
    info "Downloading hook files..."
    mkdir -p "${TMPDIR_DOWNLOAD}/hooks"
    for hook_file in "${HOOK_FILES[@]}"; do
        url="${REPO_RAW_BASE}/hooks/${hook_file}"
        dest="${TMPDIR_DOWNLOAD}/hooks/${hook_file}"
        if fetch "${url}" > "${dest}" 2>/dev/null; then
            if [ ! -s "${dest}" ]; then
                error "Downloaded hooks/${hook_file} is empty."
                FAIL=1
            fi
        else
            error "Failed to download hooks/${hook_file} from ${url}"
            FAIL=1
        fi
    done

    if [ "${FAIL}" -ne 0 ]; then
        error "One or more files failed to download. Installation aborted."
        exit 1
    fi

    # ── Install skills ────────────────────────────────────────────
    for skill_entry in "${SKILLS[@]}"; do
        source_path="${skill_entry%%|*}"
        rest="${skill_entry#*|}"
        install_name="${rest%%|*}"
        skill_files_str="${rest#*|}"
        IFS=',' read -ra skill_files <<< "${skill_files_str}"

        target_dir="${PROJECT_ROOT}/.claude/skills/${install_name}"

        for file in "${skill_files[@]}"; do
            dest="${target_dir}/${file}"
            mkdir -p "$(dirname "${dest}")"
            cp "${TMPDIR_DOWNLOAD}/skills/${source_path}/${file}" "${dest}"
            INSTALLED_FILES+=("${dest}")
        done
    done

    # ── Remove renamed hook file (wise_mode.py -> mode_persistence.py) ──
    rm -f "${PROJECT_ROOT}/.claude/hooks/wise_mode.py"

    # ── Remove skills that were folded into other skills ──────────
    for removed in "${REMOVED_SKILLS[@]}"; do
        removed_dir="${PROJECT_ROOT}/.claude/skills/${removed}"
        if [ -f "${removed_dir}/SKILL.md" ]; then
            rm -rf "${removed_dir}"
            info "Removed ${removed} (now a phase of wise-flow)"
        fi
    done

    # ── Make skill scripts executable ─────────────────────────────
    # Only the files this installer wrote. A find over .claude/skills would also
    # chmod scripts belonging to skills installed from somewhere else.
    for installed in "${INSTALLED_FILES[@]}"; do
        case "${installed}" in
            *.sh) chmod +x "${installed}" ;;
        esac
    done

    # ── Install hooks ─────────────────────────────────────────────
    hooks_dir="${PROJECT_ROOT}/.claude/hooks"
    mkdir -p "${hooks_dir}"
    for hook_file in "${HOOK_FILES[@]}"; do
        dest="${hooks_dir}/${hook_file}"
        cp "${TMPDIR_DOWNLOAD}/hooks/${hook_file}" "${dest}"
        chmod +x "${dest}"
        INSTALLED_FILES+=("${dest}")
    done

    # ── Merge hooks config into settings.local.json ───────────────
    SETTINGS_PATH="${PROJECT_ROOT}/.claude/settings.local.json"
    python3 -c "
import json, os, sys

settings_path = sys.argv[1]
hooks_config = json.loads(sys.argv[2])

if os.path.exists(settings_path):
    with open(settings_path) as f:
        settings = json.load(f)
else:
    settings = {}

existing_hooks = settings.get('hooks', {})
# Legacy cleanup for older installs that still used cclog-hook.sh.
legacy_commands = {
    'PostToolUse': {
        '.claude/hooks/cclog-hook.sh PostToolUse',
        'python3 .claude/hooks/session_log.py',
        'python3 .claude/hooks/session_log.py PostToolUse',
    },
    'Stop': {
        '.claude/hooks/cclog-hook.sh Stop',
        'python3 .claude/hooks/session_log.py',
        'python3 .claude/hooks/session_log.py Stop',
    },
}

for event, entries in list(existing_hooks.items()):
    cleaned_entries = []
    for entry in entries:
        hooks = [
            hook for hook in entry.get('hooks', [])
            if hook.get('command', '') not in legacy_commands.get(event, set())
            # wise_mode.py was renamed to mode_persistence.py. A leftover entry
            # points at a deleted file and fails on every prompt.
            and 'wise_mode.py' not in hook.get('command', '')
        ]
        if hooks:
            updated_entry = dict(entry)
            updated_entry['hooks'] = hooks
            cleaned_entries.append(updated_entry)
    existing_hooks[event] = cleaned_entries

for event, entries in hooks_config.items():
    if event not in existing_hooks:
        existing_hooks[event] = entries
    else:
        existing_cmds = set()
        for entry in existing_hooks[event]:
            for h in entry.get('hooks', []):
                existing_cmds.add(h.get('command', ''))
        for entry in entries:
            missing_hooks = [
                hook for hook in entry.get('hooks', [])
                if hook.get('command', '') not in existing_cmds
            ]
            if missing_hooks:
                updated_entry = dict(entry)
                updated_entry['hooks'] = missing_hooks
                existing_hooks[event].append(updated_entry)
                for hook in missing_hooks:
                    existing_cmds.add(hook.get('command', ''))

settings['hooks'] = existing_hooks

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
" "${SETTINGS_PATH}" "${HOOKS_CONFIG}"

    ok "Hooks configuration merged into .claude/settings.local.json"

    # ── Summary ───────────────────────────────────────────────────
    echo ""
    printf '%s\n' "${BOLD}${GREEN}  wise-mode installed successfully!${RESET}"
    echo ""
    info "Installed files:"
    for f in "${INSTALLED_FILES[@]}"; do
        echo "    ${f}"
    done
    echo ""
    info "Usage:"
    echo "    /terse-mode       - Brevity mode with lite/full/ultra intensity"
    echo "    /swarm            - Parallel delegation planning"
    echo "    /wise             - Architect mode for a single task"
    echo "    /wise-cont        - Architect mode for the entire session"
    echo "    /wise-flow        - Source-first development flow router (phases live inside it)"
    echo "    /dev-with-review  - Implement + continuous self-review + independent AI review"
    echo "    /attack-on-hacker - Adversarial source-code security review"
    echo "    /pr-self-review   - Self code review on own diff before opening a PR"
    echo ""
    info "Session logs are written to .claude/log/ automatically by the hook."
    echo ""

    # ── Check: are the session logs actually ignored? ──────────────
    # The PostToolUse hook writes tool input and command output to
    # .claude/log/. Secrets are masked before writing, but the masking is
    # pattern-based, so these files stay sensitive and should not be committed.
    if git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        # Trailing slash matters: a directory-only rule like `.claude/log/` does
        # not match the path `.claude/log` while that directory does not exist yet.
        if git -C "${PROJECT_ROOT}" check-ignore -q ".claude/log/" 2>/dev/null; then
            ok "Session logs (.claude/log/) are git-ignored."
        else
            warn "'.claude/log/' is NOT git-ignored, and the hook writes command output there."
            warn "Add this to .gitignore before your next commit:"
            echo "    .claude/log/"
            echo "    .claude/.wise-mode"
            echo "    .claude/.terse-mode"
            echo "    .claude/flow/"

            # Committing .claude/ to share skills is common, and the log files
            # land inside it. Once they are tracked, .gitignore does nothing —
            # the advice above leaves them committed and the warning never clears.
            if git -C "${PROJECT_ROOT}" ls-files --error-unmatch ".claude/log" \
                >/dev/null 2>&1; then
                warn "Some logs are ALREADY TRACKED — .gitignore will not stop them."
                warn "Untrack them first (history still needs separate cleanup):"
                echo "    git rm -r --cached .claude/log"
            fi
        fi
    fi
}

# Run everything inside main() to guard against partial downloads
main "$@"
