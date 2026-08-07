#!/usr/bin/env python3
"""fix_follow_rate.py のユニットテスト（純粋関数のみ、git は叩かない）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fix_follow_rate import DAY, analyze, parse_log

T0 = 1_700_000_000


def commit(sha, day, subject, files):
    return {"sha": sha, "ts": T0 + day * DAY, "subject": subject, "files": files}


class AnalyzeTest(unittest.TestCase):
    def test_fix_soon_after_touch_counts_as_rework(self):
        result = analyze([
            commit("a", 0, "feat: add checkout", ["pay.py"]),
            commit("b", 3, "fix: null total in checkout", ["pay.py"]),
        ])
        self.assertEqual(result["rework_commits"], 1)
        self.assertEqual(result["rate"], 0.5)

    def test_fix_outside_window_is_not_rework(self):
        result = analyze([
            commit("a", 0, "feat: add checkout", ["pay.py"]),
            commit("b", 60, "fix: rounding", ["pay.py"]),
        ], window_days=14)
        self.assertEqual(result["rework_commits"], 0)

    def test_fix_on_untouched_file_is_not_rework(self):
        result = analyze([
            commit("a", 0, "feat: add checkout", ["pay.py"]),
            commit("b", 1, "fix: typo in docs", ["README.md"]),
        ])
        self.assertEqual(result["rework_commits"], 0)
        self.assertEqual(result["fix_commits"], 1)

    def test_japanese_and_conventional_subjects_count(self):
        for subject in ["fix(auth): bypass", "Revert \"feat: x\"", "認証の修正"]:
            with self.subTest(subject=subject):
                result = analyze([
                    commit("a", 0, "feat: x", ["auth.py"]),
                    commit("b", 1, subject, ["auth.py"]),
                ])
                self.assertEqual(result["rework_commits"], 1)

    def test_feature_commit_touching_recent_file_is_not_rework(self):
        result = analyze([
            commit("a", 0, "feat: x", ["auth.py"]),
            commit("b", 1, "feat: y", ["auth.py"]),
        ])
        self.assertEqual(result["rework_commits"], 0)

    def test_empty_history(self):
        self.assertEqual(analyze([])["rate"], 0.0)


class ParseLogTest(unittest.TestCase):
    def test_parses_null_separated_log(self):
        raw = (
            "\x00abc123\t1700000000\tfeat: add thing\nsrc/a.py\nsrc/b.py\n"
            "\x00def456\t1700086400\tfix: thing\nsrc/a.py\n"
        )
        commits = parse_log(raw)
        self.assertEqual([c["sha"] for c in commits], ["abc123", "def456"])
        self.assertEqual(commits[0]["files"], ["src/a.py", "src/b.py"])
        self.assertEqual(commits[1]["subject"], "fix: thing")

    def test_subject_with_tabs_survives(self):
        commits = parse_log("\x00abc\t1700000000\tfix: a\tb\tc\nsrc/a.py\n")
        self.assertEqual(commits[0]["subject"], "fix: a\tb\tc")


if __name__ == "__main__":
    unittest.main()
