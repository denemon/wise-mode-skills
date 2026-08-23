# wise-mode

[English](README.md) | 日本語

**Claude Code にプロセスを守らせる。** コードを読む前に書かれる変更を減らし、
根本原因を外す修正を減らし、PR を開いた後に見つかる問題を減らす。
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) の
スキルとフックのセット。スキルの起動と必須マーカーはライブ eval
(`./check.sh --evals`)で検査する — これは invocation レベルの検査であって
出力品質の検査ではない。長期的な傾向は git 履歴ベースのヒューリスティック
([benchmarks/](benchmarks/))で追う — 診断であって証明ではない。

7 スキル + 3 フック。継続モードは**フックが維持する**ので、会話が長くなっても
薄れて消えない。

## コンポーネント

| 名前 | 種類 | 説明 |
|------|------|------|
| **wise** | スキル (`/wise`) | アーキテクトモード — 体系的な計画、TDD、敵対的セルフレビュー、品質ゲート(単発タスク向け) |
| **wise-cont** | スキル (`/wise-cont`) | 継続アーキテクトモード — 一度有効化すると `/wise-cont-off` まで持続(フックで維持) |
| **wise-flow** | スキル (`/wise-flow`) | ソースファーストのフロー: recon → plan → implement → validate → security gate → PR gate → handoff を 1 スキルのフェーズとして実行。成果物は `.claude/flow/` に永続化。PR gate は `pr-self-review` を実行し、security gate は `attack-on-hacker` の methodology reference を適用する |
| **attack-on-hacker** | スキル (`/attack-on-hacker`) | 敵対的ソースコードセキュリティレビュー — 脅威モデル、taint 解析(Source → Sink → Sanitizer)、severity rubric、CWE/CVSS、PR 向け Diff Mode |
| **pr-self-review** | スキル (`/pr-self-review`) | PR を開く前の diff セルフレビュー — バグ予防特化、GitHub にそのまま貼れる日本語出力。`/wise-flow` の PR gate も兼ねる |
| **swarm** | スキル (`/swarm`) | 低トークンのサブエージェント編成 — スコープ付きエージェントブリーフと実行可能な swarm ファイルを生成 |
| **terse-mode** | スキル (`/terse-mode`) | 簡潔モード — 技術的内容はそのままに語数を減らす。lite/full/ultra の強度付き(フックで維持) |
| **mode_persistence** | フック | `/wise-cont` と `/terse-mode` をターン・`/compact`・セッション再開をまたいで維持する — 無いとモードは数ターンで薄れる |
| **session_log** | フック(opt-in) | Claude Code セッションを `.claude/log/` に Markdown で記録。書き込み前に秘匿値をマスク。`--with-session-log` 指定時のみインストール |
| **flag_guard** | フック | 事前承認済み read-only コマンドのフラグレベルの逸脱(`rg --pre`、`git --output`、グローバル `git -c`、スキャナのレポートフラグ)を遮断 — prefix-match の `allowed-tools` が検査できない層 |

## クイックインストール

**プロジェクトルート**(`.git/` のある場所)で実行:

```bash
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash

# with the opt-in session-logging hook:
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash -s -- --with-session-log

# reproducible: pin the installer AND the snapshot to the same commit, and
# verify the archive checksum. An installer taken from mutable main can
# disagree with a pinned archive's manifest — take both from one ref.
REF=<commit-sha>
curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh" \
  | WISE_MODE_REF="${REF}" WISE_MODE_SHA256=<archive-sha256> bash
```

インストーラはリポジトリの **tar.gz スナップショットを 1 つ**ダウンロードする
(可変な `main` から 1 ファイルずつ取ると push と交錯して混在バージョンの
ツリーになり得る)。manifest と既存の `settings.local.json` を**配置前に**
検証し、payload 全体を staging に構築してから skill/hook 単位の `mv` で
swap する — 途中で中断されても半コピーの skill は残らない。マージ済みの
フック設定を `.claude/settings.local.json` に書くのは最後のステップ。
どの検査で失敗しても、何もインストールされずに中断する。他のスキルに
統合されたスキル(`dev-with-review`、旧 `/wise-flow-*` 一族)は、上書き時と
同じ同意プロンプトを経てインストール時に削除される — 残しておくと発火し
続けてルーターと競合するため。

`session_log` フックは **opt-in**(`--with-session-log`)。すべてのツール
呼び出しでツールの入出力をディスクに永続化するため、全プロジェクトが
望むものではない。

モードフラグは `.claude/.wise-mode` と `.claude/.terse-mode` に置かれる。
リポジトリが `.claude/` をコミットしているなら両方を `.gitignore` に
追加すること — さもないと有効化したモードがチーム全員に配布される。

### 手動インストール

