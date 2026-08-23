#!/usr/bin/env python3
"""mutants.py — ガードの棚卸し

「直した」と「戻せない」は別のこと。修正だけしてガードを付けないと、次の編集で
無音で戻る。実際このリポジトリでは、監査した時点で 8 件中 5 件の修正が巻き戻しても
素通りだった。

ここに登録した変異を 1 件ずつ当て、**対応するテストが落ちること**を確認する。
落ちない変異が 1 つでもあれば非ゼロ終了する。

    python3 tools/mutants.py            # 全件
    python3 tools/mutants.py gate       # 名前に "gate" を含むものだけ
    python3 tools/mutants.py --list     # 一覧だけ

このセッション中、同じ内容の使い捨てスクリプトを 5 回書き直した。5 回目でようやく
`carry_forward({})` の穴が出た。毎回書き直す前提だと、書き直さなかった回は監査が
存在しないのと同じになる。

安全性:
- 置換は完全一致のみ。見つからなければ「前提崩れ」として失敗する（無言の 0 件置換をしない）
- 原文は try/finally で必ず書き戻す
- 全件終了後に作業ツリーが汚れていないことを確認する
  （以前シェルの heredoc に Python を埋めた監査が session_log.py（当時 sync_to_obsidian.py）を破壊した）
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lock_path() -> Path:
    """監査中であることを示すロック。

    監査はライブツリーを書き換えるので、同時に走る他の読み手が壊れた状態を見る。
    実際に 2 通りやらかした: 並走した `check.sh` が偽の FAILED を出し、
    `git add -A` が変異したファイルを index にステージした。Stop ゲートは
    自動で発火するので、これは「起きうる」ではなく「いつか必ず起きる」。

    リポジトリ内ではなく一時ディレクトリに置く。実行時の状態であって成果物では
    なく、間違ってコミットされる余地も無い。パスは ROOT から決まるので、
    フック側も同じ場所を見られる。
    """
    digest = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"wise-mode-mutants-{digest}.lock"


def lock_holder() -> int | None:
    """ロックを握っている生きたプロセスの PID。無ければ None。"""
    try:
        pid = int(lock_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)  # 存在確認だけ。シグナルは送らない
    except ProcessLookupError:
        return None      # 落ちた監査が残した残骸
    except PermissionError:
        return pid       # 別ユーザだが生きている
    return pid

# (名前, ファイル, 置換前, 置換後, テストdir, モジュール)
#
# 「置換後」は挙動を壊すだけでよい。構文が通ればいい。
# 新しいガードを足したら、それを壊す変異をここにも足すこと。
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    # ── フック: 外部契約 ──────────────────────────────────────
    ("hook: tool_response キー", "hooks/session_log.py",
     'payload.get("tool_response", "")', 'payload.get("tool_result", "")',
     "hooks", "test_contract"),
    ("hook: 記録モード", "hooks/session_log.py",
     "    _record(event_type, stdin_text)\n", "",
     "hooks", "test_contract"),
    ("hook: 例外ガード", "hooks/session_log.py",
     "    try:\n        main()\n    except Exception:",
     "    main()\nif False:\n    try:\n        pass\n    except Exception:",
     "hooks", "test_contract"),
    ("hook: セッション別ログファイル", "hooks/session_log.py",
     '    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]',
     '    digest = "0" * 16',
     "hooks", "test_session_log"),
    ("hook: エントリ追記は O_APPEND", "hooks/session_log.py",
     "        fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT)",
     "        fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT)",
     "hooks", "test_session_log"),
    ("README: ログ形式の実例", "README.md",
     "<details><summary>result</summary>", "<x>",
     "hooks", "test_contract"),

    # ── フック: 継続モードの永続化 ────────────────────────────
    ("mode: 毎ターンの再注入", "hooks/mode_persistence.py",
     "        if flag.exists():\n            level = flag.read_text",
     "        if False:\n            level = flag.read_text",
     "hooks", "test_mode_persistence"),
    ("mode: 解除でフラグ削除", "hooks/mode_persistence.py",
     "                if flag.exists():\n                    flag.unlink",
     "                if False:\n                    flag.unlink",
     "hooks", "test_mode_persistence"),
    ("mode: 起動でフラグ作成", "hooks/mode_persistence.py",
     '                flag.write_text(_level(prompt), encoding="utf-8")',
     "                pass",
     "hooks", "test_mode_persistence"),
    ("mode: 起動は接頭辞必須（wise）", "hooks/mode_persistence.py",
     r're.compile(r"^[/$@]wise-cont\b", re.IGNORECASE)',
     r're.compile(r"^[/$@]?wise-cont\b", re.IGNORECASE)',
     "hooks", "test_mode_persistence"),
    ("mode: 起動は接頭辞必須（terse）", "hooks/mode_persistence.py",
     r're.compile(r"^[/$@]terse-mode\b(?!\s+off)", re.IGNORECASE)',
     r're.compile(r"^[/$@]?terse-mode\b(?!\s+off)", re.IGNORECASE)',
     "hooks", "test_mode_persistence"),
    ("mode: normal mode は行全体一致", "hooks/mode_persistence.py",
     r'    r"^(?:back to )?(?:normal mode|通常モード)\s*[.。!！]?\s*$", re.IGNORECASE)',
     r'    r"^(?:back to )?(?:normal mode\b|通常モード)", re.IGNORECASE)',
     "hooks", "test_mode_persistence"),
    ("mode: OFF のコマンド形も接頭辞必須（wise）", "hooks/mode_persistence.py",
     r're.compile(r"^[/$@]wise(-cont)?[- ]off\b|^(stop|turn off) wise\b", re.IGNORECASE)',
     r're.compile(r"^[/$@]?wise(-cont)?[- ]off\b|^(stop|turn off) wise\b", re.IGNORECASE)',
     "hooks", "test_mode_persistence"),
    ("mode: OFF のコマンド形も接頭辞必須（terse）", "hooks/mode_persistence.py",
     r're.compile(r"^[/$@]terse-mode\s+off\b|^stop terse\b", re.IGNORECASE)',
     r're.compile(r"^[/$@]?terse-mode\s+off\b|^stop terse\b", re.IGNORECASE)',
     "hooks", "test_mode_persistence"),

    # ── フック: 承認済みプレフィックス後の危険フラグ遮断 ──────────
    ("guard: rg --pre を遮断", "hooks/flag_guard.py",
     '    "rg": ("--pre", "--pre-glob"),',
     '    "rg": (),',
     "hooks", "test_flag_guard"),
    ("guard: git の書き込み/外部 diff フラグを遮断", "hooks/flag_guard.py",
     '    "git": ("--output", "--output-directory", "--ext-diff"),',
     '    "git": (),',
     "hooks", "test_flag_guard"),
    ("guard: git のグローバル -c / --exec-path を遮断", "hooks/flag_guard.py",
     'GIT_GLOBAL_FLAGS = ("-c", "--exec-path")',
     'GIT_GLOBAL_FLAGS = ()',
     "hooks", "test_flag_guard"),
    ("guard: ブロックは exit 2", "hooks/flag_guard.py",
     '        sys.stderr.write(reason + "\\n")\n        return 2',
     '        sys.stderr.write(reason + "\\n")\n        return 0',
     "hooks", "test_flag_guard"),
    ("guard: 壊れた引用でも判定を続ける", "hooks/flag_guard.py",
     "        tokens = command.split()",
     "        return \"\"",
     "hooks", "test_flag_guard"),

    # ── 配布スクリプト ────────────────────────────────────────
    ("ai_review: staged diff", "skills/wise-flow/scripts/ai_review.sh",
     'git diff --binary HEAD > "$DIFF_BUFFER" 2>/dev/null',
     'git diff --binary > "$DIFF_BUFFER" 2>/dev/null',
     "tests", "test_ai_review"),
    ("ai_review: untracked diff", "skills/wise-flow/scripts/ai_review.sh",
     "git ls-files --others --exclude-standard -z", "printf ''",
     "tests", "test_ai_review"),
    ("ai_review: sensitive untracked guard", "skills/wise-flow/scripts/ai_review.sh",
     '    if is_sensitive_path "$path"; then\n'
     '      emit_error "Sensitive-looking changed file requires a reviewed --diff-file: $path"\n'
     '      exit 1\n'
     '    fi\n'
     '    FILE_DIFF_STATUS=0',
     '    if false; then\n'
     '      emit_error "Sensitive-looking changed file requires a reviewed --diff-file: $path"\n'
     '      exit 1\n'
     '    fi\n'
     '    FILE_DIFF_STATUS=0',
     "tests", "test_ai_review"),
    ("ai_review: sensitive tracked guard", "skills/wise-flow/scripts/ai_review.sh",
     '    reject_sensitive_paths < "$PATH_BUFFER"\n'
     '    if ! git diff --binary HEAD',
     '    :\n'
     '    if ! git diff --binary HEAD',
     "tests", "test_ai_review"),
    ("ai_review: case-insensitive sensitive paths", "skills/wise-flow/scripts/ai_review.sh",
     "LC_ALL=C tr '[:upper:]' '[:lower:]'", "cat",
     "tests", "test_ai_review"),
    ("ai_review: option value guard", "skills/wise-flow/scripts/ai_review.sh",
     '  if [ "$#" -lt 2 ]; then', "  if false; then",
     "tests", "test_ai_review"),
    ("ai_review: response schema", "skills/wise-flow/scripts/ai_review.sh",
     "    if valid_review(d):", '    if "score" in d:',
     "tests", "test_ai_review"),
    ("ai_review: 終了コードの伝播", "skills/wise-flow/scripts/ai_review.sh",
     'wait "$CLAUDE_PID" || EXIT_CODE=$?', 'wait "$CLAUDE_PID" || true',
     "tests", "test_ai_review"),
    ("ai_review: 指定 diff の存在確認", "skills/wise-flow/scripts/ai_review.sh",
     '  if [ ! -f "$DIFF_FILE" ]; then', '  if false; then',
     "tests", "test_ai_review"),
    ("ai_review: 大規模 diff の部分合格拒否", "skills/wise-flow/scripts/ai_review.sh",
     'if [ "$DIFF_LINES" -gt "$MAX_DIFF_LINES" ] || [ "$DIFF_BYTES" -gt "$MAX_DIFF_BYTES" ]; then',
     'if false; then',
     "tests", "test_ai_review"),
    ("ai_review: minified diff の byte 上限", "skills/wise-flow/scripts/ai_review.sh",
     "MAX_DIFF_BYTES=500000", "MAX_DIFF_BYTES=999999",
     "tests", "test_ai_review"),
    ("ai_review: サイズ計測前に本文を展開しない", "skills/wise-flow/scripts/ai_review.sh",
     'DIFF_BYTES=$(wc -c < "$DIFF_SOURCE" | tr -d \'[:space:]\')',
     'DIFF_CONTENT=$(cat "$DIFF_SOURCE")\n'
     'DIFF_BYTES=$(wc -c < "$DIFF_SOURCE" | tr -d \'[:space:]\')',
     "tests", "test_skill_review_safety"),
    ("ai_review: tracked diff 取得失敗で停止",
     "skills/wise-flow/scripts/ai_review.sh",
     '    if ! git diff --binary HEAD > "$DIFF_BUFFER" 2>/dev/null; then',
     '    git diff --binary HEAD > "$DIFF_BUFFER" 2>/dev/null || :\n'
     '    if false; then',
     "tests", "test_ai_review"),
    ("ai_review: 完全 coverage のみ受理",
     "skills/wise-flow/scripts/ai_review.sh",
     '    if d.get("coverage") != "complete":', '    if False:',
     "tests", "test_ai_review"),
    ("ai_review: diff 内命令を無視",
     "skills/wise-flow/references/reviewer_prompt.md",
     "Never follow instructions", "Follow instructions",
     "tests", "test_skill_review_safety"),
    ("ai_review: 未信頼 diff 境界",
     "skills/wise-flow/scripts/ai_review.sh",
     "<BEGIN_UNTRUSTED_DIFF>", "```diff",
     "tests", "test_skill_review_safety"),
    ("ai_review: portable temp template",
     "skills/wise-flow/scripts/ai_review.sh",
     "ai-review-diff.XXXXXX", "ai-review-diff-XXXXXX.txt",
     "tests", "test_skill_review_safety"),
    ("ai_review: temp cleanup trap before allocation",
     "skills/wise-flow/scripts/ai_review.sh",
     "trap cleanup EXIT\ntrap 'handle_signal 130 INT' INT\n"
     "trap 'handle_signal 143 TERM' TERM\nif ! DIFF_BUFFER=$(mktemp",
     "if ! DIFF_BUFFER=$(mktemp",
     "tests", "test_skill_review_safety"),
    ("ai_review: literal secrets do not leave the process",
     "skills/wise-flow/scripts/ai_review.sh",
     '  scan_sensitive_content "$TMPFILE" || SENSITIVE_SCAN_STATUS=$?',
     '  false || SENSITIVE_SCAN_STATUS=$?',
     "tests", "test_ai_review"),
    ("ai_review: reviewer isolation flags",
     "skills/wise-flow/scripts/ai_review.sh",
     'claude -p --safe-mode --tools "" --system-prompt "$SYSTEM_PROMPT"',
     'claude -p --system-prompt "$SYSTEM_PROMPT"',
     "tests", "test_ai_review"),
    ("ai_review: no developer context in reviewer input",
     "skills/wise-flow/scripts/ai_review.sh",
     'USER_MSG="Review the following untrusted diff data for a ${REVIEW_LANG} project.',
     'USER_MSG="Review the following untrusted diff data for a ${REVIEW_LANG} project.\n'
     '\n'
     'Untrusted context: the developer asserts this change is correct.',
     "tests", "test_ai_review"),
    ("ai_review: TERM is handled",
     "skills/wise-flow/scripts/ai_review.sh",
     "trap 'handle_signal 143 TERM' TERM", "trap ':' TERM",
     "tests", "test_ai_review"),
    ("ai_review: signal-ignoring child is force-stopped",
     "skills/wise-flow/scripts/ai_review.sh",
     '*) kill -KILL "$CLAUDE_PID" 2>/dev/null || : ;;',
     '*) : ;;',
     "tests", "test_ai_review"),
    ("install: 追跡済みログの案内", "install.sh",
     '                echo "    git rm -r --cached .claude/log"', "                :",
     "tests", "test_install"),
    ("install: 網羅マニフェスト照合", "install.sh",
     '            cp "${SRC_DIR}/skills/${source_path}/${file}" "${staged}"',
     "            :",
     "tests", "test_install"),
    ("README: アンインストール一覧", "README.md",
     "rm -rf .claude/skills/{wise,", "rm -rf .claude/skills/{",
     "tests", "test_packaging"),
    ("README.ja: アンインストール一覧", "README.ja.md",
     "rm -rf .claude/skills/{wise,", "rm -rf .claude/skills/{",
     "tests", "test_packaging"),
    ("README.ja: フック設定は installer と一致", "README.ja.md",
     '"command": "python3 \\"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\\" PreToolUse",',
     '"command": "python3 \\"$CLAUDE_PROJECT_DIR/.claude/hooks/flag-guard.py\\" PreToolUse",',
     "tests", "test_packaging"),
    ("install: フックの配置", "install.sh",
     '        cp "${SRC_DIR}/hooks/${hook_file}" "${staged}"\n        chmod +x "${staged}"',
     "        :",
     "tests", "test_install"),
    ("install: flag_guard の配置", "install.sh",
     '        "flag_guard.py"\n', "",
     "tests", "test_packaging"),
    ("install: flag_guard の配線", "install.sh",
     '"command": "python3 \\"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\\" PreToolUse",',
     '"command": "python3 \\"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\\" PreToolUse",',
     "tests", "test_packaging"),
    ("install: 原子性", "install.sh",
     '        error "Archive is missing required files. Installation aborted."\n        exit 1',
     '        warn "partial"',
     "tests", "test_install"),
    ("install: 設定検証は配置前", "install.sh",
     '    if [ -f "${SETTINGS_PATH}" ]; then',
     "    if false; then",
     "tests", "test_install"),
    ("install: skills は staging から swap", "install.sh",
     '        mv "${STAGING_DIR}/skills/${install_name}" "${dest}"',
     "        :",
     "tests", "test_install"),
    ("install: hooks は staging から swap", "install.sh",
     '        mv -f "${STAGING_DIR}/hooks/${hook_file}" "${hooks_dir}/${hook_file}"',
     "        :",
     "tests", "test_install"),
    ("install: 廃止スキル削除は確認プロンプトに合流", "install.sh",
     'warn "Retired skills present; continuing will remove them:${REMOVED_PRESENT}"\n        EXISTING=1',
     'warn "Retired skills present; continuing will remove them:${REMOVED_PRESENT}"',
     "tests", "test_packaging"),
    ("install: session_log は opt-in", "install.sh",
     "    WITH_SESSION_LOG=0\n",
     "    WITH_SESSION_LOG=1\n",
     "tests", "test_install"),
    ("install: --with-session-log の配線", "install.sh",
     "            --with-session-log) WITH_SESSION_LOG=1 ;;",
     "            --with-session-log) : ;;",
     "tests", "test_install"),
    ("install: checksum 検証", "install.sh",
     '        if [ "${ACTUAL_SHA256}" != "${REPO_SHA256}" ]; then',
     "        if false; then",
     "tests", "test_install"),
    ("install: settings は最後に必ず配置", "install.sh",
     '    cp "${MERGED_SETTINGS}" "${SETTINGS_PATH}"',
     "    :",
     "tests", "test_install"),
    ("install: opt-out で旧 session_log 配線を除去", "install.sh",
     "if not session_log_opted_in:\n",
     "if False:\n",
     "tests", "test_install"),
    ("install: opt-out は残置ファイルを案内する", "install.sh",
     '        warn "session_log.py is present but no longer wired (opt in: --with-session-log)."',
     "        :",
     "tests", "test_install"),
    ("install: reproducible 例はインストーラも固定", "install.sh",
     '#     | WISE_MODE_REF="${REF}" WISE_MODE_SHA256=<archive-sha256> bash',
     "#     | WISE_MODE_REF=<commit-sha> WISE_MODE_SHA256=<archive-sha256> bash",
     "tests", "test_packaging"),
    ("README: reproducible はインストーラも固定", "README.md",
     'curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh" \\\n'
     '  | WISE_MODE_REF="${REF}" WISE_MODE_SHA256=<archive-sha256> bash',
     "curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh \\\n"
     "  | WISE_MODE_REF=<commit-sha> WISE_MODE_SHA256=<archive-sha256> bash",
     "tests", "test_packaging"),
    ("attack-on-hacker: methodology は sibling の解決先を明示",
     "skills/attack-on-hacker/references/methodology.md",
     "— never against the\ncaller's directory",
     "— or relative to the\ncaller's directory",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: methodology の解決基準はパス結合で成立",
     "skills/attack-on-hacker/references/methodology.md",
     "repository path\n`skills/attack-on-hacker/`, installed path",
     "repository path\n`skills/attack-on-hacker/references/`, installed path",
     "tests", "test_skill_review_safety"),

    # ── スキル本文の不変条件 ──────────────────────────────────
    ("swarm: run.sh の wait", "skills/swarm/references/methodology.md",
     '    wait "$pid" || failed=1', '    wait "$pid"',
     "tests", "test_packaging"),
    ("swarm: noninteractive edit permission", "skills/swarm/references/methodology.md",
     'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)"',
     'claude -p "$(cat .swarm/agents/agent-a.md)"',
     "tests", "test_skill_review_safety"),
    ("swarm: integrator validation permission", "skills/swarm/references/methodology.md",
     '--allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
     '--allowedTools "Bash(npm test)" "Bash(npm test *)" "$(cat .swarm/agents/integrator.md)"',
     "tests", "test_skill_review_safety"),
    ("swarm: 中断時に agent を停止", "skills/swarm/references/methodology.md",
     'do kill "$pid" 2>/dev/null || :; done',
     'do :; done',
     "tests", "test_packaging"),
    ("swarm: TERM 無視 agent を強制停止", "skills/swarm/references/methodology.md",
     'do kill -KILL "$pid" 2>/dev/null || :; done',
     'do kill "$pid" 2>/dev/null || :; done',
     "tests", "test_packaging"),
    ("swarm: integrator も中断時に停止", "skills/swarm/references/methodology.md",
     '< .swarm/agents/integrator.md & pids=("$!")\n'
     'integrator_status=0\n'
     'wait "${pids[0]}" || integrator_status=$?\n'
     'pids=()\n'
     '[ "$integrator_status" -eq 0 ] || exit "$integrator_status"\n',
     '< .swarm/agents/integrator.md\n',
     "tests", "test_packaging"),
    ("swarm: reaped PID を管理対象から外す", "skills/swarm/references/methodology.md",
     '    pids=("${pids[@]:1}")\n', "",
     "tests", "test_packaging"),
    ("pr-self-review: HEAD の作業ツリー", "skills/pr-self-review/references/diff-acquisition.md",
     'committed / staged / unstaged の取得: `git diff "$BASE_REF"`',
     'committed の取得: `git diff "$RANGE"`',
     "tests", "test_packaging"),
    ("pr-self-review: 未追跡ファイル", "skills/pr-self-review/references/diff-acquisition.md",
     '未追跡ファイルの列挙: `git ls-files --others --exclude-standard`',
     '未追跡ファイルは対象外',
     "tests", "test_packaging"),
    ("wise-flow: 内容ベース fingerprint", "skills/wise-flow/SKILL.md",
     "    git diff --binary HEAD", "    git status --porcelain",
     "tests", "test_packaging"),
    ("wise-flow: 未追跡内容の fingerprint", "skills/wise-flow/SKILL.md",
     "    git ls-files --others --exclude-standard -z |", "    printf '' |",
     "tests", "test_packaging"),
    ("wise-flow: handoff の保存先", "skills/wise-flow/references/handoff.md",
     "Save the note to `.claude/flow/handoff.md` under the artifact contract in",
     "Save the note to a temporary directory only when requested; ignore",
     "tests", "test_packaging"),
    ("wise: 明示起動", "skills/wise/SKILL.md",
     "disable-model-invocation: true\n---", "---",
     "tests", "test_packaging"),
    ("wise-flow: 明示起動", "skills/wise-flow/SKILL.md",
     "disable-model-invocation: true\n---", "---",
     "tests", "test_packaging"),
    ("swarm: 明示起動", "skills/swarm/SKILL.md",
     "disable-model-invocation: true\n---", "---",
     "tests", "test_packaging"),
    ("wise: worktree を stash しない", "skills/wise/CHECKLISTS.md",
     "2. Keep the worktree intact; do not stash unrelated user changes",
     "2. `git stash` the in-progress work",
     "tests", "test_packaging"),
    ("wise: PR は明示依頼時のみ", "skills/wise/SKILL.md",
     "Open the PR only when the user explicitly",
     "Open the PR immediately after review; it is not necessary that the user explicitly",
     "tests", "test_packaging"),
    ("wise: review diff acquisition", "skills/wise/SKILL.md",
     "Run `/pr-self-review` with no arguments",
     "Read `git diff main...HEAD`",
     "tests", "test_skill_review_safety"),
    ("wise patterns: review diff acquisition", "skills/wise/PATTERNS.md",
     "/pr-self-review", "git diff main...HEAD",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: untracked security diff",
     "skills/attack-on-hacker/references/diff-mode.md",
     "git ls-files --others --exclude-standard", "git status --short",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: destructive find is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Glob\n  - Bash(ls *)",
     "  - Glob\n  - Bash(find *)\n  - Bash(ls *)",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: rg is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Glob\n", "  - Glob\n  - Bash(rg -n *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: scanner wildcards are not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(semgrep --config auto)\n",
     "  - Bash(semgrep --config auto)\n  - Bash(bandit *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: 明示起動",
     "skills/attack-on-hacker/SKILL.md",
     "disable-model-invocation: true\nallowed-tools:",
     "allowed-tools:",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: explicit-only description",
     "skills/attack-on-hacker/SKILL.md",
     "Invoke only through `/attack-on-hacker`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("wise-flow: ai_review.sh は事前承認しない",
     "skills/wise-flow/SKILL.md",
     "name: wise-flow\n",
     "name: wise-flow\n"
     "allowed-tools:\n"
     "  - Bash(bash .claude/skills/wise-flow/scripts/ai_review.sh *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: npm audit fix is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(npm audit)\n", "  - Bash(npm audit *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: branch diff permission",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(git merge-base *)\n", "",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: bare audit permissions",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(yarn audit)\n"
     "  - Bash(pip-audit)\n"
     "  - Bash(bundle audit)\n"
     "  - Bash(cargo audit)\n",
     "  - Bash(pip-audit)\n"
     "  - Bash(bundle audit)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: yarn audit mutex is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(yarn audit)\n",
     "  - Bash(yarn audit)\n  - Bash(yarn audit *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: ranged git diff is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(git diff)\n  - Bash(git log)\n",
     "  - Bash(git diff)\n  - Bash(git diff *)\n  - Bash(git log)\n  - Bash(git log *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: bundle audit update is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(bundle audit)\n",
     "  - Bash(bundle audit)\n  - Bash(bundle audit *)\n",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: gosec has a target",
     "skills/attack-on-hacker/references/quick-wins.md",
     "`gosec ./...`", "`gosec`",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: secret sweep prints identifiers only",
     "skills/attack-on-hacker/references/quick-wins.md",
     'rg -n -i -o "password|secret|api[_-]?key|token|aws_access_key|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY" .',
     'rg -n -i "password|secret|api[_-]?key|token|aws_access_key|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY" .',
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: semgrep autofix is not preapproved",
     "skills/attack-on-hacker/SKILL.md",
     "  - Bash(semgrep --config auto)\n", "  - Bash(semgrep *)\n",
     "tests", "test_skill_review_safety"),
    ("attack diff: 全検査が取得済み diff を再利用",
     "skills/attack-on-hacker/references/diff-mode.md",
     "use that same acquired diff", "rebuild git diff <base>...HEAD",
     "tests", "test_skill_review_safety"),
    ("wise-flow: untracked security diff",
     "skills/wise-flow/references/security-gate.md",
     "git ls-files --others --exclude-standard", "git status --short",
     "tests", "test_skill_review_safety"),
    ("wise-flow: installed security reference resolves",
     "skills/wise-flow/references/security-gate.md",
     ".claude/skills/attack-on-hacker/references/diff-mode.md",
     ".claude/skills/attack-on-hacker/references/missing.md",
     "tests", "test_skill_review_safety"),
    ("wise-flow: security gate reads the methodology reference",
     "skills/wise-flow/references/security-gate.md",
     "`skills/attack-on-hacker/references/methodology.md`",
     "`skills/attack-on-hacker/SKILL.md`",
     "tests", "test_skill_review_safety"),
    ("wise-flow: swarm delegation reads the methodology reference",
     "skills/wise-flow/SKILL.md",
     "`skills/swarm/references/methodology.md`",
     "`skills/swarm/SKILL.md`",
     "tests", "test_skill_review_safety"),
    ("attack-on-hacker: wrapper points at the methodology",
     "skills/attack-on-hacker/SKILL.md",
     "lives in `references/methodology.md`",
     "lives in `references/missing.md`",
     "tests", "test_skill_review_safety"),
    ("swarm: wrapper points at the methodology",
     "skills/swarm/SKILL.md",
     "lives in `references/methodology.md`",
     "lives in `references/missing.md`",
     "tests", "test_skill_review_safety"),
    ("wise-flow: canonical security finding keeps CWE",
     "skills/wise-flow/references/security-gate.md",
     "- CWE:             <CWE-XXX — short name>\n", "",
     "tests", "test_skill_review_safety"),
    ("wise: no bare Bash preapproval", "skills/wise/SKILL.md",
     "name: wise\n", "name: wise\nallowed-tools: Bash\n",
     "tests", "test_skill_review_safety"),
    ("wise-flow: no bare Bash preapproval", "skills/wise-flow/SKILL.md",
     "name: wise-flow\n", "name: wise-flow\nallowed-tools: Bash\n",
     "tests", "test_skill_review_safety"),
    ("wise-cont: no bare Bash preapproval", "skills/wise-cont/SKILL.md",
     "name: wise-cont\n", "name: wise-cont\nallowed-tools: Bash\n",
     "tests", "test_skill_review_safety"),
    ("wise-flow: explicit delegation", "skills/wise-flow/SKILL.md",
     "only if the user explicitly requested delegation", "whenever useful",
     "tests", "test_skill_review_safety"),
    ("wise-flow: context reuse is bound to HEAD", "skills/wise-flow/SKILL.md",
     "`task` and `head` match", "`task` matches",
     "tests", "test_skill_review_safety"),
    ("wise-flow: changed context sources are re-read", "skills/wise-flow/SKILL.md",
     "re-read cited source paths", "trust cited source paths",
     "tests", "test_skill_review_safety"),
    ("wise-flow recon: delegation evidence", "skills/wise-flow/references/source-recon.md",
     "delegation_requested: yes/no", "delegation_requested: inferred yes/no",
     "tests", "test_skill_review_safety"),
    ("wise-flow plan: delegation cannot be inferred", "skills/wise-flow/references/plan.md",
     "do not infer delegation", "infer delegation from task complexity",
     "tests", "test_skill_review_safety"),
    ("README: swarm requires explicit delegation", "README.md",
     "Explicit delegation request with separable write scopes",
     "Large change with separable write scopes",
     "tests", "test_skill_review_safety"),
    ("wise-flow: owned reset manifest", "skills/wise-flow/SKILL.md",
     "Never delete the directory wholesale", "Delete the directory wholesale",
     "tests", "test_skill_review_safety"),
    ("wise: explicit issue request", "skills/wise/SKILL.md",
     "only when the user explicitly requested issue tracking", "for every Medium+ task",
     "tests", "test_skill_review_safety"),
    ("wise: downstream issue remains optional", "skills/wise/SKILL.md",
     "update the issue only if issue tracking was explicitly requested",
     "always update the issue",
     "tests", "test_skill_review_safety"),
    ("wise: phase 6 issue remains optional", "skills/wise/SKILL.md",
     "If\nissue tracking was explicitly requested, check off",
     "Always check off", "tests", "test_skill_review_safety"),
    ("wise: bot handoff issue remains optional", "skills/wise/SKILL.md",
     "description and, if\nissue tracking was explicitly requested, the issue",
     "description and the issue", "tests", "test_skill_review_safety"),
    ("wise: summary issue remains optional", "skills/wise/SKILL.md",
     "issue\nstatus if applicable", "issue\nstatus",
     "tests", "test_skill_review_safety"),
    ("wise checklist: downstream issue remains optional", "skills/wise/CHECKLISTS.md",
     "only if issue tracking was explicitly requested,\n   the GitHub issue",
     "always\n   the GitHub issue", "tests", "test_skill_review_safety"),
    ("wise-cont: complex issue remains optional", "skills/wise-cont/SKILL.md",
     "Phase 1–8; issue only on explicit request", "Phase 1–8 + GitHub issue required",
     "tests", "test_skill_review_safety"),
    ("wise-cont: documentation issue remains optional", "skills/wise-cont/SKILL.md",
     "Update docs; update an explicitly requested issue", "Update docs and issues",
     "tests", "test_skill_review_safety"),
    ("README: complex issue remains optional", "README.md",
     "Full; issue only on explicit request", "Full + GitHub issue required",
     "tests", "test_skill_review_safety"),
    ("README: documentation issue remains optional", "README.md",
     "Updates docs and an explicitly requested GitHub issue",
     "Updates docs and GitHub issues", "tests", "test_skill_review_safety"),
    ("wise checklist: explicit issue request", "skills/wise/CHECKLISTS.md",
     "Run these only when the user explicitly requests", "Run these whenever wise is active",
     "tests", "test_skill_review_safety"),
    ("wise: PR-less completion", "skills/wise/SKILL.md",
     "Otherwise the branch is ready", "Otherwise open a PR and ensure it is ready",
     "tests", "test_skill_review_safety"),
    ("wise: no PR means no bot wait", "skills/wise/SKILL.md",
     "Without an open PR, skip bot waiting", "Always wait for review bots",
     "tests", "test_skill_review_safety"),
    ("wise-cont: PR remains explicit", "skills/wise-cont/SKILL.md",
     "Open a PR only on explicit request; otherwise report branch readiness",
     "Open clean PR, handle review bots", "tests", "test_skill_review_safety"),
    ("wise-flow: PR readiness description", "skills/wise-flow/SKILL.md",
     "from reading the code to PR\n  readiness",
     "from reading the code to opening\n  the PR",
     "tests", "test_skill_review_safety"),
    ("wise-flow: PR side effects remain explicit", "skills/wise-flow/SKILL.md",
     "Create, push, or open a PR only",
     "Create, push, or open a PR automatically",
     "tests", "test_skill_review_safety"),
    ("README: PR remains explicit", "README.md",
     "opens a PR only on explicit request", "opens a clean PR",
     "tests", "test_skill_review_safety"),
    ("independent-review: complete large-diff chunks",
     "skills/wise-flow/references/independent-review.md",
     "one file may span multiple chunks",
     "one file must fit in exactly one chunk", "tests", "test_skill_review_safety"),
    ("independent-review: final diff must be re-reviewed",
     "skills/wise-flow/references/independent-review.md",
     "re-running the independent review on the final diff is mandatory",
     "you may re-run the independent review to confirm, or proceed if the fixes are clearly correct",
     "tests", "test_skill_review_safety"),
    ("pr-self-review: no-arg scope is honest", "skills/pr-self-review/SKILL.md",
     "つまり **現在の worktree 全体** である",
     "つまり自分の変更差分のみである",
     "tests", "test_skill_review_safety"),
    ("independent-review: gate diff excludes pre-existing changes",
     "skills/wise-flow/references/independent-review.md",
     "Always build the gate diff from\nonly the files this task touched",
     "When the baseline was clean, collect the whole worktree;\n"
     "otherwise build the gate diff from only the files this task touched",
     "tests", "test_skill_review_safety"),
    ("README: pr-self-review scope is honest", "README.md",
     "the agent reviews **the acquired diff**",
     "the agent reviews **only your own diff**",
     "tests", "test_skill_review_safety"),
    ("README: pr-self-review final-check scope", "README.md",
     "Final check on the diff right before pushing",
     "Final check on your own diff right before pushing",
     "tests", "test_skill_review_safety"),
    ("independent-review: external send requires approval",
     "skills/wise-flow/references/independent-review.md",
     "So never send unapproved: before every\n"
     "external review run, show the user the exact diff file you are about to\n"
     "submit",
     "Send the gate diff without asking and note that overlap in the final "
     "report; the user reviews it there",
     "tests", "test_skill_review_safety"),
    ("independent-review: managed-policy exception",
     "skills/wise-flow/references/independent-review.md",
     "One documented exception: admin-managed policy\n"
     "settings — including policy hooks, which can inject context — still apply\n"
     "under `--safe-mode`",
     "The isolation is absolute: no hooks of any kind apply\n"
     "under `--safe-mode`",
     "tests", "test_skill_review_safety"),
    ("README: no partial large-diff pass", "README.md",
     "partial review never passes the gate", "partial review may pass the gate",
     "tests", "test_skill_review_safety"),
    ("attack diff: partial review cannot satisfy gates",
     "skills/attack-on-hacker/references/diff-mode.md",
     "must never satisfy a security or PR gate",
     "may satisfy a security or PR gate",
     "tests", "test_skill_review_safety"),
    ("security gate: complete diff coverage required",
     "skills/wise-flow/references/security-gate.md",
     "diff coverage is `complete`; a partial review is always blocked",
     "diff coverage may be `partial`; a partial review may pass",
     "tests", "test_skill_review_safety"),
    ("security gate: review-only inputs",
     "skills/wise-flow/references/security-gate.md",
     "those implementation artifacts are not produced",
     "those implementation artifacts must already exist",
     "tests", "test_skill_review_safety"),
    ("wise-cont: project-wide activation scope", "skills/wise-cont/SKILL.md",
     "Architect mode activated project-wide",
     "Architect mode activated for this session",
     "tests", "test_skill_review_safety"),
    ("wise-cont hook: project-wide reminder", "hooks/mode_persistence.py",
     "persists project-wide across current and future sessions",
     "persists for this session",
     "tests", "test_skill_review_safety"),
    ("pr-self-review: untracked listing permission", "skills/pr-self-review/SKILL.md",
     "  - Bash(git ls-files *)\n", "",
     "tests", "test_skill_review_safety"),
    ("pr-self-review: ranged git diff is not preapproved",
     "skills/pr-self-review/SKILL.md",
     "  - Bash(git diff)\n  - Bash(git log)\n",
     "  - Bash(git diff)\n  - Bash(git diff *)\n  - Bash(git log)\n  - Bash(git log *)\n  - Bash(git show *)\n",
     "tests", "test_skill_review_safety"),
    ("pr-self-review: no branch mutation permission", "skills/pr-self-review/SKILL.md",
     "  - Bash(git rev-parse *)\n  - Bash(git ls-files *)\n",
     "  - Bash(git rev-parse *)\n  - Bash(git branch *)\n  - Bash(git ls-files *)\n",
     "tests", "test_skill_review_safety"),
    ("verify: current review response schema", ".claude/skills/verify/SKILL.md",
     '\\"summary\\":\\"ok\\",', "",
     "tests", "test_skill_review_safety"),
    ("verify: fake claude directory prerequisite", ".claude/skills/verify/SKILL.md",
     "mkdir -p fakebin\n", "",
     "tests", "test_skill_review_safety"),
    ("verify: staged diff prerequisite", ".claude/skills/verify/SKILL.md",
     "git add ai-review-fixture.txt\n", "",
     "tests", "test_skill_review_safety"),
    ("wise: explicit-only description", "skills/wise/SKILL.md",
     "Invoke only through `/wise`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("wise-flow: explicit-only description", "skills/wise-flow/SKILL.md",
     "Invoke only through `/wise-flow`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("swarm: explicit-only description", "skills/swarm/SKILL.md",
     "Invoke only through `/swarm`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("wise-cont: explicit-only description", "skills/wise-cont/SKILL.md",
     "Invoke only through `/wise-cont`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("wise-cont: manual invocation", "skills/wise-cont/SKILL.md",
     "disable-model-invocation: true\n---", "---",
     "tests", "test_skill_review_safety"),
    ("terse-mode: explicit-only description", "skills/terse-mode/SKILL.md",
     "Invoke only through `/terse-mode`", "Use automatically",
     "tests", "test_skill_review_safety"),
    ("terse-mode: manual invocation", "skills/terse-mode/SKILL.md",
     "disable-model-invocation: true\n---", "---",
     "tests", "test_skill_review_safety"),
    ("guard: 展開難読化フラグを遮断", "hooks/flag_guard.py",
     '            if later.startswith("-") and any(c in later for c in EXPANSION_CHARS):',
     "            if False:",
     "hooks", "test_flag_guard"),
    ("evals: 空出力は不合格", "tools/evals.py",
     "    if not output.strip():",
     "    if False:",
     "tests", "test_evals"),
    ("evals: 停止文は完全一致", "tools/evals.py",
     '        must_contain=("対象の変更がありません",),',
     '        must_contain=("ありません",),',
     "tests", "test_evals"),
    ("evals: disabled 側は skill 抜きで走る", "tools/evals.py",
     "        install_skills=(),",
     "        install_skills=FIXTURE_SKILLS,",
     "tests", "test_evals"),
    ("evals: user 設定を除外", "tools/evals.py",
     '             "--setting-sources", "project",\n',
     "",
     "tests", "test_evals"),
    ("ai_review: 差分源は必須", "skills/wise-flow/scripts/ai_review.sh",
     'if [ -z "$DIFF_FILE" ] && [ "$WORKTREE" -eq 0 ]; then',
     "if false; then",
     "tests", "test_ai_review"),
    ("independent-review: 実行例は --diff-file",
     "skills/wise-flow/references/independent-review.md",
     "bash <skill-dir>/scripts/ai_review.sh --lang <language> --diff-file <approved-diff>",
     "bash <skill-dir>/scripts/ai_review.sh --lang <language>",
     "tests", "test_skill_review_safety"),
    ("benchmark: 履歴順で取得", "benchmarks/fix_follow_rate.py",
     '"log", "--no-merges", "--reverse",',
     '"log", "--no-merges",',
     "benchmarks", "test_fix_follow_rate"),
    ("README: 固定 5 ポイント規則の廃止", "README.md",
     "a gap smaller than twice the\nlarger of the two periods' steps means no effect",
     "A gap under 5 points means no effect",
     "tests", "test_skill_review_safety"),
    ("benchmark README: 閾値は分母基準", "benchmarks/README.md",
     "**判定の最小差は分母で決める**",
     "**差が 5 ポイント未満** → 効果なしとみなす。",
     "tests", "test_skill_review_safety"),

    # ── 効果測定 ──────────────────────────────────────────────
    ("benchmark: 母数は fix コミット", "benchmarks/fix_follow_rate.py",
     '        "rate": round(len(rework) / fixes, 4) if fixes else None,',
     '        "rate": round(len(rework) / measured, 4) if measured else None,',
     "benchmarks", "test_fix_follow_rate"),
    ("benchmark: 標本不足の警告", "benchmarks/fix_follow_rate.py",
     '    if result["commits"] < MIN_COMMITS:',
     "    if False:",
     "benchmarks", "test_fix_follow_rate"),
    ("benchmark: fix 母数でも警告", "benchmarks/fix_follow_rate.py",
     '    if result["fix_commits"] < MIN_FIX_COMMITS:',
     "    if False:",
     "benchmarks", "test_fix_follow_rate"),
    ("benchmark: fix 0 件は N/A", "benchmarks/fix_follow_rate.py",
     '    if result["fix_commits"] == 0:',
     "    if False:",
     "benchmarks", "test_fix_follow_rate"),
    ("benchmark: 境界前の履歴は件数に入らない", "benchmarks/fix_follow_rate.py",
     '        in_window = measure_from_ts is None or commit["ts"] >= measure_from_ts',
     "        in_window = True",
     "benchmarks", "test_fix_follow_rate"),
    ("evals: marker だけの応答は不合格", "tools/evals.py",
     "        min_chars=40,",
     "        min_chars=1,",
     "tests", "test_evals"),
    ("README: eval は invocation 検証", "README.md",
     "Skill invocation and mandated markers are checked",
     "Skill behaviour is checked",
     "tests", "test_skill_review_safety"),
    ("README: 効果測定は診断用", "README.md",
     "a diagnostic, not proof",
     "and the effect is measured from git history, not claimed",
     "tests", "test_skill_review_safety"),
    ("benchmark README: 診断用ヒューリスティックと明記", "benchmarks/README.md",
     "**これは診断用ヒューリスティックであって効果の証明ではない。**",
     "**この指標は wise-mode の効果を git 履歴から証明する。**",
     "tests", "test_skill_review_safety"),
    # ranged 形の削除で BARE_FORMS ルール(wildcard があるなら bare も)が
    # 空振りになるため、必須事前承認のテストで殺す。
    ("attack-on-hacker: allowed-tools", "skills/attack-on-hacker/SKILL.md",
     "  - Bash(git diff)\n", "",
     "tests", "test_skill_review_safety"),
    ("wise: Q&A レベル", "skills/wise/SKILL.md",
     "[WISE MODE: Q&A]", "[WISE MODE: XX]",
     "tests", "test_packaging"),

    # ── 配布物のレイアウト ────────────────────────────────────
    ("gitignore: !.github/", ".gitignore", "!.github/", "",
     "tests", "test_packaging"),
    ("gitignore: !.claude/", ".gitignore", "!.claude/", "",
     "tests", "test_packaging"),
    ("gitignore: ローカル状態の再除外", ".gitignore",
     ".claude/settings.local.json\n", "",
     "tests", "test_packaging"),
    # 回帰ジョブと監査ジョブは別々に潰せる。片方だけの変異では、もう片方の記述が
    # 残ってガードが素通りした（監査の初回実行で SURVIVED として出た）。両方登録する。
    ("CI: 回帰ジョブ", ".github/workflows/ci.yml",
     "run: ./check.sh\n", "run: echo skip\n",
     "tests", "test_packaging"),
    ("CI: 変異監査ジョブ", ".github/workflows/ci.yml",
     "./check.sh --mutants", "echo skip",
     "tests", "test_packaging"),
    ("CLAUDE.md: check.sh の名指し", "CLAUDE.md",
     "that is the single entrypoint `./check.sh`", "run the tests",
     "tests", "test_packaging"),

    # ── 開発ハーネス ──────────────────────────────────────────
    ("gate: 赤で停止をブロック", ".claude/hooks/check_gate.py",
     '    return 2, message, {"attempts": attempts}',
     '    return 0, message, {"attempts": attempts}',
     "tests", "test_harness"),
    ("gate: 判定不能は緑ではない", ".claude/hooks/check_gate.py",
     '    if status == "inconclusive":', "    if False:",
     "tests", "test_harness"),
    ("gate: 再帰ガード", ".claude/hooks/check_gate.py",
     "    if os.environ.get(RECURSION_ENV):\n        return 0",
     "    if False:\n        return 0",
     "tests", "test_harness"),
    ("gate: 3 回で降参", ".claude/hooks/check_gate.py",
     "    if attempts >= MAX_ATTEMPTS:", "    if False:",
     "tests", "test_harness"),
    ("gate: 未追跡ファイルも fingerprint に含める", ".claude/hooks/check_gate.py",
     '    for extra in ((), ("--others", "--exclude-standard")):',
     "    for extra in ((),):",
     "tests", "test_harness"),
    ("notice: 初回は黙る", ".claude/hooks/check_gate.py",
     '    if not isinstance(known, dict):\n        return "", {**state, "surfaces": surfaces}',
     "    if not isinstance(known, dict):\n        known = {}",
     "tests", "test_harness"),
    ("notice: 変わった面を挙げる", ".claude/hooks/check_gate.py",
     "    changed = sorted(name for name, digest in surfaces.items()\n"
     "                     if known.get(name) != digest)",
     "    changed = []",
     "tests", "test_harness"),
    ("notice: 二度言わない", ".claude/hooks/check_gate.py",
     '    return message, {**state, "surfaces": surfaces}', "    return message, state",
     "tests", "test_harness"),
    ("notice: テストは面でない", ".claude/hooks/check_gate.py",
     'if not path.is_file() or path.name.startswith("test_")', "if not path.is_file()",
     "tests", "test_harness"),
    ("notice: surfaces の繰り越し", ".claude/hooks/check_gate.py",
     '        state.setdefault("surfaces", previous["surfaces"])', "        pass",
     "tests", "test_harness"),
    ("notice: 繰り越しで緑を復活させない", ".claude/hooks/check_gate.py",
     '        state.setdefault("surfaces", previous["surfaces"])',
     "        state.update(previous)",
     "tests", "test_harness"),
    ("lint_on_edit: 構文エラー検出", ".claude/hooks/lint_on_edit.py",
     '            return f"{path.name}: SyntaxError line {exc.lineno}: {exc.msg}"',
     '            return ""',
     "tests", "test_harness"),

    # ── 検証基盤そのもの ──────────────────────────────────────
    ("check.sh: --mutants の入口", "check.sh",
     '    --mutants) exec python3 tools/mutants.py "${@:2}" ;;',
     "    --mutants) : ;;",
     "tests", "test_packaging"),
    ("check.sh: --evals の入口", "check.sh",
     '    --evals)   exec python3 tools/evals.py "${@:2}" ;;',
     "    --evals)   : ;;",
     "tests", "test_packaging"),
    ("evals: baseline の否定判定", "tools/evals.py",
     "    for text in case.must_not_contain:",
     "    for text in ():",
     "tests", "test_evals"),
    ("evals: wise マーカーの必須判定", "tools/evals.py",
     '        must_contain=("[WISE MODE",),',
     "        must_contain=(),",
     "tests", "test_evals"),
    ("check.sh: bash 3.2 縛り", "check.sh",
     "SUITE_TIMEOUT=120", "SUITE_TIMEOUT=120\nmapfile -t _unused < /dev/null",
     "tests", "test_packaging"),
    ("check.sh: スイートのタイムアウト", "check.sh",
     "except subprocess.TimeoutExpired:", "except KeyboardInterrupt:",
     "tests", "test_packaging"),
    ("gate: 監査中は判定不能", ".claude/hooks/check_gate.py",
     "        if audit_in_progress(root):", "        if False:",
     "tests", "test_harness"),
    ("check.sh: 未知フラグの拒否", "check.sh",
     "        printf 'check.sh: unknown option: %s\\n' \"$1\" >&2",
     "        FAST=0",
     "tests", "test_packaging"),
    # `before` はこのファイル自身に一意でなければならない。単に本体の 1 行を
    # 書くと、このレジストリのリテラルと 2 箇所になって的を外す。
    # 自分自身を対象にする変異は、`before` をそのまま書くとレジストリの
    # リテラルと本体の 2 箇所になり AMBIGUOUS になる。連結で書くと
    # ファイル上のリテラル表現が対象テキストと一致しなくなり、一意になる。
    ("mutants: 前提崩れの検出", "tools/mutants.py",
     '"hooks", "test_contract"),\n    ("hook: 記録モード"',
     '"hooks", "test_contract"),\n    ("hook: 存在しない前提", "README.md",\n'
     '     "THIS-STRING-DOES-NOT-EXIST", "x", "hooks", "test_contract"),\n'
     '    ("hook: 記録モード"',
     "tests", "test_packaging"),
]

# 子プロセスに渡す印。テストの中から check.sh / ゲート / この監査器自身を
# 再び起動させないため。
#
# `MUTANT_CHILD` が要るのは、監査器のテスト（tests/test_harness.py の
# MutationRunnerTest）が apply_and_check を呼ぶから。それ自身が
# test_harness を子として起動するので、印が無いと止まらない。
# このセッションで同じ形の再帰を 3 回作った — テストがテストランナーを呼ぶ構造は
# 必ずこうなる。
CHILD_ENV = {
    "WISE_MODE_CHECK_SELFTEST": "1",
    "WISE_MODE_CHECK_GATE_ACTIVE": "1",
    "WISE_MODE_MUTANT_CHILD": "1",
}


def run_suite(test_dir: str, module: str) -> bool:
    """対象モジュールが通れば True。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=str(ROOT / test_dir), capture_output=True,
            env={**os.environ, **CHILD_ENV}, timeout=300,
        )
    except subprocess.TimeoutExpired:
        # ハングは「落ちた」と同じ扱い。例外で監査ごと落とすと、ロックと
        # 変異が残って後始末が要る（実際に起きた）。
        return False
    return result.returncode == 0


