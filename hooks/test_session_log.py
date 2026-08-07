#!/usr/bin/env python3
"""session_log.py のユニットテスト

対象: セッションログの整形・秘匿値マスク・ファイル解決
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# テスト対象モジュールをインポート
sys.path.insert(0, str(Path(__file__).parent))
import session_log as mod


FIXED_NOW = datetime(2026, 4, 17, 12, 34, 56)
FIXED_LATER = datetime(2026, 4, 17, 12, 35, 40)


class _EnvIsolatedTestCase(unittest.TestCase):
    """CLAUDE_PROJECT_DIR を payload.cwd より優先で読むため、
    テスト実行環境の env が漏れ込むと payload で指定した tmpdir 以外に
    ログが書き込まれ得る。各テストの前に env を空に固定する。"""

    def setUp(self) -> None:
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_PROJECT_DIR": ""}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)






# ══════════════════════════════════════════════════════════════
# _format_post_tool_use_entry
# ══════════════════════════════════════════════════════════════
class TestFormatPostToolUseEntry(unittest.TestCase):
    """ローカルログ用エントリ整形 — ツール別分岐とフォールバック"""

    def _call(self, tool: str, inp: dict, result=""):
        return mod._format_post_tool_use_entry(
            {"tool_name": tool, "tool_input": inp, "tool_response": result},
            FIXED_NOW,
        )

    def test_bash_with_result_has_details_block(self):
        out = self._call("Bash", {"command": "ls", "description": "list"}, "a\nb")
        self.assertIn("### [12:34] `Bash` — list", out)
        self.assertIn("```bash\nls\n```", out)
        self.assertIn("<details><summary>result</summary>", out)
        self.assertIn("a\nb", out)

    def test_bash_real_payload_shape_is_recorded(self):
        # Claude Code が実際に渡す形。文字列だと決め打ちすると出力が丸ごと
        # 消え、ログは入力だけになって「動いているように見える」。
        out = self._call(
            "Bash",
            {"command": "pytest", "description": "run tests"},
            {"stdout": "2 passed", "stderr": "warn: slow", "interrupted": False},
        )
        self.assertIn("<details><summary>result</summary>", out)
        self.assertIn("2 passed", out)
        self.assertIn("warn: slow", out)
        self.assertNotIn("interrupted", out)  # JSON をそのまま貼っていない

    def test_bash_real_payload_shape_is_redacted(self):
        out = self._call(
            "Bash", {"command": "cat .env"}, {"stdout": "TOKEN=sk-live-abcdefghij123456"}
        )
        self.assertNotIn("sk-live-abcdefghij123456", out)
        self.assertIn(mod.REDACTED, out)

    def test_bash_no_command_skips_code_block(self):
        out = self._call("Bash", {})
        self.assertIn("### [12:34] `Bash`", out)
        self.assertNotIn("```bash", out)

    def test_edit_with_old_new_produces_diff(self):
        out = self._call("Edit", {
            "file_path": "/f.py",
            "old_string": "old1\nold2",
            "new_string": "new1\nnew2",
        })
        self.assertIn("### [12:34] `Edit` — `/f.py`", out)
        self.assertIn("```diff", out)
        self.assertIn("- old1", out)
        self.assertIn("- old2", out)
        self.assertIn("+ new1", out)
        self.assertIn("+ new2", out)

    def test_edit_without_old_new_skips_diff(self):
        out = self._call("Edit", {"file_path": "/f.py"})
        self.assertIn("`Edit`", out)
        self.assertNotIn("```diff", out)

    def test_glob_with_path_and_result(self):
        out = self._call(
            "Glob", {"pattern": "*.py", "path": "/src"}, "a.py\nb.py"
        )
        self.assertIn("`Glob` — `*.py`", out)
        self.assertIn("in `/src`", out)
        self.assertIn("a.py\nb.py", out)

    def test_grep_with_glob_filter(self):
        out = self._call(
            "Grep",
            {"pattern": "TODO", "path": "/src", "glob": "*.py"},
            "match",
        )
        self.assertIn("`Grep` — `TODO`", out)
        self.assertIn("in `/src`", out)
        self.assertIn("(`*.py`)", out)

    def test_agent_long_prompt_truncated_at_five_lines(self):
        long_prompt = "\n".join(f"line{i}" for i in range(10))
        out = self._call(
            "Agent",
            {"description": "d", "subagent_type": "Explore", "prompt": long_prompt},
        )
        self.assertIn("`Agent` (Explore) — d", out)
        self.assertIn("> line0", out)
        self.assertIn("> line4", out)
        self.assertNotIn("line5", out)  # 5 行で切り詰め
        self.assertIn("> ...", out)

    def test_skill_with_args(self):
        out = self._call("Skill", {"skill": "wise", "args": "implement X"})
        self.assertIn("### [12:34] `Skill` — /wise implement X", out)

    def test_skill_without_args_no_trailing_space(self):
        out = self._call("Skill", {"skill": "wise"})
        self.assertIn("### [12:34] `Skill` — /wise", out)
        self.assertNotIn("/wise ", out)

    def test_unknown_tool_fallback_serializes_input_and_result(self):
        out = self._call("Custom", {"key": "val"}, "result data")
        self.assertIn("### [12:34] `Custom`", out)
        self.assertIn('"key": "val"', out)
        self.assertIn("result data", out)

    def test_non_dict_input_does_not_crash(self):
        out = mod._format_post_tool_use_entry(
            {"tool_name": "Bash", "tool_input": "not a dict"},
            FIXED_NOW,
        )
        self.assertIn("`Bash`", out)

    def test_long_tool_input_summary_truncated(self):
        big = {"key": "x" * 500}
        out = self._call("Custom", big)
        self.assertIn("...", out)  # 200 文字で切り詰め

    def test_dict_result_serialized_as_json(self):
        out = self._call("Bash", {"command": "x"}, {"a": 1, "b": [1, 2]})
        self.assertIn('"a": 1', out)


# ══════════════════════════════════════════════════════════════
# _safe_json_loads / _load_session_map
# ══════════════════════════════════════════════════════════════
class TestSafeJsonLoads(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(mod._safe_json_loads(""), {})

    def test_whitespace(self):
        self.assertEqual(mod._safe_json_loads("  \n  "), {})

    def test_malformed(self):
        self.assertEqual(mod._safe_json_loads("{not json"), {})

    def test_valid_dict(self):
        self.assertEqual(mod._safe_json_loads('{"a": 1}'), {"a": 1})

    def test_list_returns_empty_dict(self):
        """JSON 配列は dict ではないので {} を返す"""
        self.assertEqual(mod._safe_json_loads("[1, 2, 3]"), {})

    def test_scalar_returns_empty_dict(self):
        self.assertEqual(mod._safe_json_loads("42"), {})
        self.assertEqual(mod._safe_json_loads('"str"'), {})


class TestLoadSessionMap(unittest.TestCase):
    def test_nonexistent_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                mod._load_session_map(Path(tmpdir) / "missing"), {}
            )

    def test_valid_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions"
            path.write_text("s1=/log/a.md\ns2=/log/b.md\n", encoding="utf-8")
            self.assertEqual(
                mod._load_session_map(path),
                {"s1": "/log/a.md", "s2": "/log/b.md"},
            )

    def test_skips_malformed_lines(self):
        """`=` を含まない行、key/value が空の行はスキップ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions"
            path.write_text(
                "valid=/log/a.md\n"
                "no_equal_sign\n"
                "=missing_key\n"
                "missing_value=\n"
                "\n"
                "another=/log/b.md\n",
                encoding="utf-8",
            )
            self.assertEqual(
                mod._load_session_map(path),
                {"valid": "/log/a.md", "another": "/log/b.md"},
            )

    def test_value_with_equals_sign_preserved(self):
        """値に '=' が含まれても split(1) なので最初の '=' で分割"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions"
            path.write_text("s1=/path/with=eq.md\n", encoding="utf-8")
            self.assertEqual(
                mod._load_session_map(path), {"s1": "/path/with=eq.md"}
            )


# ══════════════════════════════════════════════════════════════
# Local logging / main / セッションログ sync
# ══════════════════════════════════════════════════════════════
class TestLocalLogging(_EnvIsolatedTestCase):
    def _payload(self, cwd: str) -> dict:
        return {
            "session_id": "session-1234567890",
            "cwd": cwd,
            "tool_name": "Bash",
            "tool_input": {
                "command": "pytest",
                "description": "Run test suite",
            },
            "tool_response": "PASS",
        }

    def test_post_tool_use_creates_local_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = mod.write_local_log(
                self._payload(tmpdir), "PostToolUse", now=FIXED_NOW
            )

            self.assertIsNotNone(log_file)
            self.assertTrue(log_file.exists())
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("# Claude Code Session Log", content)
            self.assertIn("**Project:** " + Path(tmpdir).name, content)
            self.assertIn("**Session:** session-1234567890", content)
            self.assertIn("### [12:34] `Bash` — Run test suite", content)
            self.assertIn("```bash\npytest\n```", content)
            self.assertIn("PASS", content)

            session_map = Path(tmpdir) / ".claude" / "log" / ".sessions"
            self.assertTrue(session_map.exists())
            self.assertIn("session-1234567890", session_map.read_text(encoding="utf-8"))

    def test_stop_reuses_same_file_even_if_session_map_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self._payload(tmpdir)
            first_log = mod.write_local_log(payload, "PostToolUse", now=FIXED_NOW)
            self.assertIsNotNone(first_log)

            session_map = Path(tmpdir) / ".claude" / "log" / ".sessions"
            session_map.unlink()

            stop_payload = {"session_id": payload["session_id"], "cwd": tmpdir}
            stop_log = mod.write_local_log(stop_payload, "Stop", now=FIXED_LATER)

            self.assertEqual(first_log, stop_log)
            content = first_log.read_text(encoding="utf-8")
            self.assertIn("> Turn ended at 12:35:40", content)

    def test_missing_session_id_skips_local_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = mod.write_local_log({"cwd": tmpdir}, "PostToolUse", now=FIXED_NOW)
            self.assertIsNone(result)
            self.assertFalse((Path(tmpdir) / ".claude" / "log").exists())




class TestMain(_EnvIsolatedTestCase):
    def test_main_writes_local_log_when_called_with_event_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "session_id": "session-1234567890",
                "cwd": tmpdir,
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_response": "",
            }
            with mock.patch.object(mod, "_now", return_value=FIXED_NOW):
                mod.main(
                    ["session_log.py", "PostToolUse"],
                    json.dumps(payload, ensure_ascii=False),
                )

            log_file = Path(tmpdir) / ".claude" / "log" / "2026-04-17_123456.md"
            self.assertTrue(log_file.exists())
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("### [12:34] `Read` — `README.md`", content)

    def test_main_ignores_empty_stdin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ, {"CLAUDE_PROJECT_DIR": tmpdir}
            ), mock.patch.object(mod, "_now", return_value=FIXED_NOW):
                mod.main(["session_log.py", "PostToolUse"], "")
            self.assertFalse((Path(tmpdir) / ".claude" / "log").exists())


# ══════════════════════════════════════════════════════════════
# _redact — 秘匿値がディスクに残らないこと
# ══════════════════════════════════════════════════════════════
class TestRedact(unittest.TestCase):
    """このフックはツール出力をそのまま永続化する。マスクが壊れると
    .env の中身や Authorization ヘッダが平文でログと vault に残る。"""

    def assertRedacted(self, text: str, leaked: str) -> None:
        out = mod._redact(text)
        self.assertNotIn(leaked, out, f"leaked into log: {text!r} -> {out!r}")

    # ── 代入形 ──

    def test_env_file_contents(self):
        self.assertRedacted("API_KEY=sk_live_abcdef123456", "sk_live_abcdef123456")
        self.assertRedacted("DB_PASSWORD=hunter2xyz", "hunter2xyz")
        self.assertRedacted('"client_secret": "abc123def456"', "abc123def456")
        self.assertRedacted("aws_secret_access_key = wJalrXUtnFEMI", "wJalrXUtnFEMI")

    def test_yaml_style_colon(self):
        self.assertRedacted("token: ghs_verysecretvalue", "ghs_verysecretvalue")

    # ── ヘッダ / URL ──

    def test_authorization_header(self):
        self.assertRedacted(
            'curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload"',
            "eyJhbGciOiJIUzI1NiJ9.payload",
        )

    def test_url_embedded_credentials(self):
        self.assertRedacted(
            "psql postgres://admin:s3cr3tpw@db.internal:5432/app", "s3cr3tpw"
        )

    def test_url_host_survives(self):
        # 資格情報だけを消し、接続先は読めるまま残す
        out = mod._redact("postgres://admin:s3cr3tpw@db.internal:5432/app")
        self.assertIn("db.internal:5432/app", out)
        self.assertIn("admin", out)

    # ── 発行元が判別できる形状（キー名が無くても消す）──

    def test_bare_provider_tokens(self):
        for token in (
            "sk-abcdefghijklmnopqrstuvwx",
            "ghp_abcdefghijklmnopqrstuvwxyz1234",
            "xoxb-1234567890-abcdefghij",
            "AKIAIOSFODNN7EXAMPLE",
        ):
            with self.subTest(token=token):
                self.assertRedacted(f"echo {token}", token)

    def test_private_key_block(self):
        pem = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAA\nSECRETLINE\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )
        self.assertRedacted(pem, "SECRETLINE")

    # ── 過剰マスクの上限 ──

    def test_ordinary_text_untouched(self):
        for text in (
            "### [12:34] `Bash` — run the tests",
            "assert result.count == 5",
            "src/auth.ts:47 missing null check",
            "https://github.com/den-emon/wise-mode",
        ):
            with self.subTest(text=text):
                self.assertEqual(mod._redact(text), text)


# ══════════════════════════════════════════════════════════════
# 書き出し経路にマスクが掛かっていること
# ══════════════════════════════════════════════════════════════
class TestRedactionIsWired(_EnvIsolatedTestCase):
    """_redact 単体が正しくても、書き出し経路に繋がっていなければ意味がない。"""

    def test_bash_result_is_redacted_in_local_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "session_id": "sess-redact-1",
                "cwd": tmpdir,
                "tool_name": "Bash",
                "tool_input": {"command": "cat .env"},
                "tool_response": "STRIPE_SECRET_KEY=sk_live_leakme123456",
            }
            with mock.patch.object(mod, "_now", return_value=FIXED_NOW):
                log_file = mod.write_local_log(payload, "PostToolUse")
            body = Path(log_file).read_text(encoding="utf-8")
            self.assertNotIn("sk_live_leakme123456", body)
            self.assertIn(mod.REDACTED, body)
            self.assertIn("cat .env", body)  # 何をしたかは残る



if __name__ == "__main__":
    unittest.main()
