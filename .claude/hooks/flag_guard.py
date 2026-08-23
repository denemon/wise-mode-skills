#!/usr/bin/env python3
"""flag_guard.py — PreToolUse フック: 承認済みプレフィックスの後ろの危険フラグを止める

スキルの allowed-tools は接頭辞一致で、フラグを検査できない。
`Bash(rg -n *)` を許可すると `rg -n --pre '<cmd>' pattern`（ファイルごとに
任意コマンド実行）も自動承認される。レビュー系スキルは敵対的でありうる
コード（サードパーティ監査・vendored 依存）を読むので、コード内の prompt
injection がこの形を誘導すると、許可プロンプトなしで任意コマンドが走る。
接頭辞一致では塞げない層なので、ここで機械的に遮断する。

契約（公式 hook-development ドキュメントで確認。check_gate.py と同じ表）:
  exit 0 → ツール呼び出しを許可
  exit 2 → 呼び出しをブロックし、stderr がモデルに差し戻される

判定できない入力は全て素通しする（フェイルオープン）。ただし事前承認済みの
プレフィックスに対しては素通し＝即実行であり、許可プロンプトには戻らない。
さらに公式仕様上 hook の例外や timeout はブロックにならない。したがって
このガードは防御の一層であって権限境界ではない — 「このガード無しでは
危険な形」を allowed-tools で事前承認してはならない。

使い方: python3 flag_guard.py PreToolUse   # stdin に payload JSON
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

# ツール名 -> コマンド中のどこに現れても遮断するフラグ。
# 完全一致か `=` 付き（--output=/path）だけを見る。前方一致にすると
# --prefix のような無関係のフラグを巻き込む。
BLOCKED_FLAGS = {
    "rg": ("--pre", "--pre-glob"),          # ファイルごとに任意コマンド実行
    "git": ("--output", "--output-directory", "--ext-diff"),  # 任意パス書き込み / 外部 diff 実行
    "bandit": ("-o", "--output"),           # 以下はレポートによる任意パス上書き
    "gitleaks": ("-r", "--report-path"),
    "tfsec": ("--out",),
    "checkov": ("--output-file-path",),
    "gosec": ("-out",),
}

# git のグローバルオプション（サブコマンドより前）だけに現れる実行系。
# 位置を見るのは `git log -c`（マージ差分の合成表示）を誤遮断しないため。
# `git -c diff.external=cmd diff` は差分表示のたびに cmd を実行する。
GIT_GLOBAL_FLAGS = ("-c", "--exec-path")

# このガードはシェル展開前の文字列しか見えない。`--out${GAP}put` は字面では
# どのフラグとも一致せず、実行時に --output へ化ける。フラグ字句（`-` で始まる
# トークン）にこれらの文字が残っていたら、安全と判定できないので遮断する。
# 正当なフラグ名にこれらの文字は現れない（展開値は別トークンで渡せる）。
EXPANSION_CHARS = "$`{"


def _message(tool: str, flag: str) -> str:
    hint = (" (the global `git -c key=value` form injects config that can"
            " execute external commands; `git log -c` after the subcommand"
            " is allowed)" if flag == "-c" else "")
    return (
        f"flag_guard: blocked `{flag}` after `{tool}`{hint}. This flag turns "
        "a preapproved read-only command into an execute or write primitive, "
        "so it is intentionally not preapproved. Rerun the command without "
        "this flag, or ask the user to run the exact command themselves."
    )


def blocked(command: str) -> str:
    """遮断理由を返す。安全なら ""。"""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # 引用が壊れていて字句解析できない。見逃すより誤遮断に倒す。
        tokens = command.split()

    for i, token in enumerate(tokens):
        tool = token.rsplit("/", 1)[-1]
        if tool == "git":
            for later in tokens[i + 1:]:
                if not later.startswith("-"):
                    break  # サブコマンド以降
                if later.split("=", 1)[0] in GIT_GLOBAL_FLAGS:
                    return _message("git", later.split("=", 1)[0])
        flags = BLOCKED_FLAGS.get(tool)
        if not flags:
            continue
        for later in tokens[i + 1:]:
            if later.startswith("-") and any(c in later for c in EXPANSION_CHARS):
                return (
                    f"flag_guard: blocked `{later}` after `{tool}`. Shell "
                    "expansion runs after this guard, so a flag token "
                    "containing `$`, a backtick, or `{` can turn into a "
                    "different flag at execution time. Write the flag "
                    "literally, or pass expanded values as separate "
                    "non-flag arguments."
                )
            for flag in flags:
                if later == flag or later.startswith(flag + "="):
                    return _message(tool, flag)
    return ""


def _payload(raw: str) -> dict[str, Any]:
    # mode_persistence._payload と同じ数行。フック同士を import で結合させない。
    try:
        payload = json.loads(raw or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _record(event: str, raw: str) -> None:
    """`CLAUDE_HOOK_RECORD` が指すディレクトリに実ペイロードを保存する。

    session_log._record と同じ理由・同じ数行。PreToolUse の実収録が
    取れたら hooks/fixtures/ に昇格させること。
    """
    dest = os.environ.get("CLAUDE_HOOK_RECORD")
    if not dest:
        return
    try:
        directory = Path(dest)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{event or 'unknown'}.json").write_text(raw, encoding="utf-8")
    except OSError:
        pass  # 記録は best-effort。


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    event = argv[1] if len(argv) > 1 else ""
    if event != "PreToolUse":
        return 0

    raw = sys.stdin.read() if stdin_text is None else stdin_text
    _record(event, raw)
    payload = _payload(raw)
    if payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = str((tool_input or {}).get("command") or "") \
        if isinstance(tool_input, dict) else ""
    if not command:
        return 0

    reason = blocked(command)
    if reason:
        sys.stderr.write(reason + "\n")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # フックがセッションを止めることは絶対に避ける