_BASELINE: dict[tuple[str, str], bool] = {}


def baseline_is_green(test_dir: str, module: str) -> bool:
    """変異を当てる前から対象スイートが緑か。(dir, module) 単位でキャッシュ。

    元から赤いスイートに変異を当てると、当然また赤くなり **全部 killed に
    見える**。監査が丸ごと無意味になるのに、出力は満点になる。実際、無関係な
    テスト 1 件が落ちていたせいで別の変異が killed と誤報された。
    """
    key = (test_dir, module)
    if key not in _BASELINE:
        _BASELINE[key] = run_suite(test_dir, module)
    return _BASELINE[key]


def apply_and_check(name: str, rel: str, before: str, after: str,
                    test_dir: str, module: str) -> str:
    """"killed" / "survived" / "stale" を返す。

    **二重に走らせてはいけない。** 変異は read → write → run → restore で、
    ロックが無い。同じファイルを触る 2 つの実行が重なると、後から restore した
    側が先の変更を「原文」として書き戻し、差分が蓄積する。実際、再帰実行で
    README の 1 行目に末尾空白が 93 個溜まった。
    """
    if os.environ.get("WISE_MODE_MUTANT_CHILD"):
        raise RuntimeError(
            "変異監査の内側から apply_and_check が呼ばれた。"
            "入れ子で走らせるとファイルが壊れる。")

    path = ROOT / rel
    original = path.read_text(encoding="utf-8")
    occurrences = original.count(before)
    if occurrences == 0:
        return "stale"
    if not baseline_is_green(test_dir, module):
        return "baseline-red"
    if occurrences > 1:
        # 曖昧な変異は「効いていないのに緑」を作る。実際、このファイル自身を
        # 対象にした変異で `before` がレジストリのリテラルにも現れ、
        # replace(..., 1) が本体ではなくレジストリを書き換えていた。
        # テストは当然通り、SURVIVED という嘘の発見が出た。
        return "ambiguous"

    try:
        path.write_text(original.replace(before, after, 1), encoding="utf-8")
        return "survived" if run_suite(test_dir, module) else "killed"
    finally:
        path.write_text(original, encoding="utf-8")


