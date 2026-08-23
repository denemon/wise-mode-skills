#!/usr/bin/env python3
"""fix_follow_rate.py のユニットテスト（純粋関数のみ、git は叩かない）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fix_follow_rate import (
    DAY, MIN_COMMITS, MIN_FIX_COMMITS, analyze, log_command, parse_log,
    sample_warning,
)

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
        # 母数は fix コミット(1 件中 1 件が再修正)。全コミット割りではない。
        self.assertEqual(result["rate"], 1.0)

    def test_unrelated_feature_commits_do_not_dilute_the_rate(self):
        # レビューで実証された操作: 再修正 1 件のまま feature を 8 件足すと
        # 全コミット割りでは 50% → 10% に「改善」する。母数を fix に固定して
        # この操作を無効化する。
        base = [
            commit("a", 0, "feat: add checkout", ["pay.py"]),
            commit("b", 3, "fix: null total in checkout", ["pay.py"]),
        ]
        padding = [
            commit(f"p{i}", 30 + i, "feat: unrelated work", [f"other{i}.py"])
            for i in range(8)
        ]
        self.assertEqual(analyze(base)["rate"], analyze(base + padding)["rate"])

    def test_no_fix_commits_means_no_rate(self):
        # fix 0 件で 0.0 を返すと「最良値」に見える。率は存在しない = None。
        result = analyze([commit("a", 0, "feat: x", ["a.py"])])
        self.assertIsNone(result["rate"])

    def test_pre_window_history_seeds_last_touch(self):
        # 反例: 測定開始 1 日前に触られ、1 日後に修正された同じファイルが、
        # 先行履歴なしでは 0%、含めると 100% になった。seed は last_touch
        # にだけ効き、件数には入らない。
        result = analyze([
            commit("a", -1, "feat: x", ["pay.py"]),
            commit("b", 1, "fix: x", ["pay.py"]),
        ], measure_from_ts=T0)
        self.assertEqual(result["commits"], 1)
        self.assertEqual(result["fix_commits"], 1)
        self.assertEqual(result["rework_commits"], 1)
        self.assertEqual(result["rate"], 1.0)

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
        self.assertIsNone(analyze([])["rate"])

    def test_same_second_commits_follow_input_history_order(self):
        # 反例: git log は newest-first で、timestamp の安定ソートはその順序を
        # 保存する。同一秒の feat→fix が fix→feat のまま処理され、同じ 2
        # コミットで入力順を変えるだけで 0%↔100% が反転した。analyze は
        # 並べ替えず、git log --reverse の履歴順をそのまま信頼する。
        pair = [
            commit("a", 0, "feat: x", ["pay.py"]),
            commit("b", 0, "fix: x", ["pay.py"]),
        ]
        self.assertEqual(analyze(pair)["rework_commits"], 1)
        self.assertEqual(analyze(list(reversed(pair)))["rework_commits"], 0)

    def test_log_command_requests_history_order(self):
        self.assertIn("--reverse", log_command("2026-01-01", None, "."))


class SampleWarningTest(unittest.TestCase):
    def test_thin_fix_denominator_warns_even_with_many_commits(self):
        # 反例: 「31 commits / 1 fix」が無警告だった。率の母数は fix なので、
        # 総コミット数だけ見ても標本の薄さは分からない。
        warning = sample_warning({"commits": 31, "fix_commits": 1})
        self.assertIn("警告", warning)
        self.assertIn("fix", warning)

    def test_zero_fixes_warns_as_not_measurable(self):
        self.assertIn("N/A", sample_warning({"commits": 31, "fix_commits": 0}))

    def test_few_total_commits_warns(self):
        self.assertIn("警告", sample_warning(
            {"commits": MIN_COMMITS - 1, "fix_commits": MIN_FIX_COMMITS}))

    def test_sufficient_sample_is_silent(self):
        self.assertEqual(sample_warning(
            {"commits": MIN_COMMITS, "fix_commits": MIN_FIX_COMMITS}), "")


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