```bash
# wise
mkdir -p .claude/skills/wise
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/SKILL.md \
  -o .claude/skills/wise/SKILL.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/CHECKLISTS.md \
  -o .claude/skills/wise/CHECKLISTS.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/PATTERNS.md \
  -o .claude/skills/wise/PATTERNS.md

# wise-cont
mkdir -p .claude/skills/wise-cont
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-cont/SKILL.md \
  -o .claude/skills/wise-cont/SKILL.md

# wise-flow (router + phase reference files + independent-review script)
mkdir -p .claude/skills/wise-flow/references .claude/skills/wise-flow/scripts
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/SKILL.md \
  -o .claude/skills/wise-flow/SKILL.md
for phase in source-recon plan implement-review validate security-gate independent-review reviewer_prompt handoff; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/references/${phase}.md" \
    -o ".claude/skills/wise-flow/references/${phase}.md"
done
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/scripts/ai_review.sh \
  -o .claude/skills/wise-flow/scripts/ai_review.sh
chmod +x .claude/skills/wise-flow/scripts/ai_review.sh

# attack-on-hacker
mkdir -p .claude/skills/attack-on-hacker/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/attack-on-hacker/SKILL.md \
  -o .claude/skills/attack-on-hacker/SKILL.md
for ref in methodology diff-mode quick-wins language-hints report-format; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/attack-on-hacker/references/${ref}.md" \
    -o ".claude/skills/attack-on-hacker/references/${ref}.md"
done

# pr-self-review
mkdir -p .claude/skills/pr-self-review/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/pr-self-review/SKILL.md \
  -o .claude/skills/pr-self-review/SKILL.md
for ref in diff-acquisition output-format; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/pr-self-review/references/${ref}.md" \
    -o ".claude/skills/pr-self-review/references/${ref}.md"
done

# swarm
mkdir -p .claude/skills/swarm/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/swarm/SKILL.md \
  -o .claude/skills/swarm/SKILL.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/swarm/references/methodology.md \
  -o .claude/skills/swarm/references/methodology.md

# terse-mode
mkdir -p .claude/skills/terse-mode
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/terse-mode/SKILL.md \
  -o .claude/skills/terse-mode/SKILL.md

# hooks (default set)
mkdir -p .claude/hooks
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/mode_persistence.py \
  -o .claude/hooks/mode_persistence.py
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/flag_guard.py \
  -o .claude/hooks/flag_guard.py

# session_log hook — opt-in only (it writes tool output to disk)
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/session_log.py \
  -o .claude/hooks/session_log.py
```

続いて、フック設定を `.claude/settings.local.json` に追加する:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" UserPromptSubmit",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" SessionStart",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\" PreToolUse",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`session_log` フックに opt-in した場合は、さらに次のイベントを同じ
`"hooks"` オブジェクトにマージする:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" PostToolUse",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" Stop",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`timeout` は**秒**であってミリ秒ではない — 4 桁の値を書くと、ハングした
フックがセッションを 1 時間以上塞ぎ得る。

## wise — アーキテクトモード

Claude Code で `/wise` と打つと、エージェントは**単発タスク**向けの
アーキテクトモードに切り替わる:

- **考えてから書く** — 理解に 70%、コーディングに 30%
- **8 フェーズのワークフロー** — 計画から PR 準備まで
- **TDD の強制** — RED / GREEN / REFACTOR サイクル
- **敵対的セルフレビュー** — 「これが並行に 2 回走ったら?」
- **軽量モード** — 単純で低リスクな変更では自動的に縮退

```
/wise implement user authentication with JWT
```

| フェーズ | 内容 |
|---------|------|
| 1. **理解と計画** | プロジェクトのドキュメントを読み、複雑さを評価し、計画を作る |
| 2. **コードベース探索** | 既存パターンを把握し、API の実在を確認し、影響範囲を特定する |
| 3. **TDD** | 失敗するテストを先に書き、最小実装、その後リファクタ |
| 4. **実装** | 既存パターン(定数・ログ・エラー処理)に従って構築 |
| 5. **テスト検証** | 適切なテストスイートを実行し、リグレッションを修正 |
| 6. **ドキュメント** | ドキュメントと、明示的に要求された GitHub issue を更新 |
| 7. **コミット前レビュー** | 敵対的セルフレビューのチェックリスト |
| 8. **PR 準備** | diff をセルフレビュー。PR を開くのは明示要求時のみ |

単純な変更(単一ファイル、50 行未満、インターフェース変更なし)は自動的に
フルの手順をスキップし、フェーズ 1・4・7 だけが走る。

### スキルファイル

| ファイル | 役割 |
|---------|------|
| `SKILL.md` | フェーズ、原則、他 2 ファイルを読むタイミング |
| `CHECKLISTS.md` | フェーズ別チェックリスト、敵対的質問、テスト戦略表、`gh` コマンド |
| `PATTERNS.md` | TOCTOU、トランザクション副作用、変異耐性アサーション、characterization テストの具体コード |

`SKILL.md` は意図的に短い。詳細は 2 つの reference ファイルに置かれ、
フェーズが必要とするときに読まれる — 長いスキルファイルは文脈で薄まり、
後半のフェーズが飛ばされる。

## wise-cont — 継続アーキテクトモード

一度有効化すると、**以後のすべてのメッセージ**がアーキテクトモードの基準で
処理される — 毎回 `/wise` と打つ必要はない。

```
/wise-cont
```

エージェントはリクエストごとに評価し、適切なレベルを適用する:

| リクエストの種類 | 適用モード |
|----------------|-----------|
| 質問・議論(コード変更なし) | Q&A — アーキテクト思考の原則のみ |
| 単一ファイル、50 行未満、低リスク | Lightweight — フェーズ 1・4・7 |
| 複数ファイル、明確なスコープ | Full — フェーズ 1–8 |
| 複雑(4+ ファイル、スキーマ変更等) | Full; issue only on explicit request |

`/wise-cont-off` または「normal mode」で解除。