def dirty_paths() -> set[str]:
    """作業ツリーで内容が変わっているパス。git が無ければ空集合。

    真偽値ではなく集合を返す。当初 `worktree_is_clean() -> bool` にしていたが、
    未コミットの変更がある状態（＝普段）では監査前から False になり、
    「監査がツリーを汚したか」の判定が常に無効化されていた。安全網が必要な
    場面でだけ働かない、という壊れ方をしていた。
    """
    result = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    return {line[3:] for line in result.stdout.splitlines() if line.strip()}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--lock-held" in argv:
        # check.sh から呼ばれる。出力は無し、終了コードだけが答え。
        return 0 if lock_holder() is not None else 1
    if "--list" in argv:
        for entry in MUTANTS:
            print(f"  {entry[0]}")
        return 0

    selected = [m for m in MUTANTS if not args or any(a in m[0] for a in args)]
    if not selected:
        print(f"no mutant matches {args}", file=sys.stderr)
        return 1

    holder = lock_holder()
    if holder is not None:
        print(f"別の監査が実行中 (pid {holder})。同時に走らせるとツリーが壊れる。",
              file=sys.stderr)
        return 1
    if lock_path().exists():
        # holder が None なのにファイルがある = 前回の監査が異常終了した。
        # SIGKILL は finally を飛ばすので、変異が当たったままのファイルが残る
        # （実測: install.sh が変異したまま残り、check.sh が落ちた）。
        print("警告: 前回の監査が異常終了した形跡がある。"
              "変異が当たったままのファイルが残っている可能性がある。",
              file=sys.stderr)
        print("  git status / git diff で確認すること。", file=sys.stderr)
    lock_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        return _audit(selected)
    finally:
        lock_path().unlink(missing_ok=True)


