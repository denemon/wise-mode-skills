#!/usr/bin/env python3
"""session_log.py — Claude Code のセッションを .claude/log/ に記録するフック

PostToolUse でツールの入出力を、Stop でターンの区切りを追記する。
書き出す直前に秘匿値をマスクする（パターンベースなので完全ではない）。

以前は Obsidian への同期も兼ねていたが、既定で無効（VAULT_DIR="") のまま
コード 205 行・テスト約 600 行を占め、ツール分岐の二重実装も抱えていたので
削除した。ログ機能だけになったので名前も実態に合わせてある。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_DIRNAME = ".claude/log"
SESSION_MARKER_PREFIX = "**Session:** "


# ── 秘匿値のマスク ────────────────────────────────────────────
# このフックはツールの入出力をそのままディスクに残す。`cat .env` の結果や
# Authorization ヘッダがログに平文で残るため、書き出す直前に
# 潰す。完全な secret scanner ではない（それは gitleaks / trufflehog の仕事）。
# 狙いは「よくある形の秘匿値を確実に消す」こと。過剰マスクは許容する。
REDACTED = "«redacted»"

_SECRET_KEY = (
    r"pass(?:wd|word)?|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|secret[_-]?key|private[_-]?key|credential|client[_-]?secret"
)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 秘密鍵ブロックは丸ごと。他のパターンに刻まれる前に処理する。
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "«redacted private key»",
    ),
    # 発行元が判別できるトークン形状
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}"
            r"|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
            r"|AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9_-]{20,})"
        ),
        REDACTED,
    ),
    # URL に埋め込まれた資格情報 — scheme://user:pass@host
    (re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)"), r"\1" + REDACTED + r"\2"),
    # Authorization: Bearer xxx
    (
        re.compile(
            r"(authorization\s*[:=]\s*[\"']?(?:bearer|basic|token)?\s*)"
            r"[A-Za-z0-9._+/=-]{8,}",
            re.IGNORECASE,
        ),
        r"\1" + REDACTED,
    ),
    # 秘匿的な名前への代入 — KEY=value / "key": "value" / key: value
    (
        re.compile(rf"((?:{_SECRET_KEY})[\"']?\s*[:=]\s*[\"']?)[^\s\"',;)]{{4,}}", re.IGNORECASE),
        r"\1" + REDACTED,
    ),
)


def _redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _now() -> datetime:
    return datetime.now()


def _record(event: str, raw: str) -> None:
    """`CLAUDE_HOOK_RECORD` が指すディレクトリに実ペイロードを保存する。

    外部契約を記憶から書き起こすと、実装とテストが同じ誤りを共有して静かに
    壊れる（`tool_result` / `tool_response` の取り違えが実例。128 件が緑のまま
    ツール出力が一切記録されない状態が残った）。

    使い方: `CLAUDE_HOOK_RECORD=hooks/fixtures/recorded` を付けて Claude Code を
    1 ターン動かすと、実物が採取される。それを fixtures の正とする。
    """
    dest = os.environ.get("CLAUDE_HOOK_RECORD")
    if not dest:
        return
    try:
        directory = Path(dest)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{event or 'unknown'}.json").write_text(raw, encoding="utf-8")
    except OSError:
        pass  # 記録は best-effort。フックの本務を止めない。


def _safe_json_loads(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_root(payload: dict[str, Any]) -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    return Path(os.getcwd())


def _extract_session_id(payload: dict[str, Any]) -> str:
    session_id = payload.get("session_id", "")
    return session_id if isinstance(session_id, str) else ""


def _detect_event_type(payload: dict[str, Any], argv: list[str]) -> str:
    if len(argv) > 1 and argv[1]:
        return argv[1]

    for key in ("hook_event_name", "event_name", "event_type", "hook_event"):
        value = payload.get(key, "")
        if isinstance(value, str) and value:
            return value

    return ""


def _log_dir(payload: dict[str, Any]) -> Path:
    return _project_root(payload) / LOG_DIRNAME


def _log_file_path(log_dir: Path, session_id: str) -> Path:
    # ファイル名はセッション ID のハッシュだけから決める。以前は
    # 日時名 + `.sessions` レジストリ + マーカースキャンで解決していたが、
    # exists() チェック後の作成と read-modify-write に排他が無く、40 並行
    # セッションで 28 セッション分以上を無音で失った。共有状態を持たなければ
    # 競合する場所も無い。日時ベースの名前も不可: セッションが日付をまたぐと
    # イベントごとに別ファイルへ分裂する。
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return log_dir / f"session-{digest}.md"


def _resolve_log_file(payload: dict[str, Any], now: datetime) -> Path | None:
    session_id = _extract_session_id(payload)
    if not session_id:
        return None

    log_dir = _log_dir(payload)
    log_dir.mkdir(parents=True, exist_ok=True)

    path = _log_file_path(log_dir, session_id)
    if not path.exists():
        header = (
            "# Claude Code Session Log\n"
            f"**Date:** {now.strftime('%Y-%m-%d')}\n"
            f"**Start:** {now.strftime('%H:%M:%S')}\n"
            f"**Project:** {_project_root(payload).name}\n"
            f"{SESSION_MARKER_PREFIX}{session_id}\n\n"
            "---\n"
        )
        try:
            # O_EXCL で原子的に作成し、負けた側は追記に合流するだけ。
            # O_APPEND も必須: exists() と flush の間に別スレッドがエントリを
            # 追記し得るので、offset 0 への書き込みだとそれを上書きして失う
            # (並行テストが実際に検出した)。追記なら最悪ヘッダが後ろに
            # 並ぶだけで、データは失われない。
            fd = os.open(
                str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_APPEND)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(header)
    return path


def _stringify_tool_result(raw_result: Any) -> str:
    # Bash の tool_response は {stdout, stderr, interrupted} の dict。JSON のまま
    # 貼ると改行がエスケープされてログが読めないので、本文だけを取り出す。
    if isinstance(raw_result, dict) and ("stdout" in raw_result or "stderr" in raw_result):
        parts = [raw_result.get("stdout") or "", raw_result.get("stderr") or ""]
        return "\n".join(p for p in parts if p).strip()
    if isinstance(raw_result, (dict, list)):
        return json.dumps(raw_result, ensure_ascii=False, indent=2)
    return str(raw_result) if raw_result else ""


def _format_tool_input_summary(inp: Any) -> str:
    if not inp:
        return ""
    try:
        summary = json.dumps(inp, ensure_ascii=False)
    except TypeError:
        summary = str(inp)
    if len(summary) > 200:
        summary = summary[:200] + "..."
    return summary


def _format_quote_block(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def _format_post_tool_use_entry(payload: dict[str, Any], now: datetime) -> str:
    ts = now.strftime("%H:%M")
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {})
    # `tool_response` が正。`tool_result` はプロンプト型フックのテンプレート変数
    # ($TOOL_RESULT) の名前で、コマンド型フックが stdin で受け取る JSON には存在
    # しない。取り違えると出力が常に空になり、ログは静かに入力だけになる。
    raw_result = payload.get("tool_response", "")
    result = _stringify_tool_result(raw_result)
    lines: list[str] = []

    if not isinstance(inp, dict):
        inp = {}

    if tool == "Bash":
        cmd = inp.get("command", "")
        desc = inp.get("description", "")
        header = f"### [{ts}] `Bash`"
        if desc:
            header += f" — {desc}"
        lines.append(header)
        if cmd:
            lines.append(f"```bash\n{cmd}\n```")
        if result:
            lines.append(
                f"<details><summary>result</summary>\n\n```\n{result}\n```\n</details>"
            )

    elif tool == "Read":
        fp = inp.get("file_path", "")
        lines.append(f"### [{ts}] `Read` — `{fp}`")

    elif tool == "Write":
        fp = inp.get("file_path", "")
        lines.append(f"### [{ts}] `Write` — `{fp}`")

    elif tool == "Edit":
        fp = inp.get("file_path", "")
        old = inp.get("old_string", "")
        new = inp.get("new_string", "")
        lines.append(f"### [{ts}] `Edit` — `{fp}`")
        if old or new:
            lines.append("```diff")
            for line in str(old).splitlines():
                lines.append(f"- {line}")
            for line in str(new).splitlines():
                lines.append(f"+ {line}")
            lines.append("```")

    elif tool == "Glob":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        header = f"### [{ts}] `Glob` — `{pattern}`"
        if path:
            header += f" in `{path}`"
        lines.append(header)
        if result:
            lines.append(f"```\n{result}\n```")

    elif tool == "Grep":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        glob_filter = inp.get("glob", "")
        header = f"### [{ts}] `Grep` — `{pattern}`"
        if path:
            header += f" in `{path}`"
        if glob_filter:
            header += f" (`{glob_filter}`)"
        lines.append(header)
        if result:
            lines.append(f"```\n{result}\n```")

    elif tool == "Agent":
        desc = inp.get("description", "")
        prompt = inp.get("prompt", "")
        agent_type = inp.get("subagent_type", "")
        header = f"### [{ts}] `Agent`"
        if agent_type:
            header += f" ({agent_type})"
        if desc:
            header += f" — {desc}"
        lines.append(header)
        if prompt:
            prompt_lines = prompt.splitlines()
            if len(prompt_lines) > 5:
                prompt = "\n".join(prompt_lines[:5]) + "\n..."
            lines.append(_format_quote_block(prompt))

    elif tool == "Skill":
        skill = inp.get("skill", "")
        args = inp.get("args", "")
        header = f"### [{ts}] `Skill` — /{skill}"
        if args:
            header += f" {args}"
        lines.append(header)

    else:
        lines.append(f"### [{ts}] `{tool}`")
        summary = _format_tool_input_summary(inp)
        if summary:
            lines.append(f"```json\n{summary}\n```")
        if result:
            lines.append(
                f"<details><summary>result</summary>\n\n```\n{result}\n```\n</details>"
            )

    return _redact("\n".join(lines))


def write_local_log(
    payload: dict[str, Any], event_type: str, *, now: datetime | None = None
) -> Path | None:
    if event_type not in {"PostToolUse", "Stop"}:
        return None

    current_time = now or _now()
    log_file = _resolve_log_file(payload, current_time)
    if log_file is None:
        return None

    if event_type == "PostToolUse":
        entry = _format_post_tool_use_entry(payload, current_time)
        text = f"\n{entry}\n" if entry else ""
    else:
        text = f"\n---\n> Turn ended at {current_time.strftime('%H:%M:%S')}\n"

    if text:
        # 1 エントリ = 1 回の os.write。バッファ付き open("a") はエントリが
        # バッファ(8KB)を超えると複数 write に分割され、並行イベントと
        # エントリ内部で交錯する。O_APPEND の単一 write は分割されない。
        fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

    return log_file


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> None:
    argv = list(sys.argv if argv is None else argv)
    stdin_text = sys.stdin.read() if stdin_text is None else stdin_text

    payload = _safe_json_loads(stdin_text)
    if not payload:
        return

    current_time = _now()
    event_type = _detect_event_type(payload, argv)
    _record(event_type, stdin_text)
    if event_type:
        write_local_log(payload, event_type, now=current_time)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # mode_persistence.py と同じ理由: フックがセッションを止めない。
        # PostToolUse は全ツール呼び出しで走るので、書き込み失敗や壊れた
        # トランスクリプトが毎回エラーを吐くのを防ぐ。
