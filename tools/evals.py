#!/usr/bin/env python3
"""evals.py — スキル挙動の実測 eval(fresh fixture で実 claude -p を起動する)

静的テスト(tests/test_skill_review_safety.py ほか)が保証するのは「望ましい
文が SKILL.md に書かれていること」まで。Claude がその手順に従うかは、fresh
session で実際に起動しないと分からない。公式ドキュメントも skill 有効/無効の
baseline 比較を推奨している。

課金される実 API 呼び出しなので、check.sh の既定にも CI にも入れない:

    ./check.sh --evals            # 全件(claude -p を数回起動、要認証)
    ./check.sh --evals wise       # 名前でフィルタ
    python3 tools/evals.py --list # 一覧だけ

これが検証するのは **invocation とマーカー遵守**(起動すべきときに起動し、
MANDATORY マーカーを守り、起動すべきでないときに黙る)であって、出力の
品質ではない。回答の中身の良し悪しは機械判定できないので、ここでは扱わない
— その区別を消して「挙動を検証済み」と読ませないこと。ガードは:
空出力は全ケース不合格、marker だけの応答は min_chars で不合格、wise は
同一プロンプトを skill 導入/未導入の fixture で走らせる enabled/disabled
ペアで判定する。

対象は機械判定可能なマーカー契約を持つ 2 スキル(wise, pr-self-review)のみ。
残るスキルはマーカー契約を定義してから足す — 判定基準の無い eval は
false green 製造機にしかならない。

ponytail: 5 ケースの検知線(手順が丸ごと無視されていないかを見る smoke)。
follow-rate の統計が要るなら反復回数とケース数を増やす形に上げる。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# fixture に配置するスキル。wise は CHECKLISTS/PATTERNS を同梱で参照する。
FIXTURE_SKILLS = ("wise", "pr-self-review")

# 呼び出しごとの上限。eval は 1 問答で終わる想定なので、これを超えるのは
# スキルが暴走している(それ自体が発見)。
MAX_BUDGET_USD = "1"
CALL_TIMEOUT_SECONDS = 600

QUESTION = "配列から重複を取り除く代表的な方法を一言で教えてください。"


@dataclass(frozen=True)
class Eval:
    name: str
    prompt: str
    why: str
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    # fixture に配置するスキル。() は「skill 無効」側の baseline。
    install_skills: tuple[str, ...] = FIXTURE_SKILLS
    # strip 後の最低文字数。marker だけ吐いて回答しない壊れた応答への下限。
    min_chars: int = 1


EVALS = (
    Eval(
        name="wise-enabled",
        prompt=f"/wise {QUESTION}",
        must_contain=("[WISE MODE",),
        min_chars=40,
        why="ペアの有効側: wise/SKILL.md は Visual Indicator を MANDATORY と"
            "定める。min_chars はマーカーだけで回答が無い応答を落とす",
    ),
    Eval(
        name="wise-disabled",
        prompt=f"/wise {QUESTION}",
        install_skills=(),
        must_not_contain=("[WISE MODE",),
        why="ペアの無効側: 同一プロンプトを skill 未導入で実行してもマーカーは"
            "出ない(公式推奨の enabled/disabled baseline 比較)",
    ),
    Eval(
        name="wise-should-not-trigger",
        prompt=QUESTION,
        must_not_contain=("[WISE MODE",),
        why="skill 導入済みでも、/wise の無い素の質問では起動しない",
    ),
    Eval(
        name="pr-self-review-empty",
        prompt="/pr-self-review",
        must_contain=("対象の変更がありません",),
        must_not_contain=("🛑",),
        why="diff-acquisition.md 1-C が定める停止文そのもの。部分一致では"
            "『問題ありません』の類いが誤合格する",
    ),
    Eval(
        name="no-unrequested-skill",
        prompt="REST API とは何ですか?一言で。",
        must_not_contain=("[WISE MODE", "✅ 重大な懸念なし", "🛑"),
        why="定義質問がレビュー系スキルを起動してはならない(should-not-trigger)",
    ),
)


def build_fixture(base: Path, install_skills: tuple[str, ...]) -> Path:
    """指定スキルだけを配置した使い捨ての git リポジトリを作る。

    このリポジトリの CLAUDE.md や hooks を継承させないため、cwd を移す。
    install_skills=() は「skill 無効」の baseline 環境。
    """
    fixture = base / "fixture"
    skills_dest = fixture / ".claude" / "skills"
    skills_dest.mkdir(parents=True)
    for name in install_skills:
        shutil.copytree(ROOT / "skills" / name, skills_dest / name)
    (fixture / "a.txt").write_text("one\n", encoding="utf-8")
    git = ["git", "-C", str(fixture)]
    for args in (
        ["init", "-q", "."],
        ["config", "user.email", "eval@example.com"],
        ["config", "user.name", "eval"],
        ["add", "."],
        ["commit", "-qm", "init"],
        # pr-self-review の merge-base カスケードは main / master を探す。
        ["branch", "-M", "main"],
    ):
        subprocess.run(git + args, check=True, capture_output=True)
    return fixture


def run_eval(case: Eval, fixture: Path) -> tuple[bool, str]:
    """(passed, failure_detail)。判定は stdout のみ(応答本文)に対して行う。"""
    try:
        proc = subprocess.run(
            ["claude", "-p", "--no-session-persistence",
             # personal skill (~/.claude/skills) は project skill に優先する。
             # user source を外さないと、同名スキルがある環境では別物を評価し、
             # disabled 側も実際には disabled にならない。
             "--setting-sources", "project",
             "--max-budget-usd", MAX_BUDGET_USD, case.prompt],
            cwd=str(fixture), capture_output=True, text=True,
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"claude -p timed out after {CALL_TIMEOUT_SECONDS}s"
    if proc.returncode != 0:
        return False, (f"claude -p exited {proc.returncode}: "
                       f"{proc.stderr.strip()[:300]}")

    output = proc.stdout
    if not output.strip():
        # must_not_contain だけのケースを無応答が素通りした実例への対策。
        return False, "empty output — a silent responder must not pass"
    if len(output.strip()) < case.min_chars:
        # マーカーだけ出して回答しない応答が合格した実例への対策。
        return False, (f"output shorter than {case.min_chars} chars — "
                       "a marker-only response must not pass")
    problems = []
    for text in case.must_contain:
        if text not in output:
            problems.append(f"missing required marker: {text!r}")
    for text in case.must_not_contain:
        if text in output:
            problems.append(f"forbidden marker present: {text!r}")
    if problems:
        preview = output.strip()[:400] or "(empty output)"
        return False, "\n".join(problems) + f"\n--- output preview ---\n{preview}"
    return True, ""


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--list" in argv:
        for case in EVALS:
            print(f"  {case.name} — {case.why}")
        return 0

    selected = [c for c in EVALS if not args or any(a in c.name for a in args)]
    if not selected:
        print(f"no eval matches {args}", file=sys.stderr)
        return 1
    if not shutil.which("claude"):
        print("claude CLI not found — evals run the real, authenticated CLI",
              file=sys.stderr)
        return 1

    failures = 0
    print(f"{len(selected)} evals — real claude -p calls, billed\n")
    for index, case in enumerate(selected, 1):
        # eval ごとに新しい fixture = fresh session。前の eval の状態を継がない。
        with tempfile.TemporaryDirectory() as tmp:
            fixture = build_fixture(Path(tmp), case.install_skills)
            passed, detail = run_eval(case, fixture)
        mark = "pass  " if passed else "FAILED"
        print(f"  [{index}/{len(selected)}] {mark}  {case.name}", flush=True)
        if not passed:
            failures += 1
            for line in detail.splitlines():
                print(f"      {line}")

    print()
    if failures:
        print(f"{failures}/{len(selected)} evals failed — "
              "the skill text was not followed at its real surface")
        return 1
    print(f"all {len(selected)} evals passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
