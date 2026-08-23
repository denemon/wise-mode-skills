#!/usr/bin/env bash
# install.sh — Installer for wise-mode Claude Code skills and hooks
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash -s -- --with-session-log
#
# Reproducible install: pin the INSTALLER and the snapshot to the same commit
# (a mutable-main installer against a pinned archive can disagree with the
# archive's manifest), plus optionally the archive checksum:
#   REF=<commit-sha>
#   curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh" \
#     | WISE_MODE_REF="${REF}" WISE_MODE_SHA256=<archive-sha256> bash
#
# The entire script is wrapped in main() so that a partial download
# never executes incomplete code.

main() {
    set -euo pipefail

    # ── Configuration ──────────────────────────────────────────────
    # Single-archive install: exactly one snapshot of the repository is
    # downloaded as a tarball. Fetching files one by one from the mutable
    # main branch could interleave with a push and produce a mixed-version
    # tree; one archive cannot.
    REPO_ARCHIVE_BASE="https://codeload.github.com/den-emon/wise-mode/tar.gz"
    REPO_REF="${WISE_MODE_REF:-main}"
    REPO_SHA256="${WISE_MODE_SHA256:-}"

    # Skills to install: "source_path|install_name|file1,file2,..."
    SKILLS=(
        "terse-mode|terse-mode|SKILL.md"
        "swarm|swarm|SKILL.md,references/methodology.md"
        "wise|wise|SKILL.md,CHECKLISTS.md,PATTERNS.md"
        "wise-cont|wise-cont|SKILL.md"
        "wise-flow|wise-flow|SKILL.md,references/source-recon.md,references/plan.md,references/implement-review.md,references/validate.md,references/security-gate.md,references/independent-review.md,references/reviewer_prompt.md,references/handoff.md,scripts/ai_review.sh"
        "attack-on-hacker|attack-on-hacker|SKILL.md,references/methodology.md,references/diff-mode.md,references/quick-wins.md,references/language-hints.md,references/report-format.md"
        "pr-self-review|pr-self-review|SKILL.md,references/diff-acquisition.md,references/output-format.md"
    )

    # Skills that used to be installed separately and are now phases of another
    # skill. Left in place they keep firing and compete with the new router.
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

    # Hook files installed by default. session_log.py is a deliberate
    # opt-in (--with-session-log): it persists tool input and output to
    # disk on every tool call.
    HOOK_FILES=(
        "mode_persistence.py"
        "flag_guard.py"
    )
    SESSION_LOG_HOOK="session_log.py"

    WITH_SESSION_LOG=0
    for arg in "$@"; do
        case "$arg" in
            --with-session-log) WITH_SESSION_LOG=1 ;;
            *)
                printf '[error] unknown option: %s\n' "$arg" >&2
                exit 1
                ;;
        esac
    done

    INSTALL_HOOKS=("${HOOK_FILES[@]}")
    if [ "${WITH_SESSION_LOG}" -eq 1 ]; then
        INSTALL_HOOKS+=("${SESSION_LOG_HOOK}")
    fi

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
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\" PreToolUse",
                        "timeout": 5
                    }
                ]
            }
        ]
    }'

    # shellcheck disable=SC2016  # same reason as HOOKS_CONFIG.
    SESSION_LOG_HOOKS_CONFIG='{
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

    if ! command -v tar >/dev/null 2>&1; then
        error "tar is required to extract the release archive but was not found."
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

    # ── Validate existing settings BEFORE anything is placed ──────
    # Parsing the settings only after files were already copied is how a
    # broken JSON once aborted the install and left 27 files behind. The
    # structure check mirrors exactly what the merge step dereferences, so a
    # hooks section of the wrong shape fails here with a clear message instead
    # of as a traceback mid-merge.
    SETTINGS_PATH="${PROJECT_ROOT}/.claude/settings.local.json"
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
            error "Fix or remove it first — nothing was installed."
            exit 1
        fi
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
    for hook_file in "${INSTALL_HOOKS[@]}"; do
        if [ -f "${PROJECT_ROOT}/.claude/hooks/${hook_file}" ]; then
            EXISTING=1
            break
        fi
    done

    # Retired skills are deleted on upgrade, but never silently: route their
    # presence into the same consent prompt as the overwrite, so nothing that
    # exists in .claude/ is removed without a yes.
    REMOVED_PRESENT=""
    for removed in "${REMOVED_SKILLS[@]}"; do
        if [ -f "${PROJECT_ROOT}/.claude/skills/${removed}/SKILL.md" ]; then
            REMOVED_PRESENT="${REMOVED_PRESENT} ${removed}"
        fi
    done
    if [ -n "${REMOVED_PRESENT}" ]; then
        warn "Retired skills present; continuing will remove them:${REMOVED_PRESENT}"
        EXISTING=1
    fi

    if [ "${EXISTING}" -eq 1 ]; then
        warn "One or more skills/hooks already exist in .claude/"
        printf "  Overwrite? [y/N] "
        read -r answer </dev/tty
        case "$answer" in
            [yY]|[yY][eE][sS]) : ;;
            *) info "Aborted. Existing installation unchanged."; exit 0 ;;
        esac
    fi

    # ── Download ONE archive snapshot to a temp dir ───────────────
    TMPDIR_DOWNLOAD="$(mktemp -d)"
    # Staging lives inside .claude/ so the final swap is a same-filesystem
    # mv (rename), not a copy. A fixed name lets a rerun clean up leftovers
    # from a killed install.
    STAGING_DIR="${PROJECT_ROOT}/.claude/.install-staging"
    trap 'rm -rf "${TMPDIR_DOWNLOAD}" "${STAGING_DIR}"' EXIT

    ARCHIVE="${TMPDIR_DOWNLOAD}/wise-mode.tar.gz"
    ARCHIVE_URL="${REPO_ARCHIVE_BASE}/${REPO_REF}"
    info "Downloading snapshot ${REPO_REF}..."
    if ! fetch "${ARCHIVE_URL}" > "${ARCHIVE}" 2>/dev/null || [ ! -s "${ARCHIVE}" ]; then
        error "Failed to download ${ARCHIVE_URL}. Installation aborted."
        exit 1
    fi

    if [ -n "${REPO_SHA256}" ]; then
        if ! command -v shasum >/dev/null 2>&1; then
            error "WISE_MODE_SHA256 is set but shasum was not found."
            exit 1
        fi
        # LC_ALL=C: macOS の shasum(Perl)は LC_ALL=C.UTF-8 などの locale を
        # 継承すると panic して終了 9 になる。checksum 計算に locale は不要。
        ACTUAL_SHA256="$(LC_ALL=C shasum -a 256 "${ARCHIVE}" | cut -d' ' -f1)"
        if [ "${ACTUAL_SHA256}" != "${REPO_SHA256}" ]; then
            error "Archive checksum mismatch: expected ${REPO_SHA256}, got ${ACTUAL_SHA256}."
            error "Installation aborted — nothing was installed."
            exit 1
        fi
        ok "Archive checksum verified."
    fi

    EXTRACT_DIR="${TMPDIR_DOWNLOAD}/extracted"
    mkdir -p "${EXTRACT_DIR}"
    if ! tar -xzf "${ARCHIVE}" -C "${EXTRACT_DIR}" 2>/dev/null; then
        error "Failed to extract the archive. Installation aborted."
        exit 1
    fi

    SRC_DIR=""
    for extracted_root in "${EXTRACT_DIR}"/*/; do
        SRC_DIR="${extracted_root%/}"
        break
    done
    if [ -z "${SRC_DIR}" ]; then
        error "Archive extraction produced no directory. Installation aborted."
        exit 1
    fi

    # ── Verify the snapshot against the manifest BEFORE placement ─
    FAIL=0
    for skill_entry in "${SKILLS[@]}"; do
        source_path="${skill_entry%%|*}"
        rest="${skill_entry#*|}"
        skill_files_str="${rest#*|}"
        IFS=',' read -ra skill_files <<< "${skill_files_str}"

        for file in "${skill_files[@]}"; do
            if [ ! -s "${SRC_DIR}/skills/${source_path}/${file}" ]; then
                error "Archive is missing skills/${source_path}/${file}."
                FAIL=1
            fi
        done

        if [ -f "${SRC_DIR}/skills/${source_path}/SKILL.md" ]; then
            if ! head -1 "${SRC_DIR}/skills/${source_path}/SKILL.md" | grep -q "^---"; then
                error "${source_path}/SKILL.md does not look like a valid skill file (missing frontmatter)."
                FAIL=1
            fi
        fi
    done

    for hook_file in "${INSTALL_HOOKS[@]}"; do
        if [ ! -s "${SRC_DIR}/hooks/${hook_file}" ]; then
            error "Archive is missing hooks/${hook_file}."
            FAIL=1
        fi
    done

    if [ "${FAIL}" -ne 0 ]; then
        error "Archive is missing required files. Installation aborted."
        exit 1
    fi

    # ── Compute the merged settings BEFORE placement ──────────────
    MERGED_SETTINGS="${TMPDIR_DOWNLOAD}/settings.local.json"
    python3 -c "
import json, os, sys

settings_path = sys.argv[1]
hooks_config = json.loads(sys.argv[2])
session_log_config = json.loads(sys.argv[3])
session_log_opted_in = sys.argv[4] == '1'
if session_log_opted_in:
    hooks_config.update(session_log_config)
output_path = sys.argv[5]

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
# session_log moved to explicit opt-in. Older installs wired it by default; a
# reinstall without --with-session-log unwires exactly the commands this
# installer itself writes — full-string match against the shipped config, never
# a substring match. A substring match on the file name would also delete
# third-party hooks that merely mention it (a user-owned
# /opt/acme/session_log.py wiring would be lost that way).
if not session_log_opted_in:
    for event, entries in session_log_config.items():
        commands = {
            hook.get('command', '')
            for entry in entries
            for hook in entry.get('hooks', [])
        }
        legacy_commands.setdefault(event, set()).update(commands)

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

with open(output_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')
" "${SETTINGS_PATH}" "${HOOKS_CONFIG}" "${SESSION_LOG_HOOKS_CONFIG}" "${WITH_SESSION_LOG}" "${MERGED_SETTINGS}"

    # ── Stage the complete payload, then swap into place ──────────
    # Copying straight into .claude/ can fail halfway (permissions, disk
    # full) and leave a half-copied skill. Stage everything first — any
    # failure here aborts with .claude/ untouched — then swap one mv per
    # skill/hook, so each unit is either the old version or the new one,
    # never half of each.
    rm -rf "${STAGING_DIR}"
    mkdir -p "${STAGING_DIR}/skills" "${STAGING_DIR}/hooks"

    INSTALLED_FILES=()
    for skill_entry in "${SKILLS[@]}"; do
        source_path="${skill_entry%%|*}"
        rest="${skill_entry#*|}"
        install_name="${rest%%|*}"
        skill_files_str="${rest#*|}"
        IFS=',' read -ra skill_files <<< "${skill_files_str}"

        for file in "${skill_files[@]}"; do
            staged="${STAGING_DIR}/skills/${install_name}/${file}"
            mkdir -p "$(dirname "${staged}")"
            cp "${SRC_DIR}/skills/${source_path}/${file}" "${staged}"
            case "${staged}" in
                *.sh) chmod +x "${staged}" ;;
            esac
            INSTALLED_FILES+=("${PROJECT_ROOT}/.claude/skills/${install_name}/${file}")
        done
    done

    for hook_file in "${INSTALL_HOOKS[@]}"; do
        staged="${STAGING_DIR}/hooks/${hook_file}"
        cp "${SRC_DIR}/hooks/${hook_file}" "${staged}"
        chmod +x "${staged}"
        INSTALLED_FILES+=("${PROJECT_ROOT}/.claude/hooks/${hook_file}")
    done

    # ── Swap skills into place (one mv per skill) ─────────────────
    mkdir -p "${PROJECT_ROOT}/.claude/skills"
    for skill_entry in "${SKILLS[@]}"; do
        rest="${skill_entry#*|}"
        install_name="${rest%%|*}"
        dest="${PROJECT_ROOT}/.claude/skills/${install_name}"
        rm -rf "${dest}"
        mv "${STAGING_DIR}/skills/${install_name}" "${dest}"
    done

    # ── Remove renamed hook file (wise_mode.py -> mode_persistence.py) ──
    rm -f "${PROJECT_ROOT}/.claude/hooks/wise_mode.py"

    # ── Remove skills that were folded into other skills ──────────
    # Consent came from the prompt above: REMOVED_PRESENT forces EXISTING=1.
    for removed in "${REMOVED_SKILLS[@]}"; do
        removed_dir="${PROJECT_ROOT}/.claude/skills/${removed}"
        if [ -f "${removed_dir}/SKILL.md" ]; then
            rm -rf "${removed_dir}"
            info "Removed ${removed} (folded into wise-flow)"
        fi
    done

    # ── Swap hooks into place (one mv per file — an atomic rename) ─
    hooks_dir="${PROJECT_ROOT}/.claude/hooks"
    mkdir -p "${hooks_dir}"
    if [ "${WITH_SESSION_LOG}" -ne 1 ] && [ -f "${hooks_dir}/${SESSION_LOG_HOOK}" ]; then
        # session_log is opt-in now. This reinstall unwires the installer's own
        # session_log commands in the settings merge above, but never deletes
        # the file: a name match cannot prove the installer wrote it, and it
        # may be user-owned or locally modified.
        warn "session_log.py is present but no longer wired (opt in: --with-session-log)."
        # Relative path on purpose: interpolating ${hooks_dir} would hand the
        # user a copy-paste command that splits on a space in the project path.
        warn "Remove the file yourself if unwanted: rm .claude/hooks/${SESSION_LOG_HOOK}"
    fi
    for hook_file in "${INSTALL_HOOKS[@]}"; do
        mv -f "${STAGING_DIR}/hooks/${hook_file}" "${hooks_dir}/${hook_file}"
    done

    rm -rf "${STAGING_DIR}"

    # ── Write the pre-computed settings LAST ──────────────────────
    mkdir -p "$(dirname "${SETTINGS_PATH}")"
    cp "${MERGED_SETTINGS}" "${SETTINGS_PATH}"
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
    echo "    /attack-on-hacker - Adversarial source-code security review"
    echo "    /pr-self-review   - Self code review on own diff before opening a PR"
    echo ""
    if [ "${WITH_SESSION_LOG}" -eq 1 ]; then
        info "Session logs are written to .claude/log/ automatically by the hook."
    else
        info "Session logs hook not installed (opt in: install.sh --with-session-log)."
    fi
    echo ""

    # ── Check: are the session logs actually ignored? ──────────────
    # The PostToolUse hook writes tool input and command output to
    # .claude/log/. Secrets are masked before writing, but the masking is
    # pattern-based, so these files stay sensitive and should not be committed.
    if [ "${WITH_SESSION_LOG}" -eq 1 ] && \
        git -C "${PROJECT_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
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