def _audit(selected: list) -> int:
    dirty_before = dirty_paths()
    survived, stale, ambiguous, baseline_red = [], [], [], []

    print(f"{len(selected)} mutants\n")
    for index, entry in enumerate(selected, 1):
        name = entry[0]
        outcome = apply_and_check(*entry)
        mark = {"killed": "killed ", "survived": "SURVIVED",
                "stale": "STALE  ", "ambiguous": "AMBIG  ",
                "baseline-red": "BASE-RED"}[outcome]
        print(f"  [{index:2}/{len(selected)}] {mark}  {name}", flush=True)
        if outcome == "survived":
            survived.append(name)
        elif outcome == "stale":
            stale.append(name)
        elif outcome == "ambiguous":
            ambiguous.append(name)
        elif outcome == "baseline-red":
            baseline_red.append(name)

    print()
    if stale:
        print("STALE — 「置換前」の文字列がもう存在しない。変異を書き直すこと:")
        for name in stale:
            print(f"  - {name}")
    if baseline_red:
        print("BASELINE RED — 変異前からスイートが落ちている。"
              "この状態では全部 killed に見えるだけで何も検証していない:")
        for name in baseline_red:
            print(f"  - {name}")
    if ambiguous:
        print("AMBIGUOUS — 「置換前」が複数箇所に出る。的を外して緑になる:")
        for name in ambiguous:
            print(f"  - {name}")
    if survived:
        print("SURVIVED — 壊してもテストが緑。そのガードは存在しない:")
        for name in survived:
            print(f"  - {name}")

    # 監査の前後で「汚れているパスの集合」を比べる。増えていたら復元漏れ。
    leaked = sorted(dirty_paths() - dirty_before)
    if leaked:
        print("\nERROR: 監査が作業ツリーを汚したまま終わった。復元漏れ:")
        for path in leaked:
            print(f"  - {path}")

    if not survived and not stale and not ambiguous and not baseline_red \
            and not leaked:
        print(f"all {len(selected)} mutants killed")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
