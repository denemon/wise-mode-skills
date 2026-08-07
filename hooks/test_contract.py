#!/usr/bin/env python3
"""外部契約テスト — 「実装とテストが同じ思い込みを共有する」バグを潰すための層

通常のユニットテストは、テスト側がペイロードを手で組み立てるので、キー名を
間違えていても実装と一致していれば緑になる。実際 `tool_result` を読む実装と
`tool_result` を渡すテストが 128 件そろって緑のまま、ツール出力が一切記録され
ない状態が残った。

ここでは 2 つだけ検査する。どちらも「リポジトリの内側で閉じない」検査:

1. フックは fixtures/*.json（実物に合わせた唯一の正）から動くこと
2. その出力が README の documented なログ形式と一致すること

README が嘘をつくか、フックが実ペイロードで動かなくなれば、どちらかが落ちる。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_log as mod  # noqa: E402
import mode_persistence as persistence  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
README = (ROOT / "README.md").read_text(encoding="utf-8")
FIXED_NOW = datetime(2026, 4, 17, 12, 34, 56)

# README のログ形式サンプルと実出力の両方に現れなければならない構造。
# 片方だけ変わったら落ちる ＝ ドキュメントと実装が同時にしかずれない。
LOG_STRUCTURE = (
    "### [",                                  # 時刻つき見出し
    "`Bash`",                                 # ツール名
    "```bash",                                # 入力コマンドのブロック
    "<details><summary>result</summary>",     # ツール出力のブロック
)


def readme_log_format_section() -> str:
    """README のログ形式サンプルだけを切り出す。

    README 全体を対象にすると意味がない。"```bash" は install 手順だけで 9 回出るので、
    ログ形式の例が丸ごと消えてもマーカー検査が通ってしまう。
    """
    match = re.search(r"^### Log format$(.*?)^## ", README, re.MULTILINE | re.DOTALL)
    assert match, "README does not have a '### Log format' section"
    return match.group(1)


def load_fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    payload.pop("_comment", None)
    return payload


class PayloadContractTest(unittest.TestCase):
    """Claude Code が実際に渡す形で動くか"""

    def test_fixture_uses_tool_response_not_tool_result(self):
        payload = load_fixture("post_tool_use_bash")
        self.assertIn("tool_response", payload)
        self.assertNotIn(
            "tool_result",
            payload,
            "tool_result はプロンプト型フックの変数名。stdin JSON には存在しない",
        )

    def test_hook_records_output_from_real_payload(self):
        # このテストが最初に存在していれば、出力欠落は初日に落ちていた。
        payload = load_fixture("post_tool_use_bash")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            log_file = mod.write_local_log(payload, "PostToolUse", now=FIXED_NOW)
            body = log_file.read_text(encoding="utf-8")

        self.assertIn("npm test", body, "入力コマンドが記録されていない")
        self.assertIn("PASS src/app.test.ts", body, "ツール出力が記録されていない")

    def test_bash_response_dict_is_not_dumped_as_json(self):
        # {stdout, stderr, interrupted} を JSON のまま貼ると改行が \n に潰れて読めない。
        payload = load_fixture("post_tool_use_bash")
        entry = mod._format_post_tool_use_entry(payload, FIXED_NOW)
        self.assertNotIn("interrupted", entry)
        self.assertNotIn("\\n", entry)


class ReadmeMatchesRealOutputTest(unittest.TestCase):
    """README のログ形式が実物と一致しているか"""

    def setUp(self):
        payload = load_fixture("post_tool_use_bash")
        self.entry = mod._format_post_tool_use_entry(payload, FIXED_NOW)

    def test_documented_structure_appears_in_readme(self):
        section = readme_log_format_section()
        for marker in LOG_STRUCTURE:
            with self.subTest(marker=marker):
                self.assertIn(marker, section)

    def test_documented_structure_is_actually_produced(self):
        for marker in LOG_STRUCTURE:
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    self.entry,
                    f"README は {marker!r} を載せているが、フックは出力していない",
                )


class HookNeverBreaksTheSessionTest(unittest.TestCase):
    """PostToolUse は全ツール呼び出しで走る

    書き込み失敗や壊れたトランスクリプトで例外を投げると、以降すべての
    ツール実行にエラーが付く。`mode_persistence.py` はこれを明示的に握り潰して
    いるが、より頻繁に走るこちらには無かった。実プロセスで確認する。
    """

    def _run(self, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(Path(mod.__file__)), "PostToolUse"],
            input=json.dumps(payload), cwd=str(cwd),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)},
        )

    def test_unwritable_log_dir_does_not_raise(self):
        payload = load_fixture("post_tool_use_bash")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload["cwd"] = str(root)
            log_dir = root / ".claude" / "log"
            log_dir.mkdir(parents=True)
            log_dir.chmod(0o500)
            try:
                result = self._run(payload, root)
            finally:
                log_dir.chmod(0o700)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_garbage_stdin_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(Path(mod.__file__)), "PostToolUse"],
                input="not json at all", cwd=tmpdir,
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


class ModePersistenceContractTest(unittest.TestCase):
    """継続モードのフックも fixture 経由で検査する

    `session_log` だけが契約テストを持っていて、このフックの外部契約は
    誰も検証していなかった。継続モードはこのリポジトリの中心機能なのに。
    """

    def _run(self, payload: dict, event: str, cwd: Path) -> dict:
        result = subprocess.run(
            [sys.executable, str(Path(persistence.__file__)), event],
            input=json.dumps(payload), cwd=str(cwd),
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_real_payload_activates_and_persists(self):
        payload = load_fixture("user_prompt_submit")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload["cwd"] = str(root)

            first = self._run(payload, "UserPromptSubmit", root)
            self.assertIn(
                "WISE MODE ACTIVE",
                first["hookSpecificOutput"]["additionalContext"],
                "起動プロンプトでモードが入っていない",
            )
            self.assertTrue((root / ".claude" / ".wise-mode").exists())

            # 永続化が本体。無関係な次の入力でも貼り直されること。
            payload["prompt"] = "この関数を直して"
            second = self._run(payload, "UserPromptSubmit", root)
            self.assertIn(
                "WISE MODE ACTIVE",
                second["hookSpecificOutput"]["additionalContext"],
                "次ターンで再注入されていない — 永続化が壊れている",
            )

    def test_output_uses_the_documented_envelope(self):
        # additionalContext 以外のキーに入れると Claude Code は黙って無視する。
        payload = load_fixture("user_prompt_submit")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            out = self._run(payload, "UserPromptSubmit", Path(tmpdir))
        self.assertEqual(
            set(out["hookSpecificOutput"]) >= {"hookEventName", "additionalContext"},
            True,
        )


class RecordModeTest(unittest.TestCase):
    """記録モード — 契約を書かずに採る

    fixture を手書きしている限り、思い込みは実装とテストの両方に等しく入る。
    実物を採取できる経路を用意しておき、fixture の更新はそこからにする。
    """

    def _record(self, module, event: str, payload: dict, dest: Path) -> Path:
        subprocess.run(
            [sys.executable, str(Path(module.__file__)), event],
            input=json.dumps(payload), capture_output=True, text=True, timeout=30,
            env={**os.environ, "CLAUDE_HOOK_RECORD": str(dest)},
        )
        return dest / f"{event}.json"

    def test_post_tool_use_payload_is_captured_verbatim(self):
        payload = load_fixture("post_tool_use_bash")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            written = self._record(mod, "PostToolUse", payload, Path(tmpdir) / "rec")
            self.assertTrue(written.is_file(), "記録されていない")
            self.assertEqual(json.loads(written.read_text()), payload)

    def test_user_prompt_submit_payload_is_captured(self):
        payload = load_fixture("user_prompt_submit")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            written = self._record(persistence, "UserPromptSubmit", payload,
                                   Path(tmpdir) / "rec")
            self.assertEqual(json.loads(written.read_text()), payload)

    def test_recording_is_off_by_default(self):
        payload = load_fixture("post_tool_use_bash")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            subprocess.run(
                [sys.executable, str(Path(mod.__file__)), "PostToolUse"],
                input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                env={k: v for k, v in os.environ.items() if k != "CLAUDE_HOOK_RECORD"},
            )
            self.assertFalse((Path(tmpdir) / "rec").exists())

    def test_unwritable_record_dir_does_not_break_the_hook(self):
        payload = load_fixture("post_tool_use_bash")
        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            blocked = Path(tmpdir) / "ro"
            blocked.mkdir()
            blocked.chmod(0o500)
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(mod.__file__)), "PostToolUse"],
                    input=json.dumps(payload), capture_output=True, text=True,
                    timeout=30,
                    env={**os.environ, "CLAUDE_HOOK_RECORD": str(blocked / "sub")},
                )
            finally:
                blocked.chmod(0o700)
        self.assertEqual(result.returncode, 0, result.stderr)



class RedactionAppliesToRealPayloadTest(unittest.TestCase):
    """マスキングが「実際に書き出される経路」に効いているか

    マスキングの主目的は `cat .env` の出力を残さないこと。その出力は
    tool_response に来るので、キーを取り違えている間はマスキングが守る対象が
    そもそも空だった。テストは実ペイロード経由で確認する。
    """

    def test_secret_in_tool_response_is_masked(self):
        payload = load_fixture("post_tool_use_bash")
        payload["tool_input"] = {"command": "cat .env"}
        payload["tool_response"] = {"stdout": "STRIPE_SECRET_KEY=sk_live_leakme123456"}

        with tempfile.TemporaryDirectory() as tmpdir:
            payload["cwd"] = tmpdir
            log_file = mod.write_local_log(payload, "PostToolUse", now=FIXED_NOW)
            body = log_file.read_text(encoding="utf-8")

        self.assertNotIn("sk_live_leakme123456", body)
        self.assertIn(mod.REDACTED, body)
        self.assertIn("cat .env", body)  # 何をしたかは残す


if __name__ == "__main__":
    unittest.main()