**スコープ**: モードはプロジェクト単位のフラグ(`.claude/.wise-mode`)に
保存され、`/compact`・`/clear`・Claude Code の再起動を生き延びる。誰かが
切るまで有効で、後続セッションや同じプロジェクトの別セッションにも及ぶ。
単発タスクには `/wise` を使うこと。

## wise-flow — ソースファースト開発フロー

`/wise-flow` は 1 つのスキルで、各フェーズの手順はルーターが読み進める
reference ファイルに置かれている。個別の `/wise-flow-*` コマンドはもう
存在しない — 旧版は `install.sh` が削除する。

| フェーズ | 手順 | 成果物 | 書き込み先 |
|---------|------|--------|-----------|
| source-recon | `references/source-recon.md` | Evidence Pack | `.claude/flow/source-recon.md` |
| plan | `references/plan.md` | Implementation Plan | `.claude/flow/plan.md` |
| implement-review | `references/implement-review.md` | Change Pack | `.claude/flow/implement-review.md` |
| validate | `references/validate.md` | Validation Report | `.claude/flow/validate.md` |
| security-gate | `references/security-gate.md` → `attack-on-hacker` の methodology を適用 | Security Gate Report | `.claude/flow/security-gate.md` |
| independent-review | `references/independent-review.md` → `scripts/ai_review.sh` を実行 | Independent Review Report | `.claude/flow/independent-review.md` |
| pr-gate | `pr-self-review` スキル | PR Readiness Report | `.claude/flow/pr-gate.md` |
| handoff | `references/handoff.md` | Handoff Note | `.claude/flow/handoff.md` |

両ゲートは独自の手法を再導出せずに委譲する: PR gate は `pr-self-review` を
実行し、security gate は `attack-on-hacker/references/methodology.md` を
Diff Mode で読み、その severity rubric と evidence level をそのまま通す。
セキュリティ基準は 2 つではなく 1 つ。methodology がスキルの `SKILL.md`
ではなく副作用のない reference に置かれているのは、`attack-on-hacker` が
ユーザー起動専用であり、その `allowed-tools` の事前承認を
`/attack-on-hacker` の外で決して有効化しないため。complex ルートの `swarm`
も同じ扱いで、明示的な委譲要求があるとき wise-flow はスキルを起動せず
`swarm/references/methodology.md` を読む。

### 成果物の永続化

各フェーズは成果物を `.claude/flow/` に書くので、`/compact` 後に再開した
セッションは完了済みフェーズをやり直さない。無効化ルールは 2 種類あり、
互換ではない:

| クラス | フェーズ | 再利用条件 |
|--------|---------|-----------|
| context | source-recon, plan | タスクが不変 — コード編集後も有効 |
| result | implement-review, validate, security-gate, pr-gate, handoff | タスクが不変 **かつ** worktree の fingerprint が一致 |

キャッシュされた Validation Report や Security Gate Report が「コードの
現状」として提示されることはない — worktree が変わればそのフェーズは
再実行される。`/wise-flow reset` でディレクトリをクリアできる。

最初の書き込み前にフローは `git check-ignore .claude/flow/` を確認し、
パスが追跡されていれば知らせる。これらのファイルはソース抜粋と findings を
含む。`.gitignore` を勝手に編集することはない。

### コスト上限

フローはフェーズを増やすので上限を持つ: フェーズあたり `Read`/`Grep`/`Glob`
**25 回**、fix → 再ゲートのループは **3 周**まで。上限に達すると停止して
選択肢を出す — 予算を上げる、ここまでの証拠で進めてギャップを記録する、
スコープを絞る。同じゲートの 3 周目の失敗は、再試行ではなく診断が誤って
いると報告される。

通常ルート:

```text
source-recon -> plan -> implement-review -> validate -> optional security-gate -> pr-gate -> optional handoff
```

任意の分岐は合うときだけ使う:

| 状況 | ルート |
|------|--------|
| 小さい/普通のコード変更 | `source-recon -> plan -> implement-review -> validate -> pr-gate` |
| 分離可能な書き込みスコープを伴う明示的な委譲要求 | `source-recon -> plan -> swarm -> implement-review -> validate -> pr-gate` |
| セキュリティに敏感な変更 | `source-recon -> plan -> implement-review -> validate -> security-gate -> pr-gate` |
| 外部 AI レビューの明示要求 | `... -> validate -> independent-review -> pr-gate` |
| 既存 diff のレビューのみ | `pr-gate` |
| 未完の作業・セッション引き継ぎ | `handoff` |

finding は実装へループバックする:

```text
finding -> implement-review -> validate -> relevant gate again
```

フェーズが成果物を作れないときは、推測で進まず、ブロックしている未知を
説明して停止する。

```text
/wise-flow add rate limiting to the login endpoint
/wise-flow fix this failing test from source read to PR review
/wise-flow just run recon and find where this bug comes from
/wise-flow run only the PR gate on my final diff
```

1 フェーズだけでなく、コード開発の完全な経路が欲しいときに使う。
PR gate は準備状況を報告する。明示的に要求しない限り、PR の作成・push・
オープンは行わない。

### Independent review(任意ゲート)

外部 AI レビューを明示的に求めたときだけ、フローは
`references/independent-review.md` を実行する: `scripts/ai_review.sh` 経由で
**別の Claude インスタンス**(`claude -p`)を起動する — セッションの文脈も
設定も受け取らず、diff だけを見るレビュアー。スクリプトは stdout に JSON の
スコアと findings を、失敗時は stderr に JSON エラーと非ゼロ終了を返す。

