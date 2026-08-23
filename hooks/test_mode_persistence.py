#!/usr/bin/env python3
"""mode_persistence.py のユニットテスト

対象: 起動 / 停止 / 毎ターン再注入 / モード間の独立 / 無関係プロンプトでの無反応
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import mode_persistence as mod


def run(event: str, prompt: str = "") -> str:
    """フックを1回実行し、注入された additionalContext を返す（無ければ ""）。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.main([__file__, event], stdin_text=json.dumps({"prompt": prompt}))
    out = buf.getvalue()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


class ModePersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = Path(tmp.name) / mod.STATE_DIR

    def flag(self, name: str) -> Path:
        return self.state / name

    # ── wise-cont ────────────────────────────────────────────────
    def test_wise_activates_and_reinjects(self):
        self.assertIn("WISE MODE ACTIVE", run("UserPromptSubmit", "/wise-cont"))
        self.assertTrue(self.flag(".wise-mode").exists())
        # 次のターン以降も貼り直される
        self.assertIn("WISE MODE ACTIVE", run("UserPromptSubmit", "add a retry helper"))

    def test_wise_survives_session_start(self):
        # compact / resume 後もモードが生き残ること
        run("UserPromptSubmit", "/wise-cont")
        self.assertIn("WISE MODE ACTIVE", run("SessionStart"))

    def test_wise_cont_off_clears(self):
        run("UserPromptSubmit", "/wise-cont")
        self.assertIn("WISE MODE OFF", run("UserPromptSubmit", "/wise-cont-off"))
        self.assertFalse(self.flag(".wise-mode").exists())
        self.assertEqual(run("UserPromptSubmit", "next task"), "")

    def test_single_shot_wise_does_not_persist(self):
        # /wise は単発。継続モードを立ててはいけない
        self.assertEqual(run("UserPromptSubmit", "/wise refactor this"), "")
        self.assertFalse(self.flag(".wise-mode").exists())

    # ── terse-mode ───────────────────────────────────────────────
    def test_terse_defaults_to_full(self):
        self.assertIn("level: full", run("UserPromptSubmit", "/terse-mode"))

    def test_terse_keeps_level(self):
        self.assertIn("level: ultra", run("UserPromptSubmit", "/terse-mode ultra"))
        self.assertIn("level: ultra", run("UserPromptSubmit", "explain this function"))

    def test_terse_off_clears(self):
        run("UserPromptSubmit", "/terse-mode lite")
        self.assertIn("TERSE MODE OFF", run("UserPromptSubmit", "/terse-mode off"))
        self.assertFalse(self.flag(".terse-mode").exists())

    # ── 相互作用 ─────────────────────────────────────────────────
    def test_modes_are_independent(self):
        run("UserPromptSubmit", "/wise-cont")
        run("UserPromptSubmit", "/terse-mode ultra")
        both = run("UserPromptSubmit", "go on")
        self.assertIn("WISE MODE ACTIVE", both)
        self.assertIn("TERSE MODE ACTIVE", both)
        # terse だけ落としても wise は残る
        run("UserPromptSubmit", "/terse-mode off")
        left = run("UserPromptSubmit", "go on")
        self.assertIn("WISE MODE ACTIVE", left)
        self.assertNotIn("TERSE MODE ACTIVE", left)

    def test_normal_mode_kills_everything(self):
        run("UserPromptSubmit", "/wise-cont")
        run("UserPromptSubmit", "/terse-mode")
        run("UserPromptSubmit", "normal mode")
        self.assertEqual(run("UserPromptSubmit", "go on"), "")

    # ── should-not-trigger ───────────────────────────────────────
    # 以下 3 つは実セッションで誤発火が再現されたプロンプト。モード語を
    # 「含む質問」でモードが切り替わってはいけない（起動は [/$@] 接頭辞必須、
    # normal mode の全消しは行全体一致のみ）。
    def test_question_mentioning_wise_cont_does_not_activate(self):
        self.assertEqual(run("UserPromptSubmit", "wise-cont はどう動く?"), "")
        self.assertFalse(self.flag(".wise-mode").exists())

    def test_question_mentioning_terse_mode_does_not_activate(self):
        self.assertEqual(run("UserPromptSubmit", "terse-mode の実装を確認して"), "")
        self.assertFalse(self.flag(".terse-mode").exists())

    def test_question_mentioning_normal_mode_does_not_deactivate(self):
        run("UserPromptSubmit", "/wise-cont")
        self.assertIn("WISE MODE ACTIVE",
                      run("UserPromptSubmit", "normal mode の意味を教えて"))
        self.assertTrue(self.flag(".wise-mode").exists())

    def test_question_mentioning_wise_cont_off_does_not_deactivate(self):
        # OFF 側も同じ誤発火クラス。コマンド形（wise-cont-off）は接頭辞必須。
        # 自然文の "stop wise" / "turn off wise" は従来どおり接頭辞不要。
        run("UserPromptSubmit", "/wise-cont")
        self.assertIn("WISE MODE ACTIVE",
                      run("UserPromptSubmit", "wise-cont-off の使い方は?"))
        self.assertTrue(self.flag(".wise-mode").exists())

    def test_question_mentioning_terse_mode_off_does_not_deactivate(self):
        run("UserPromptSubmit", "/terse-mode")
        self.assertIn("TERSE MODE ACTIVE",
                      run("UserPromptSubmit", "terse-mode off とはどういう意味?"))
        self.assertTrue(self.flag(".terse-mode").exists())

    def test_back_to_normal_mode_still_deactivates(self):
        # wise-cont/SKILL.md が案内する "back to normal mode" は行全体一致に
        # 収まるので、アンカー追加後も効き続けること。
        run("UserPromptSubmit", "/wise-cont")
        run("UserPromptSubmit", "back to normal mode")
        self.assertEqual(run("UserPromptSubmit", "go on"), "")

    # ── 頑健性 ───────────────────────────────────────────────────
    def test_inactive_by_default(self):
        self.assertEqual(run("UserPromptSubmit", "fix the login bug"), "")

    def test_unknown_event_is_ignored(self):
        run("UserPromptSubmit", "/wise-cont")
        self.assertEqual(run("Stop"), "")

    def test_broken_stdin_does_not_raise(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            mod.main([__file__, "UserPromptSubmit"], stdin_text="not json")
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
