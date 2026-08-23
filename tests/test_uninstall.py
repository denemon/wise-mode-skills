#!/usr/bin/env python3
"""uninstall.sh の統合テスト

install.sh と同じ理由で実行して確かめる: 削除・配線解除・保全は走らせて
初めて分かる層。test_install の _InstallHarness を再利用してローカル配信の
本物の install.sh を最後まで走らせ、その結果に uninstall.sh をかける。

アンインストールの順序は install の逆で「settings の配線解除 → ファイル削除」。
途中で死んでも残るのは不活性なファイルだけで、消えた hook を settings が
指し続ける状態(全プロンプトでエラー)にはならない。

対話プロンプト(--yes なし)の経路は pty が要るのでここでは扱わない —
test_install と同じ方針。非対話では read が /dev/tty を開けず明確に
中断することだけ、環境に tty が無い CI で観測される。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from test_install import _InstallHarness

ROOT = Path(__file__).resolve().parent.parent


class _UninstallHarness(_InstallHarness):
    def setUp(self):
        super().setUp()
        self.uninstall_script = self.proj / "uninstall.sh"
        shutil.copy(ROOT / "uninstall.sh", self.uninstall_script)

    def uninstall(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        run_env = {**os.environ, **(env or {})}
        return subprocess.run(
            ["bash", str(self.uninstall_script), *args], cwd=self.proj,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=60, env=run_env,
        )

    def read_settings(self) -> dict:
        return json.loads(
            (self.proj / ".claude" / "settings.local.json").read_text(encoding="utf-8"))


class UninstallScriptIntegrationTest(_UninstallHarness, unittest.TestCase):
    """削除・配線解除・保全"""

    def test_full_uninstall_reverses_a_fresh_install(self):
        self.assertEqual(self.install().returncode, 0)

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        claude = self.proj / ".claude"
        self.assertEqual(sorted(p.name for p in claude.iterdir()),
                         ["settings.local.json"],
                         "配布物以外が残った/消えた")
        self.assertEqual(self.read_settings().get("hooks", {}), {},
                         "配線が残っている")

    def test_uninstall_removes_opted_in_session_log(self):
        self.assertEqual(self.install("--with-session-log").returncode, 0)

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.proj / ".claude" / "hooks").exists())
        self.assertEqual(self.read_settings().get("hooks", {}), {})

    def test_uninstall_preserves_third_party_wiring_and_settings(self):
        # install と同じ教訓: 完全一致で外す。session_log.py に言及するだけの
        # 第三者 hook (/opt/acme/session_log.py) や無関係の設定キーは残す。
        self.assertEqual(self.install().returncode, 0)
        settings_path = self.proj / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        third_party = "python3 /opt/acme/session_log.py PostToolUse"
        settings["hooks"].setdefault("PostToolUse", []).append(
            {"hooks": [{"type": "command", "command": third_party, "timeout": 10}]})
        settings["permissions"] = {"allow": ["Bash(ls:*)"]}
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        merged = self.read_settings()
        commands = [
            hook.get("command", "")
            for entries in merged.get("hooks", {}).values()
            for entry in entries
            for hook in entry.get("hooks", [])
        ]
        self.assertEqual(commands, [third_party], "第三者の配線が消された/正規配線が残った")
        self.assertEqual(merged.get("permissions"), {"allow": ["Bash(ls:*)"]},
                         "無関係の設定キーが消された")

    def test_user_owned_skill_is_not_touched(self):
        self.assertEqual(self.install().returncode, 0)
        mine = self.proj / ".claude" / "skills" / "my-notes"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: my-notes\n---\n", encoding="utf-8")

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((mine / "SKILL.md").is_file(), "無関係のスキルが消された")

    def test_legacy_leftovers_are_swept(self):
        # 旧名 wise_mode.py と廃止スキルが残る古い環境からのアンインストール。
        self.assertEqual(self.install().returncode, 0)
        claude = self.proj / ".claude"
        (claude / "hooks" / "wise_mode.py").write_text("# legacy\n", encoding="utf-8")
        legacy = claude / "skills" / "dev-with-review"
        legacy.mkdir()
        (legacy / "SKILL.md").write_text("---\nname: dev-with-review\n---\n",
                                         encoding="utf-8")

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in claude.iterdir()),
                         ["settings.local.json"])

    def test_state_flags_removed_data_dirs_kept(self):
        # モードフラグは消す(uninstall はモードを止める)。ログと flow の
        # 成果物はデータなので消さず、相対パスの片付けコマンドだけ案内する。
        self.assertEqual(self.install("--with-session-log").returncode, 0)
        claude = self.proj / ".claude"
        (claude / ".wise-mode").write_text("wise\n", encoding="utf-8")
        (claude / ".terse-mode").write_text("full\n", encoding="utf-8")
        (claude / "log").mkdir()
        (claude / "log" / "session.md").write_text("output\n", encoding="utf-8")
        (claude / "flow").mkdir()
        (claude / "flow" / "plan.md").write_text("plan\n", encoding="utf-8")

        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((claude / ".wise-mode").exists())
        self.assertFalse((claude / ".terse-mode").exists())
        self.assertEqual((claude / "log" / "session.md").read_text(encoding="utf-8"),
                         "output\n", "ログが消された")
        self.assertEqual((claude / "flow" / "plan.md").read_text(encoding="utf-8"),
                         "plan\n", "flow 成果物が消された")
        # 案内は相対パス固定 — 絶対パスの補間はプロジェクトパスに空白が
        # あるとコピペで複数引数の rm になる(install.sh と同じ教訓)。
        self.assertIn("rm -r .claude/log", result.stdout)
        self.assertNotIn(f"rm -r {self.proj}", result.stdout)

    def test_clean_project_is_a_safe_noop(self):
        result = self.uninstall("--yes")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to remove",
                      (result.stdout + result.stderr).lower())
        self.assertEqual(list((self.proj / ".claude").iterdir()), [],
                         "何も無いのに何かが作られた")

    def test_malformed_settings_abort_before_any_removal(self):
        # install と同じ原則: 検証は操作前。壊れた settings で途中まで消して
        # 止まると、配線だけ残って全プロンプトがエラーになる。
        self.assertEqual(self.install().returncode, 0)
        settings_path = self.proj / ".claude" / "settings.local.json"
        settings_path.write_text("{not json", encoding="utf-8")

        result = self.uninstall("--yes")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid json",
                      (result.stderr + result.stdout).lower())
        self.assertTrue(
            (self.proj / ".claude" / "skills" / "wise" / "SKILL.md").is_file(),
            "中断したのに削除が走った")
        self.assertTrue(
            (self.proj / ".claude" / "hooks" / "mode_persistence.py").is_file())
        self.assertEqual(settings_path.read_text(encoding="utf-8"), "{not json",
                         "壊れた settings が書き換えられた")

    def test_unknown_option_is_rejected(self):
        self.assertEqual(self.install().returncode, 0)

        result = self.uninstall("--yse")  # typo は黙って無視しない

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            (self.proj / ".claude" / "skills" / "wise" / "SKILL.md").is_file(),
            "typo なのに削除が走った")


if __name__ == "__main__":
    unittest.main()
