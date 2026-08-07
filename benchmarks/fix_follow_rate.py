#!/usr/bin/env python3
"""fix_follow_rate.py — 「直したものを直し直した率」を git 履歴から測る

wise-mode は手順を増やすスキル集なので、増やしただけの効果があるかを
示せないと重いだけになる。唯一の指標としてこれを使う:

    fix-follow rate = 直近に触ったファイルを再び fix 系コミットで触った割合

低いほど「一度で正しく直せている」。wise-mode 導入前後の同じ長さの期間で
比べる(手順は benchmarks/README.md)。

    python3 benchmarks/fix_follow_rate.py --since 2026-01-01 --until 2026-03-01

ponytail: コミットメッセージと変更ファイルだけを見るヒューリスティック。
PR 単位・変更行単位の追跡が必要になったら gh + git log -L に上げる。
"""
from __future__ import annotations

import argparse
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


def analyze(commits: list[dict[str, Any]], window_days: int = 14) -> dict[str, Any]:
    """fix 系コミットのうち、window_days 以内に触られたファイルを再度触ったものを数える。"""
    last_touch: dict[str, int] = {}
    rework = []
    fixes = 0
    for commit in sorted(commits, key=lambda c: c["ts"]):
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

    total = len(commits)
    return {
        "commits": total,
        "fix_commits": fixes,
        "rework_commits": len(rework),
        "rate": round(len(rework) / total, 4) if total else 0.0,
        "window_days": window_days,
        "detail": rework,
    }


def git_log(since: str, until: str | None, path: str) -> str:
    cmd = [
        "git", "-C", path, "log", "--no-merges",
        "--pretty=format:%x00%H%x09%at%x09%s", "--name-only", f"--since={since}",
    ]
    if until:
        cmd.append(f"--until={until}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
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

    result = analyze(parse_log(git_log(args.since, args.until, args.repo)), args.window_days)
    label = f"[{args.label}] " if args.label else ""
    print(f"{label}{args.since}..{args.until or 'now'}  window={result['window_days']}d")
    print(f"  commits        : {result['commits']}")
    print(f"  fix commits    : {result['fix_commits']}")
    print(f"  rework commits : {result['rework_commits']}")
    print(f"  fix-follow rate: {result['rate']:.1%}")
    if args.verbose:
        for c in result["detail"]:
            print(f"    {c['sha'][:8]} {c['subject']}  ->  {', '.join(c['reworked'])}")
    if result["commits"] < 30:
        print("  ! コミットが少なすぎる。期間を延ばさないと差はノイズに埋もれる", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