ゲートは `claude -p` コマンドを自前で組み立てず、スクリプトを呼ぶ。
巨大 diff の拒否、システムプロンプト抽出、レスポンス解析の実装が 1 箇所に
なる。巨大 diff は coverage manifest 付きの完全なファイル/hunk チャンクで
扱い、partial review never passes the gate(部分レビューがゲートを通ることは
ない)。他の失敗は報告され、即興の再試行で回避されることはない。

レビュアーは diff を 0–100 で採点し、severity 別(critical/high/medium/
low/info)の findings を返す。critical と high は implement-review →
validate に戻して修正し、最終 diff はこのゲートの再実行を通す必要がある。
外部レビュアーへの diff 送信は毎回、正確な `--diff-file` を表示する Bash
権限プロンプトを通る — wise-flow は何も事前承認せず、求められない限り
このゲートは走らない。

このゲートは廃止された `dev-with-review` スキルの後継。`install.sh` は
アップグレード時に旧 `dev-with-review` インストールを削除する。

## attack-on-hacker — 敵対的セキュリティレビュー

`/attack-on-hacker` と打つと、エージェントは許可されたソースコードを
ブラックハットの思考でレビューし、結果を防御的な findings に変換する:
現実的な攻撃経路、証拠、影響、修正、検証手順。武器化されたペイロードは
出さない — 出力は常に修復重視。

```
/attack-on-hacker review the auth flow in src/auth/
/attack-on-hacker audit this PR for security regressions
```

| フェーズ | 内容 |
|---------|------|
| **Diff Mode**(任意) | PR/ブランチ diff のレビュー時は全フェーズを変更コードにスコープし、静かに弱められた制御(外された auth gate、`verify=False`、緩められた CORS 等)を狩る |
| 1. **スコープ + 脅威モデル** | エントリポイント、信頼境界、攻撃者プロファイル、除外する既存緩和策 |
| 1.5. **Quick-Wins スイープ** | 高シグナルの速攻パス: コードと git 履歴の秘匿値、CI の pwn-request パターン、コンテナ衛生、IaC デフォルト、依存監査 |
| 2. **攻撃者マップ** | 全候補に Source → Sink → Sanitizer の taint 解析を必須化 |
| 3. **高リスククラスの捜索** | OWASP 系カテゴリ + 言語/フレームワーク固有の sink(Node, Django, Spring, Go, Rust, SQL) |
| 4. **妥当性の証明** | Pre-Report Sanity Gate — 到達可能性、sanitizer の不在、現実的な前提、evidence taxonomy |
| 5. **報告** | Top-3 Fix-First、Severity Rubric、finding ごとの CWE + CVSS |

### 主な特徴

- **脅威モデルが先** — 明示的な攻撃者プロファイル(`anon-external`、`authenticated-low-priv`、`cross-tenant`、`admin-or-insider`、`compromised-dependency`)。severity はそこに接地する
- **Source → Sink → Sanitizer** — すべての finding が 3 つを明示する。欠けたら疑いであってバグではない
- **Evidence taxonomy** — `confirmed-by-poc`(実行済みローカル PoC)/ `confirmed-by-read`(`file:line` 付きの完全なデータフロー)/ `inferred-pattern`(severity 自動格下げ)
- **偽陽性の規律** — 到達可能性、上流 sanitizer、現実的な前提の確認を報告前に必須化
- **finding ごとの CWE + CVSS** — トリアージツール連携用。CVSS と食い違うときは Severity Rubric が勝つ
- **Diff Mode** — PR レビュー向けの `[regression]` / `[new-surface]` / `[pre-existing]` 分類
- **JSON 出力** — ツール連携用の任意 `--format=json`

### 権限モデル — 既知の限界

`allowed-tools` のエントリは prefix ルールで、コマンドの先頭にしか一致せず
フラグを検査できない(cannot inspect flags)。2 層で補う:

1. 事前承認リストは read-only の形に固定され、フラグで write / execute
   プリミティブに化けるコマンドを意図的に除外する: `rg`(`--pre <cmd>` は
   ファイルごとにコマンドを実行)とレポートを書くスキャナ(`gosec`,
   `trufflehog`, `gitleaks`, `checkov`, `tfsec`, `bandit`)は一切事前承認
   されず、通常の権限プロンプトを通る。ranged な `git diff *` /
   `git log *` / `bundle audit *` も消えた: `--output` と `--ext-diff` は
   書き込み/実行になり、`bundle audit update` は advisory DB を変更し、
   `--out${GAP}put` 型の展開はあらゆる文字列レベルの検査をすり抜ける —
   だから素の flagless 形だけが事前承認され、ranged diff はプロンプトを
   出す。スキル自体が明示起動専用(`disable-model-invocation: true`)
   なので、ユーザーが `/attack-on-hacker` と打たない限りこれらの権限は
   有効化されない。
