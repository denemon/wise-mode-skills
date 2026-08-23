#!/usr/bin/env python3
"""fix_follow_rate.py — 「直したものを直し直した率」を git 履歴から測る

wise-mode は手順を増やすスキル集なので、増やしただけの効果があるかを
示せないと重いだけになる。唯一の指標としてこれを使う:

    fix-follow rate = 再修正コミット数 / fix 系コミット数
    (再修正 = 直近に触ったファイルを再び fix 系コミットで触ったもの)

低いほど「一度で正しく直せている」。wise-mode 導入前後の同じ長さの期間で
比べる(手順は benchmarks/README.md)。

これは診断用ヒューリスティックであって効果の証明ではない。タスク難度・
人数・コミット分割・メッセージ規約の影響は除けないため、before/after の
差は「調べるきっかけ」として読む。スキルが手順に従うかどうかの検証は
別物で、./check.sh --evals が実測する。

    python3 benchmarks/fix_follow_rate.py --since 2026-01-01 --until 2026-03-01

ponytail: コミットメッセージと変更ファイルだけを見るヒューリスティック。
PR 単位・変更行単位の追跡が必要になったら gh + git log -L に上げる。
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from typing import Any

DAY = 86400

# 英語は接頭辞 (fix: / revert(api): / hotfix ...)、日本語は位置を問わない。
# 「ログイン処理を修正」のように末尾に来るのが普通で、先頭固定だと大半を取り逃す。
# 代償として「バグを作り込まないよう〜」のような否定形も拾うが、前後の期間で
# 同じだけ過大に数えるので比較は成立する。
FIX_SUBJECT = re.compile(r"^(fix|hotfix|bugfix|revert|patch)\b|修正|バグ", re.IGNORECASE)


def parse_log(text: str) -> list[dict[str, Any]]:
    """`git log --pretty=%H%x09%at%x09%s --name-only` の出力を解析する。"""
    commits: list[dict[str, Any]] = []
    for block in text.split("\0"):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        sha, ts, subject = lines[0].split("\t", 2)
        commits.append(
            {"sha": sha, "ts": int(ts), "subject": subject, "files": lines[1:]}
        )
    return commits


def analyze(commits: list[dict[str, Any]], window_days: int = 14,
            measure_from_ts: int | None = None) -> dict[str, Any]:
    """fix 系コミットのうち、window_days 以内に触られたファイルを再度触ったものを数える。

    measure_from_ts より前のコミットは last_touch の seed にだけ使い、
    件数には数えない。境界の 1 日前に触られ 1 日後に修正されたファイルが、
    先行履歴なしだと 0% / ありだと 100% になる取りこぼしの対策
    (main は since - window_days から履歴を取ってここに渡す)。

    commits は履歴順(古→新、`git log --reverse` の出力)前提。timestamp で
    再ソートしない — 同一秒の feat→fix ペアが newest-first 入力のとき
    fix→feat の順で処理され、再修正を見失う(入力順で 0%↔100% が反転した)。
    """
    last_touch: dict[str, int] = {}
    rework = []
    fixes = 0
    measured = 0
    for commit in commits:
        in_window = measure_from_ts is None or commit["ts"] >= measure_from_ts
        if in_window:
            measured += 1
            is_fix = bool(FIX_SUBJECT.search(commit["subject"]))
            fixes += is_fix
            if is_fix:
                recent = [
                    f
                    for f in commit["files"]
                    if f in last_touch and commit["ts"] - last_touch[f] <= window_days * DAY
                ]
                if recent:
                    rework.append({**commit, "reworked": recent})
        for f in commit["files"]:
            last_touch[f] = commit["ts"]

    return {
        "commits": measured,
        "fix_commits": fixes,
        "rework_commits": len(rework),
        # 母数は fix コミット。全コミット割りだと、無関係な feature コミットを
        # 足すだけで率が「改善」する(再修正 1 件のまま 50%→10% になる操作が
        # レビューで実証された)。fix が 0 件なら率は存在しない — 0.0 を返すと
        # 「最良値」に見えてしまう。
        "rate": round(len(rework) / fixes, 4) if fixes else None,
        "window_days": window_days,
        "detail": rework,
    }


MIN_COMMITS = 30
MIN_FIX_COMMITS = 10


def sample_warning(result: dict[str, Any]) -> str:
    """標本が薄いときの警告文。十分なら ""。README の A/B 手順が前提にする。

    率の母数は fix コミットなので、総コミット数だけでは足りない —
    「31 commits / 1 fix」が無警告になる反例が出た。fix 側も見る。
    """
    if result["fix_commits"] == 0:
        return ("警告: fix 系コミットが 0 件。率は N/A — "
                "この期間では何も測れていない。")
    if result["fix_commits"] < MIN_FIX_COMMITS:
        return (f"警告: fix 系コミット {result['fix_commits']} 件 "
                f"(< {MIN_FIX_COMMITS})。母数が薄く、1 件で率が "
                "10 ポイント以上動く。")
    if result["commits"] < MIN_COMMITS:
        return (f"警告: コミット {result['commits']} 件 (< {MIN_COMMITS})。"
                "この標本量では差はノイズに埋もれる。期間を広げること。")
    return ""


def log_command(since: str, until: str | None, path: str) -> list[str]:
    # --reverse: 履歴順(古→新)。newest-first のまま analyze に渡すと、
    # 同一秒の feat→fix ペアで再修正を見失う。
    cmd = [
        "git", "-C", path, "log", "--no-merges", "--reverse",
        "--pretty=format:%x00%H%x09%at%x09%s", "--name-only", f"--since={since}",
    ]
    if until:
        cmd.append(f"--until={until}")
    return cmd


def git_log(since: str, until: str | None, path: str) -> str:
    proc = subprocess.run(log_command(since, until, path),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"git log に失敗: {proc.stderr.strip() or 'unknown error'}")
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", required=True, help="開始日 (例: 2026-01-01)")
    ap.add_argument("--until", help="終了日。省略時は現在まで")
    ap.add_argument("--repo", default=".", help="対象リポジトリ")
    ap.add_argument("--window-days", type=int, default=14, help="「直近」とみなす日数")
    ap.add_argument("--label", default="", help="出力に付ける期間名 (before / after など)")
    ap.add_argument("--verbose", action="store_true", help="該当コミットを列挙")
    args = ap.parse_args()

    try:
        since_date = datetime.date.fromisoformat(args.since)
    except ValueError:
        raise SystemExit(
            f"--since は ISO 形式 (YYYY-MM-DD) で指定する: {args.since!r}。"
            "window 分の先行履歴を取るために日付演算が必要")
    # window 分だけ手前から履歴を取り、last_touch の seed にする。測定開始
    # 直前に触られたファイルへの修正を取りこぼさないため。件数に入るのは
    # measure_from_ts 以降だけ。
    seed_since = (since_date
                  - datetime.timedelta(days=args.window_days)).isoformat()
    measure_from_ts = int(datetime.datetime.combine(
        since_date, datetime.time()).timestamp())
    result = analyze(parse_log(git_log(seed_since, args.until, args.repo)),
                     args.window_days, measure_from_ts)
    label = f"[{args.label}] " if args.label else ""
    print(f"{label}{args.since}..{args.until or 'now'}  window={result['window_days']}d")
    print(f"  commits        : {result['commits']}")
    print(f"  fix commits    : {result['fix_commits']}")
    print(f"  rework commits : {result['rework_commits']}")
    rate = result["rate"]
    rate_text = (f"{rate:.1%} (rework / fix commits)"
                 if rate is not None else "N/A (fix commits = 0)")
    print(f"  fix-follow rate: {rate_text}")
    if result["fix_commits"]:
        # 再修正 1 件で率がどれだけ動くか。before/after の差がこの 2 倍に
        # 満たなければ判定しない(benchmarks/README.md の読み方)。
        print(f"  rate step      : 1 rework = "
              f"{100 / result['fix_commits']:.1f} pts")
    if args.verbose:
        for c in result["detail"]:
            print(f"    {c['sha'][:8]} {c['subject']}  ->  {', '.join(c['reworked'])}")
    warning = sample_warning(result)
    if warning:
        print(warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
