#!/usr/bin/env python3
"""check_gate.py — Stop フック: 検証が赤いまま「完了」と言わせない

このリポジトリの開発用ハーネス。配布物ではない（install.sh は配らない）。

なぜ必要か: CLAUDE.md の実行ループも SKILL.md の指示も prompt レベルの制御で、
このリポジトリ自身が wise-cont/SKILL.md:35 で「フック無しでは数ターンで消える」
と書いている種類のもの。実際、同じセッションで 6 回「問題ない」と報告して
6 回とも欠陥が残っていた。停止をブロックできるのはフックだけ。

契約（公式 hook-development ドキュメントで確認）:
  exit 0 → 停止を許す
  exit 2 → 停止をブロックし、stderr がモデルに差し戻される

安全弁を 3 つ持たせてある。ゲートがセッションを人質に取らないため:
  1. 3 回連続で失敗したら降参して人間に渡す（CLAUDE.md の「三回で止まる」と一致）
  2. ソース（追跡＋未追跡）が前回の緑から変化していなければ check.sh を走らせない
     （会話だけのターンは無料。全層は約 20 秒かかる）
  3. check.sh がハングしてもタイムアウトで通す
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

STATE_NAME = ".check-gate"
MAX_ATTEMPTS = 3
STDERR_TAIL_LINES = 40

# ゲートは `--fast`（約 2 秒、統合スイート 2 つを除外）を走らせる。フルは
# 実測 24〜66 秒で、ターンごとに払うには重すぎるうえ、環境差でタイムアウトに
# 触れる。取りこぼす層（install.sh と ai_review.sh の統合テスト）は CI が見る。
CHECK_ARGS = "--fast"
CHECK_TIMEOUT = 45

# 再帰ガード。check.sh はテストスイートを走らせ、その中にはこのゲートを
# 起動するテストがある。`CLAUDE_PROJECT_DIR` は子プロセスに継承されるので、
# 何もしないと内側のゲートが同じリポジトリを検証し直して止まらなくなる
# （実際に踏んだ。5 分でも終わらなかった）。
RECURSION_ENV = "WISE_MODE_CHECK_GATE_ACTIVE"


def audit_lock_path(root: Path) -> Path:
    """tools/mutants.py:lock_path と同じ場所。フックからツールを import しない
    方針なので数行だけ複製している（_state_dir と同じ理由）。"""
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"wise-mode-mutants-{digest}.lock"


def audit_in_progress(root: Path) -> bool:
    """変異監査が走っているか。

    監査はライブツリーを書き換える。その最中に検証すると壊れた木を見て嘘の
    失敗を出す（実測: 偽 FAILED）。ゲートは自動発火するので、手動で監査を
    回している間にターンが終わるとこれが起きる。

    パスの決め方は tools/mutants.py:lock_path と同じ。フックからツールを
    import しない方針なので数行だけ複製している（_state_dir と同じ理由）。
    """
    lock = audit_lock_path(root)
    try:
        pid = int(lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # 落ちた監査の残骸
    except PermissionError:
        return True
    return True


def project_root(payload: dict) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return Path(root)


def source_fingerprint(root: Path) -> str | None:
    """追跡＋未追跡ファイルの内容ハッシュ。git が無ければ None（＝常に検証する）。

    未追跡（.gitignore 除外後）も含める。check.sh のテスト発見はファイル
    システム走査なので未追跡の test_*.py も実行される。追跡分しか見ないと
    「緑の記録後に未追跡ファイルだけを壊した」状態で digest が変わらず、
    ゲートが check.sh をスキップして緑のまま停止を許す。
    """
    names: set[bytes] = set()
    for extra in ((), ("--others", "--exclude-standard")):
        try:
            names.update(subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", *extra],
                capture_output=True, timeout=30, check=True,
            ).stdout.split(b"\0"))
        except (OSError, subprocess.SubprocessError):
            return None

    digest = hashlib.sha256()
    for name in sorted(names):
        if not name:
            continue
        digest.update(name)
        try:
            digest.update((root / name.decode()).read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def runtime_surfaces(root: Path) -> dict[str, str]:
    """実際に実行されるファイルと、その内容ハッシュ。

    `/verify` の surface 表に合わせてある。Markdown（プロンプト本体）と tests/ は
    含めない — `/verify` 自身が docs-only は SKIP と言っている。
    """
    patterns = ("install.sh", "check.sh", "hooks/*.py", ".claude/hooks/*.py",
                "skills/*/scripts/*", "benchmarks/*.py")
    surfaces: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or path.name.startswith("test_"):
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            surfaces[path.relative_to(root).as_posix()] = digest
    return surfaces


def surface_notice(state: dict, surfaces: dict[str, str]) -> tuple[str, dict]:
    """(stdout に出す文言, 次の状態) を返す純関数。

    テストが緑でも、それは「回帰していない」しか言っていない。実行される面が
    変わったのに一度も走らせていない、という状態を 1 度だけ知らせる。
    停止は止めない — 終了コードには関与しない。

    実際、このセッションで見つかった「追跡済みログには .gitignore が効かない」は
    どのテストにも引っかからず、実際にインストーラを走らせて初めて出た。
    """
    known = state.get("surfaces")
    if not isinstance(known, dict):
        return "", {**state, "surfaces": surfaces}  # 初回は記録だけ

    changed = sorted(name for name, digest in surfaces.items()
                     if known.get(name) != digest)
    if not changed:
        return "", state

    message = (
        "[gate] runtime surfaces changed since the last recorded run:\n"
        f"         {', '.join(changed)}\n"
        "       Tests passed, but nothing was executed. Consider /verify."
    )
    return message, {**state, "surfaces": surfaces}


def carry_forward(previous: dict, state: dict) -> dict:
    """`decide` が組み直した state に、実行面の記録だけを引き継ぐ。

    `decide` は自分が使うキーだけで state を作り直す。落とすと毎回「初回」扱いに
    なり通知が一度も出ない（実装中に踏んだ）。
    `green_fingerprint` は引き継いではいけない — 判定不能のときに再検証させる
    ためにわざと捨てている。
    """
    if "surfaces" in previous:
        state.setdefault("surfaces", previous["surfaces"])
    return state


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def decide(state: dict, fingerprint: str | None, run) -> tuple[int, str, dict]:
    """(終了コード, stderr に出す文言, 次の状態) を返す純関数。

    `run` は呼ぶと (status, output) を返す callable。status は
    "pass" / "fail" / "inconclusive" の 3 値。

    **2 値にしてはいけない。** 当初 timeout を「合格」に丸めていたところ、遅い
    環境で 1 回タイムアウトしただけで緑の fingerprint が保存され、以降ゲートが
    検証を永久にスキップした。判定不能は合格ではない。
    """
    if fingerprint is not None and state.get("green_fingerprint") == fingerprint:
        return 0, "", state  # 前回の緑から何も変わっていない

    status, output = run()

    if status == "pass":
        return 0, "", {"green_fingerprint": fingerprint, "attempts": 0}

    if status == "inconclusive":
        # 停止は止めない（セッションを人質にしない）が、緑として記録もしない。
        # 次のターンで必ずもう一度試みる。
        return 0, f"check.sh did not produce a verdict: {output}\n" \
                  "Verification did NOT run — do not treat this as green.", \
               {"attempts": int(state.get("attempts", 0))}

    attempts = int(state.get("attempts", 0)) + 1
    tail = "\n".join(output.strip().splitlines()[-STDERR_TAIL_LINES:])

    if attempts >= MAX_ATTEMPTS:
        message = (
            f"check.sh failed {attempts} times in a row — handing back.\n"
            "Three corrections without progress means the diagnosis is wrong.\n"
            "Stop and ask for direction instead of trying a fourth time.\n\n"
            f"{tail}"
        )
        return 0, message, {"attempts": 0}

    message = (
        f"check.sh FAILED (attempt {attempts}/{MAX_ATTEMPTS}). "
        "Do not report this work as complete.\n"
        "Fix the failure, then stopping will be allowed again.\n\n"
        f"{tail}"
    )
    return 2, message, {"attempts": attempts}


def main(stdin_text: str | None = None) -> int:
    raw = sys.stdin.read() if stdin_text is None else stdin_text
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if os.environ.get(RECURSION_ENV):
        return 0  # check.sh の内側から呼ばれた。ここで走らせると止まらない。

    root = project_root(payload)
    script = root / "check.sh"
    if not script.is_file():
        return 0  # 別プロジェクトで誤って有効になっている

    state_path = root / ".claude" / STATE_NAME

    def run_check() -> tuple[str, str]:
        if audit_in_progress(root):
            # 監査中のツリーは一時的に壊れている。緑とも赤とも言えない。
            return "inconclusive", "mutation audit is running"
        try:
            proc = subprocess.run(
                [str(script), CHECK_ARGS], cwd=str(root), capture_output=True,
                text=True, timeout=CHECK_TIMEOUT,
                env={**os.environ, RECURSION_ENV: "1"},
            )
        except subprocess.TimeoutExpired:
            return "inconclusive", f"timed out after {CHECK_TIMEOUT}s"
        except OSError as exc:
            return "inconclusive", f"could not run: {exc}"
        return ("pass" if proc.returncode == 0 else "fail"), proc.stdout + proc.stderr

    previous = load_state(state_path)
    code, message, state = decide(previous, source_fingerprint(root), run_check)

    state = carry_forward(previous, state)

    # 緑のときだけ通知する。赤や判定不能のときは先に直すことがある。
    if code == 0 and not message:
        notice, state = surface_notice(state, runtime_surfaces(root))
        if notice:
            print(notice)

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # 状態を保存できなくても判定は済んでいる

    if message:
        sys.stderr.write(message + "\n")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # ゲートの不具合でセッションを止めない
        sys.stderr.write(f"check_gate error (ignored): {exc}\n")
        sys.exit(0)