2. `flag_guard` PreToolUse フック(`install.sh` がインストール)は、既知の
   フラグレベルの逸脱を事前承認済み prefix の*後ろ*に現れても機械的に
   遮断する: `rg -n --pre <cmd>`、`git log --output=<path>`、グローバル
   `git -c key=value`、`git --exec-path`、監査スキャナのレポート出力
   フラグ。`$`・バッククォート・`{` を含むフラグトークンも拒否する —
   ガードは展開前の文字列を見るので、展開可能なフラグは安全と検証
   できない。このフックは defense in depth であって権限境界ではない:
   内部エラー時は fail-open で、フックのタイムアウトはブロックしない。
   フック無しで危険になるものは何も事前承認されていない。

deny テーブルは既知ベクタの一覧であって証明ではない。信頼できない/
サードパーティのコードをレビューするとき — セキュリティレビューが見るのは
まさにそれ — は多層防御を保つ: Bash を拒否した状態か sandbox 化した
チェックアウトでスキルを走らせ、`.git` や `.claude` ディレクトリを同梱した
ダウンロード済みツリーは、それらを捨ててからレビューする。

### スキルファイル

| ファイル | 役割 |
|---------|------|
| `SKILL.md` | 薄いラッパー: 権限(`/attack-on-hacker` 起動時のみ有効)と methodology へのポインタ |
| `references/methodology.md` | 手法そのもの — フェーズ、脅威モデル、taint 語彙、sanity gate、severity rubric。副作用なし。`/wise-flow` の security gate も読む |
| `references/diff-mode.md` | PR/ブランチのスコープ、regression hunt、new-surface の問い |
| `references/quick-wins.md` | 秘匿値、CI/CD、コンテナ、IaC、依存関係のチェック |
| `references/language-hints.md` | スタック固有の sink(Node, Python, Java, Go, Rust, SQL) |
| `references/report-format.md` | レポートテンプレート、findings なしテンプレート、JSON スキーマ |

### 使いどころ

| 状況 | 推奨 |
|------|------|
| コードベース/モジュールのフルセキュリティ監査 | `/attack-on-hacker` |
| PR / ブランチ diff のセキュリティチェック | `/attack-on-hacker review this PR`(自動で Diff Mode) |
| 認証・認可・暗号・デシリアライズ・パーサの変更 | `/attack-on-hacker` |
| 依存関係・IaC の変更 | `/attack-on-hacker`(Quick-Wins スイープが両方カバー) |
| セキュリティ以外の実装作業 | `/wise` または `/wise-flow` |

## pr-self-review — PR 前セルフレビュー

`/pr-self-review` と打つと、エージェントは **取得した diff** —
明示したブランチ / PR / コミット範囲、引数なしなら未追跡ファイルを含む
現在の worktree 全体 — を PR を開く前にレビューする。バグ予防に特化する —
理想論でも、大規模リファクタ提案でも、粗探しでもない。GitHub の PR
コメントにそのまま貼れる粒度で findings を出す。**レポートは日本語**。

```
/pr-self-review                # diff between current branch and base (origin/main → main → master)
/pr-self-review feature/foo    # diff of the specified branch
/pr-self-review #123           # diff of GitHub PR #123 (uses `gh pr diff`)
/pr-self-review abc123...def456
```

### フェーズ

| フェーズ | 内容 |
|---------|------|
| 1. **diff 取得** | 手順は `references/diff-acquisition.md`: 引数の形でルート判定、base 解決(`git merge-base` カスケード: `origin/main` → `origin/master` → `main` → `master`)、取得、規模確認。2000 行超の diff は黙って止まらず、進め方(full / chunked / abort)をユーザーに聞く |
| 2. **最小の文脈読解** | 各 hunk の判定に必要な周辺コードだけを読む — コードベース全体は読まない。`Read`/`Grep` は 10 回まで |
| 2-B. **呼び出し元スイープ** | diff が公開シグネチャ・型・レスポンス形・DB スキーマを変えたときだけ: 変更シンボル(最大 5)を `Grep` して diff 外の呼び出し元を探す。**後方互換の判定にのみ**使い、呼び出し元自体は批評しない。15 回まで。1 シンボル 20 箇所超は未確認として記録 |
| 3. **観点別スキャン** | バグ / Null 安全 / 分岐網羅 / エラー処理 / 非同期 / 既存仕様破壊 / 境界値 / 性能 / セキュリティ / 命名 / 可読性 — シグナルの無い観点はスキップ |
| 4. **選別** | 好みの問題を落とし、diff 外の問題を落とし、リファクタ提案を落とし、未検証の疑いは降格 |
| 5. **出力** | `references/output-format.md` の GitHub 貼り付け可能な Markdown — 判定行 + 🛑 must-fix / ⚠️ verify / 💭 unconfirmed / ✅ good |

### ハードルール

- ❌ diff 外コードへの批評はしない — フェーズ 2-B の呼び出し元スイープが
  唯一の例外で、それも「この diff がその呼び出し元を壊す」の指摘のみ可
- ❌ 「全部リファクタしろ」「設計を見直せ」の提案はしない
- ❌ 単独の「テストを書け」コメントはしない(具体的なバグシナリオとセットのみ)
- ❌ 好みレベルの命名・可読性の指摘はしない(誤読が現実的な場合のみ)
- ❌ 件数稼ぎの粗探しはしない
- ✅ すべての指摘に**特定の行**、**具体的な失敗シナリオ**、**最小の修正案**が必要 — 揃わなければ出さない
- ✅ 指摘ゼロの出力は許容され、diff がきれいなら期待される

### スキルファイル

