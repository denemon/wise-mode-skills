# Phase 1: 差分の取得

レビュー対象の差分を確定させる手順。**Phase 1 に入る前にこのファイルを読み、
そのまま従う。**

このフェーズでは内部変数として **`TARGET_REF`**(レビュー対象 ref)、**`BASE_REF`**(比較元 ref)、
**`RANGE_LABEL`**(出力ラベル用の文字列)を確定させる。以降のフェーズはこれらだけを参照する。

## 1-A. 引数を確認してルートを決定

`$ARGUMENTS` を見て、以下のいずれかのルートに分岐する:

| 引数の形 | ルート | 説明 |
|---|---|---|
| `#123` / `123`(数値) | **PRルート** | `#` を剥がして PR 番号として扱う(下記 1-B-PR) |
| `abc123...def456` | **範囲ルート** | コミット範囲をそのまま使う(下記 1-B-RANGE) |
| `feature/foo` などブランチ名 | **ブランチルート** | `TARGET_REF=feature/foo`(下記 1-B-BRANCH) |
| 指定なし | **HEADルート** | `TARGET_REF=HEAD`(下記 1-B-BRANCH) |

## 1-B. ルートごとの base / range 決定

### 1-B-BRANCH(ブランチルート / HEADルート)

`TARGET_REF` を起点に merge-base のカスケードを行う。各ステップは独立に実行する(ワンライナーで連鎖させない):

1. `git merge-base "$TARGET_REF" origin/main`
2. `git merge-base "$TARGET_REF" origin/master`
3. `git merge-base "$TARGET_REF" main`
4. `git merge-base "$TARGET_REF" master`

> ⚠️ HEAD 基準ではなく **必ず `TARGET_REF` 基準** で merge-base を取ること。
> 現在チェックアウト中のブランチとレビュー対象ブランチが異なる場合に、誤った base を使うと差分がズレる。

最初に成功したものを `BASE_REF`(SHA)とし、以下を設定:

- 明示ブランチの場合:
  - `RANGE = "${BASE_REF}...${TARGET_REF}"`
  - `RANGE_LABEL = "$RANGE"`
  - 差分取得: `git diff "$RANGE"`
  - 規模確認: `git diff --stat "$RANGE"`
- 引数なしの HEAD ルートの場合:
  - `RANGE_LABEL = "${BASE_REF}...HEAD + worktree"`
  - committed / staged / unstaged の取得: `git diff "$BASE_REF"`
  - 未追跡ファイルの列挙: `git ls-files --others --exclude-standard`
  - 列挙した各ファイルを `git diff --no-index -- /dev/null "$path"` で差分に追加する
    (差分ありの終了コード 1 は正常。1 以外は取得失敗として停止する)

HEAD ルートで `git diff "$BASE_REF"` だけを使う理由は、`BASE_REF...HEAD` が
作業ツリーを含まず、PR 作成直前の staged / unstaged 変更を落とすため。

すべての merge-base が失敗した場合は base 不明として停止し、ユーザに明示的な base 指定を依頼する。
`origin/*` を使う場合、リモート未 fetch だと古い base を返す可能性があるため、
必要に応じて `git fetch origin` の実行を提案する(自動 fetch はしない)。

### 1-B-RANGE(範囲ルート)

引数がそのまま範囲。

- `RANGE = "$ARGUMENTS"`(例: `abc123...def456`)
- `RANGE_LABEL = "$RANGE"`
- 差分取得: `git diff "$RANGE"`
- 規模確認: `git diff --stat "$RANGE"`

### 1-B-PR(PRルート)

`gh` ベースで完結させる。git range には変換しない。

1. PR 番号 `<num>` を確定(先頭 `#` は剥がす)
2. `gh pr view <num> --json baseRefName,headRefName,number,title` で base/head を取得(参考情報・表示用)
3. 差分取得: `gh pr diff <num>`
4. ファイル一覧: `gh pr diff <num> --name-only`
5. 規模(追加/削除行数): `gh pr diff <num>` の出力から `^+`(`+++ ` を除く)/ `^-`(`--- ` を除く)を集計、または `gh pr view <num> --json additions,deletions` を利用
6. `RANGE_LABEL = "PR #<num> (<baseRefName>...<headRefName>)"`

`gh` が未インストール / 未認証の場合は **その旨を 1 行で報告して停止**(推測で git ローカルにフォールバックしない)。

## 1-C. 規模確認とユーザ確認

1-B の各ルートで取得した diff に対して、共通で以下を実施する:

1. 変更ファイル一覧と追加/削除行数を把握(HEAD ルートでは未追跡ファイルも含める)
2. **0 行** の場合は「対象の変更がありません」と報告して停止
3. **巨大すぎる(>2000 行)** 場合は、停止せず以下を提示してユーザに選ばせる:
   - (a) このまま全件レビュー(時間がかかる)
   - (b) 変更ファイル単位で N 件ずつ分割レビュー
   - (c) 中止して PR を分割することを推奨

ユーザの応答を得てから Phase 2 に進む。

## 失敗時の振る舞い

- `git` / `gh` が使えない、または差分が取得できない場合は **その旨を1行で報告して停止**
- 推測でレビューを進めない(例: PR ルートで `gh` が使えなくても git ローカルにフォールバックしない)
- base が決定できない場合は 1-B-BRANCH 末尾の通り、停止してユーザに base 指定を依頼する
