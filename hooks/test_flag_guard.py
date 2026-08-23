#!/usr/bin/env python3
"""flag_guard.py のユニットテスト

対象: 危険フラグの遮断 / 文書化済みコマンド形の素通し / 未知イベント・
壊れた入力での無反応（フェイルオープン）

ペイロードは hooks/fixtures/post_tool_use_bash.json（実収録）から組み立てる。
PreToolUse の実収録はまだ無いが、tool_name / tool_input.command の形は
PostToolUse と共通（公式 hook ドキュメントおよびフィクスチャの確認元に一致）。
PreToolUse を実収録したらこのフィクスチャ参照を差し替えること。
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import flag_guard as mod

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "post_tool_use_bash.json")
    .read_text(encoding="utf-8"))


def payload(command: str) -> str:
    base = {k: v for k, v in FIXTURE.items()
            if k not in ("_comment", "tool_response")}
    base["hook_event_name"] = "PreToolUse"
    base["tool_input"] = {"command": command}
    return json.dumps(base)


def run(command: str) -> tuple[int, str]:
    """(終了コード, stderr) を返す。"""
    buf = io.StringIO()
    with redirect_stderr(buf):
        code = mod.main([__file__, "PreToolUse"], stdin_text=payload(command))
    return code, buf.getvalue()


class BlockedFlagsTest(unittest.TestCase):
    """承認済みプレフィックスの後ろに付くと実行/書き込みに化けるフラグ"""

    def assert_blocked(self, command: str, flag: str):
        code, err = run(command)
        self.assertEqual(code, 2, f"not blocked: {command}")
        self.assertIn(flag, err)

    def assert_allowed(self, command: str):
        code, err = run(command)
        self.assertEqual(code, 0, f"false positive: {command}\n{err}")
        self.assertEqual(err, "")

    # ── rg: --pre はファイルごとに任意コマンドを実行する ─────────
    def test_rg_pre_is_blocked(self):
        self.assert_blocked("rg -n --pre 'evil' pattern .", "--pre")

    def test_rg_pre_with_equals_and_full_path(self):
        self.assert_blocked("/usr/local/bin/rg --pre=evil -n x .", "--pre")

    def test_rg_pre_glob_is_blocked(self):
        self.assert_blocked("rg -n --pre-glob '*.md' --pre evil x", "--pre")

    def test_rg_in_pipe_is_inspected(self):
        self.assert_blocked(
            "git ls-files --others --exclude-standard | rg -i --pre evil x",
            "--pre")

    def test_documented_rg_forms_pass(self):
        self.assert_allowed(
            'rg -n -i -o "password|secret|api[_-]?key" .')
        # --prefix は --pre と別フラグ（前方一致で巻き込まない）
        self.assert_allowed("rg -n --prefix-count x .")

    # ── git: 書き込み / 設定注入 / バイナリ差し替え ───────────────
    def test_git_output_is_blocked(self):
        self.assert_blocked("git log --output=/tmp/pwned --oneline", "--output")
        self.assert_blocked("git diff --output /tmp/pwned HEAD~1", "--output")

    def test_git_inline_config_is_blocked(self):
        # `git -c diff.external=cmd diff` は差分表示のたびに cmd を実行する
        self.assert_blocked("git -c diff.external=evil diff", "-c")

    def test_git_exec_path_is_blocked(self):
        self.assert_blocked("git --exec-path=/tmp/evil log", "--exec-path")

    def test_normal_git_forms_pass(self):
        self.assert_allowed("git log --oneline -20")
        self.assert_allowed("git diff HEAD~1 -- src/")
        self.assert_allowed("git status --porcelain")

    # ── スキャナ: レポート出力フラグは任意パス上書きになる ────────
    def test_scanner_report_flags_are_blocked(self):
        self.assert_blocked("bandit -r . -o /tmp/pwned", "-o")
        self.assert_blocked("gitleaks detect --report-path /tmp/pwned",
                            "--report-path")
        self.assert_blocked("gosec -out /tmp/pwned ./...", "-out")

    def test_scanner_normal_forms_pass(self):
        self.assert_allowed("bandit -r .")
        self.assert_allowed("gitleaks detect --no-banner")
        # bandit の -r は再帰であって report ではない（フラグはツール別）
        self.assert_allowed("tfsec .")

    # ── 対象外のコマンドには触らない ─────────────────────────────
    def test_unlisted_tools_are_untouched(self):
        self.assert_allowed("npm install --prefix /tmp/x left-pad")
        self.assert_allowed("ls -la /tmp")

    def test_broken_quoting_still_blocks(self):
        # shlex が解析できない引用でもフラグを見逃さない（保守的側に倒す）
        code, _ = run("rg -n --pre 'evil pattern")
        self.assertEqual(code, 2)

    # ── 展開難読化: ガードはシェル展開前の文字列しか見えない ────────
    def test_expansion_obfuscated_flags_are_blocked(self):
        # `--out${GAP}put` は字面ではどのフラグとも一致せず、GAP が空なら
        # 実行時に --output へ化ける（レビューで実証されたバイパス）。
        self.assert_blocked(
            "git diff --out${WISE_FLAG_GAP}put=/tmp/x HEAD",
            "--out${WISE_FLAG_GAP}put")
        self.assert_blocked("rg -n --p${X}re evil x", "--p${X}re")
        self.assert_blocked("git log --out`echo put`=/tmp/x", "`")
        self.assert_blocked("git diff --out{,}put=/tmp/x HEAD", "--out{,}put")

    def test_expanded_values_in_non_flag_positions_pass(self):
        # 展開値そのもの（フラグではないトークン）は正当な使い方。
        # diff-acquisition.md の文書化コマンドがまさにこの形。
        self.assert_allowed('git diff "$RANGE"')
        self.assert_allowed('git diff "$BASE_REF"...HEAD -- src/')
        self.assert_allowed("rg -n --glob=*.py pattern .")


class RobustnessTest(unittest.TestCase):
    def _main(self, argv_event: str, stdin_text: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stderr(buf):
            code = mod.main([__file__, argv_event], stdin_text=stdin_text)
        return code, buf.getvalue()

    def test_non_bash_tool_passes(self):
        p = json.loads(payload("unused"))
        p["tool_name"] = "Edit"
        p["tool_input"] = {"file_path": "/tmp/x", "old_string": "--pre"}
        code, err = self._main("PreToolUse", json.dumps(p))
        self.assertEqual((code, err), (0, ""))

    def test_unknown_event_is_ignored(self):
        code, err = self._main("Stop", payload("rg --pre evil x"))
        self.assertEqual((code, err), (0, ""))

    def test_missing_command_passes(self):
        p = json.loads(payload("unused"))
        p["tool_input"] = {}
        code, err = self._main("PreToolUse", json.dumps(p))
        self.assertEqual((code, err), (0, ""))

    def test_garbage_stdin_does_not_raise(self):
        code, err = self._main("PreToolUse", "not json")
        self.assertEqual((code, err), (0, ""))


if __name__ == "__main__":
    unittest.main()