| ファイル | 役割 |
|---------|------|
| `SKILL.md` | スコープルール、ハードルール、レビュー観点、フェーズ、振る舞い |
| `references/diff-acquisition.md` | フェーズ 1 の実務 — 引数ルーティング、base 解決、規模確認 |
| `references/output-format.md` | 日本語 PR コメントテンプレートと PR Readiness Report テンプレート |

### 出力セクション

- **🛑 PR前に修正推奨** — PR を開く前に直すべきもの
- **⚠️ 要確認(挙動次第で問題化)** — おそらく問題ないが、著者が前提を確認すべきもの
- **💭 未確認の懸念** — diff 外の調査が必要。文脈としてのみ共有
- **✅ 良かった点** — 任意。本当に特筆すべきときだけ

### wise-flow の PR gate として

`/wise-flow` から呼ばれると、同じスキルが出力を **PR Readiness Report**
(判定 / スコープ / must-fix / verify / unconfirmed)に切り替え、diff の
範囲・検証状況・(必要なら)セキュリティゲートの結果がすべて判明するまで
`ready` を宣言しない。

### 使い分け

| 状況 | 推奨 |
|------|------|
| push / PR 直前の diff の最終チェック | `/pr-self-review` |
| ソースファーストフロー内の PR gate | `/wise-flow` — このスキルを呼び、PR Readiness Report を要求する |
| 別の Claude インスタンスによる、より独立したレビュー | `/wise-flow`(independent-review gate、明示要求時) |
| セキュリティ特化の diff レビュー | `/attack-on-hacker`(Diff Mode) |
| 変更自体のアーキテクト設計 + TDD | `/wise` |

## swarm — 並列委譲モード

`/swarm` と打つと、明示的に委譲したいタスク向けのコンパクトな並列作業計画を
作る:

- **低トークンの探索** — エージェント境界の決定に必要なファイルだけ読む
- **競合安全な所有権** — 各エージェントに明示的な書き込みスコープ
- **実行可能な出力** — 人間向けの `.swarm/plan.md` と実行可能な `.swarm/run.sh` を生成
- **最小の有効な swarm** — 単純な作業を過剰分割しない

```text
/swarm build agents for this feature
/swarm break this task into parallel workers
```

サブエージェントや並列実行が欲しいときに使う。通常のシングルエージェントの
コーディングには使わない。

## terse-mode — 簡潔モード

`/terse-mode` と打つと、エージェントは簡潔さ優先の応答スタイルに切り替わる:

- **技術的内容は同じ** — 埋め草を削り、正確な用語・コマンド・エラーは保つ
- **3 段階の強度** — `lite`、`full`、`ultra`
- **自動明瞭化** — 破壊的操作と安全警告では一時的に通常の言い回しに戻り、他スキルが定義する構造化レポートは決して圧縮しない(severity ラベルや必須フィールドは埋め草ではない)
- **言語維持** — 翻訳を頼まれない限りユーザーの言語のまま
- **永続** — フックが毎ターン強度を再注入するので、`/compact`・`/clear`・再開を生き延びる

```text
/terse-mode
/terse-mode lite
/terse-mode ultra
/terse-mode off      # or "normal mode"
```

修正内容や理由を失わずに、速く締まった回答が欲しいときに使う。

## mode_persistence — 継続モードフック

`/wise-cont` と `/terse-mode` は「持続する」と言う。フック無しでは持続
しない: 指示はモデルの作業文脈からスクロールアウトし、モードは数ターンで
静かに減衰する。`mode_persistence.py` はそれをハーネスのレベルで解決する。

| イベント | 動作 |
|---------|------|
| `UserPromptSubmit` | `/wise-cont`、`/terse-mode [level]`、その解除を検出。フラグを書き込み/削除し、有効なモードのリマインダーを**毎**プロンプトに注入 |
| `SessionStart` | `startup`、`resume`、`clear`、`compact`、`fork` でリマインダーを再注入 |

- フラグ: `.claude/.wise-mode`、`.claude/.terse-mode`(プロジェクト単位、各 1 行)
- 「normal mode」は**両方**のモードを同時に切る
- 2 つのモードは独立 — terse を切っても wise は動き続ける
- 失敗は意図的に握りつぶす: 壊れたフックがセッションを止めてはならない

## session_log — セッションロガー(フック、opt-in)

`session_log.py` は Claude Code のツール使用を `.claude/log/` に Markdown で
記録する。**デフォルトインストールには含まれない**: すべてのツール呼び出しで
入出力をディスクに永続化するため、`install.sh --with-session-log`(または
手動配線)で求めたときだけインストールされる。

### 仕組み

- **PostToolUse フック** — すべてのツール呼び出しをタイムスタンプ・入力・実行結果つきで記録
- **Stop フック** — Claude の応答間にターン区切りを追加
- **セッション検出** — `session_id` でエントリをグループ化。セッションごとに 1 ファイル
- **マスク** — コマンド出力は書き込み前にマスクされ、`cat .env`、
  `Authorization` ヘッダ、`postgres://user:pass@host` URL、発行元の分かる
  トークン(`sk-`、`ghp_`、`xoxb-`、`AKIA`…)、PEM 秘密鍵はログに残らない。
  何を実行しどこへ接続したかは読めるまま、秘匿値だけが `«redacted»` に置換される

> **マスクは secret scanner ではない。** 上記のよくある形を狙い、過小より
> 過剰にマスクする。メールアドレス等の個人情報は削除**しない**し、珍しい
> 形式の秘匿値は通り抜け得る。`.claude/log/` は機密として扱うこと:
> コミットに入れず、本物のカバレッジが必要なら `gitleaks` / `trufflehog` を
> 使う。

### 記録内容

| ツール | 記録内容 |
|--------|---------|
| **Bash** | コマンド、説明、実行結果(`<details>` 折りたたみ) |
| **Edit** | ファイルパス、diff(`- old` / `+ new`) |
| **Grep** | パターン、パス、glob フィルタ、マッチ結果 |
| **Glob** | パターン、パス、マッチしたファイル |
| **Read** | ファイルパス |
| **Write** | ファイルパス |
| **Agent** | 種類、説明、プロンプト |
| **Skill** | スキル名、引数 |
| **その他** | ツール名、入力 JSON、結果 |

### ログ形式

ログは `.claude/log/session-<hash>.md` に保存される — 名前はセッション ID
だけから導出されるので、並行セッションが共有レジストリを奪い合うことは
なく、日付をまたぐセッションも 1 ファイルに収まる:

````markdown
# Claude Code Session Log
**Date:** 2026-03-20
**Start:** 14:30:22
**Project:** my-project
**Session:** abcdef1234567890

---

### [14:30] `Bash` — Run unit tests
```bash
npm test
```
<details><summary>result</summary>

```
PASS src/app.test.ts
  ✓ renders correctly (12ms)
Tests: 1 passed
```
</details>

### [14:31] `Edit` — `src/app.ts`
```diff
- const x = 1
+ const x = 2
```

### [14:32] `Grep` — `handleError` in `src/` (`*.ts`)
```
src/app.ts:42:  handleError(err)
src/utils.ts:10:export function handleError(e: Error) {
```

---
> Turn ended at 14:32:45
````


## 効果の測定

これらのスキルはプロセスを*増やす*。数字が無ければ「丁寧になった気がする」
しか残らない — だから指標はちょうど 1 つ: **fix-follow rate**、直前に
変更されたファイルを再度触る fix コミットの割合。

```bash
python3 benchmarks/fix_follow_rate.py --since 2026-01-01 --until 2026-04-01 --label before
python3 benchmarks/fix_follow_rate.py --since 2026-04-01 --until 2026-07-01 --label after
```

wise-mode 採用前の期間と、同じ長さの採用後の期間を測る。各期間に 30 コミット
**かつ 10 fix コミット**以上が必要。rework 1 件で rate は 100 / fix-commits
ポイント動く(`rate step` として出力される)。差が 2 期間の step の大きい方の
2 倍未満なら効果なしとみなす。プロトコル、解釈、既知の限界は
[benchmarks/README.md](benchmarks/README.md) にある。

## 開発

1 コマンドですべて検証する — `bash -n`、`shellcheck`、Python 構文、
3 つのテストスイート:

```bash
./check.sh            # everything, ~22s
./check.sh --fast     # skips the slow integration suites, ~3s
./check.sh --mutants  # audits the guards themselves, ~2.5min
./check.sh --evals    # runs real claude -p against the skills (billed) — on demand
```

各スイートはタイムアウト付きで走る。ここでのハングは常に再帰 — テストが
テストランナーを起動する構造 — を意味し、以前は無言の停止として現れた。
今は数秒でそう言って落ちる。

CI も Stop ゲート(後述)も同じスクリプトを実行する。手でチェックを組み
立て直すと範囲が実行者任せになる — 「全テスト成功」が日によって別の意味に
なるのはそのせいだ。

テストは対象コードの隣に置かれるため 3 ディレクトリに分かれるが、
1 スイートずつでも動く:

```bash
python3 -m unittest discover -s hooks        # hooks (session log, mode persistence)
python3 -m unittest discover -s tests        # packaging + installer/script integration
python3 -m unittest discover -s benchmarks   # the metric script
```

`-s hooks` がスイートの大半(マスクのテスト含む)を持つ。`-s tests` だけ
走らせると、それを走らせないまま緑に見える — `check.sh` を使うべき理由が
もう 1 つ。

`tests/` は退屈な壊れ方を捕まえる: frontmatter の `name` がディレクトリと
一致しないスキル、`install.sh` から漏れたスキル、ドキュメントされていない
スキル、ミリ秒で書かれた `timeout`、300 行を超えた `SKILL.md`。スキルを
足したら、まずこのスイートを緑にすること。

`check.sh` 内の shellcheck の glob は新しいスクリプトを自動で拾い、現在の
警告数はゼロ — 新しい警告はそれを持ち込んだ diff のもの。

### Stop ゲート

`.claude/hooks/check_gate.py` は Claude Code がターンを終えようとするときに
`check.sh` を実行する。スイートが赤ならフックは exit 2 で停止をブロックし、
失敗を差し戻す — 検証が失敗している間は変更を「完了」と報告できない。
3 連続失敗で諦めて人間に返し、最後の緑以降に追跡対象ソースが変わって
いなければ実行自体をスキップする — 会話だけのターンはコストゼロ。

ゲートは `check.sh --fast` を回す。遅い統合スイートは CI の仕事。
タイムアウトした実行は緑ではなく *inconclusive* として報告される —
さもないと遅いマシン 1 台が偽の合格をキャッシュしてゲートを恒久停止させる。

**ゲートが緑でも変更が動くとは限らない。** `check.sh` はテストを走らせる
だけで、変更を実際の面で実行しない。だからスイートが通っても、実際に実行
されるファイル — `install.sh`、フック、配布スクリプト — が変わったときは、
ゲートがそれらを名指しして `/verify` を提案する 1 行を出す。変更ごとに
1 回だけ言い、exit code には触れない。Markdown は除外 — プロンプト内容に
実行面は無く、doc 編集のたびに注意されれば人はその行を無視するようになる。

`.claude/skills/verify/SKILL.md` が、このリポジトリで `/verify` が拾う
レシピ。

`.claude/hooks/lint_on_edit.py` は速い方の半分: Edit/Write の `PostToolUse`
で、その 1 ファイルに `bash -n` + `shellcheck`(`.sh`)か `ast.parse`
(`.py`)を実行する。非ブロッキング — 出力して退く。

どちらも `settings.local.json`(ignore 済み、マシンごと)ではなく
`.claude/settings.json`(追跡済み、共有)に配線されている。切りたければ
そこのエントリを消す。どちらのフックも `install.sh` の配布物ではない —
このリポジトリ自身の開発ハーネスである。

### テスト層が冗長に見える理由

3 層あるのは、*unit* テストがコードと共有する誤った仮定を捕まえられない
からだ。フックは `tool_result` を読んでいたが Claude Code は
`tool_response` を送る。ツール出力は一度も記録されず — 128 個のフック
テストは緑のままだった。テストが同じ間違ったキーでペイロードを組み立てて
いたからだ。

| 層 | ファイル | 捕まえるもの |
|----|---------|-------------|
| unit | `hooks/test_*.py` | 関数内のロジック |
| contract | `hooks/test_contract.py` + `hooks/fixtures/*.json` | Claude Code が実際に送るペイロードの形、実出力から乖離した README |
| integration | `tests/test_ai_review.py` | 配布スクリプトを偽 `claude` を PATH に置いて実際に実行 |
| integration | `tests/test_install.py` | ローカル配信したリポジトリに対して `install.sh` を end-to-end 実行 |
| mutation | `tools/mutants.py` | 守っていないガード — 巻き戻しを誰も検出できない「修正」 |

`tools/mutants.py` はこのリポジトリの修正 1 件につき 1 エントリを持つ:
ファイル、正確な文字列、壊したときに何が起きるべきか。
`./check.sh --mutants` は 1 件ずつ当て、気づくべきテストだけを走らせ、
復元する。*生き残った*エントリは、その修正にガードが無く静かに退行する
ことを意味する。初回実行時、8 件中 5 件の修正が生き残った。

変異を登録せずに修正を書くことは、修正を偶然にする方法である。

`.claude/skills/verify/SKILL.md` はこれらを手で動かすレシピ — リポジトリを
インストーラに配信し、本物の pty でプロンプトに答え、本物の `claude` を
シャドウする。手動検証の前に読むこと。

`hooks/fixtures/*.json` が外部ペイロード形の単一の正。テスト内でフック
ペイロードを手組みしないこと — fixture をロードする。形が間違っていれば
ちょうど 1 箇所で、出典の引用つきで間違っている。

`tests/test_ai_review.py` は実行前に本物の `claude` を含む `PATH` エントリを
除去するので、スイートが課金 API 呼び出しをすることはない。

## 要件

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- `python3`(フックとインストーラの設定マージ用)
- `curl` または `wget`(インストーラ用)

## 旧バージョンからのアップグレード

`install.sh` を再実行する。旧バージョンの残置物を掃除する:

- `dev-with-review` スキル — 廃止。外部 AI レビューは `/wise-flow` の任意 `independent-review` ゲートになり、インストーラが `.claude/skills/dev-with-review` を削除する
- 個別の `/wise-flow-*` スキル — 今は `/wise-flow` のフェーズ。`.claude/skills/` から削除される
- `hooks/wise_mode.py` — `mode_persistence.py` に改名。ファイルと古い `settings.local.json` エントリが除去される
- ミリ秒で書かれたフック `timeout`(`5000`)— 意味は秒

それより古いものはここでは管理しない。過去のインストールが
`.claude/skills/caveman`、`.claude/skills/cclog`、`.claude/hooks/cclog-hook.sh`
を残しているなら手で消すこと — インストーラはもう削除コードを持たない。

## アンインストール

```bash
# All components
rm -rf .claude/skills/{wise,wise-cont,wise-flow,attack-on-hacker,pr-self-review,swarm,terse-mode}
rm -f .claude/hooks/session_log.py .claude/hooks/mode_persistence.py .claude/hooks/flag_guard.py
rm -f .claude/.wise-mode .claude/.terse-mode
rm -rf .claude/flow          # wise-flow phase artifacts
rm -rf .claude/log           # session logs (masked, but still sensitive)

# Leftovers install.sh still removes for you
rm -rf .claude/skills/wise-flow-{source-recon,plan,implement-review,validate,security-gate,pr-gate,handoff}
rm -f .claude/hooks/wise_mode.py

# Older still — no longer handled by the installer, remove by hand
rm -rf .claude/skills/caveman .claude/skills/cclog
rm -f .claude/hooks/cclog-hook.sh
```

フックを削除したら、`.claude/settings.local.json` の `hooks` セクションも
削除すること。

## ライセンス

MIT
