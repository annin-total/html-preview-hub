# CLAUDE.md - html-preview-hub

ローカルの HTML / LaTeX ファイルを一覧・検索・プレビューするローカル Web アプリ。
サーバーは `hph/`（FastAPI）、フロントエンドは `hph/static/`（ビルド不要のバニラ JS + CSS）。

文書は `docs/` にある。構成・処理フロー・設計判断・セキュリティ設計の正本は `docs/architecture.md`、
API は `docs/api.md`、設定と CLI 引数は `docs/configuration.md`。ルートの `README.md` は人向けの入口。

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt  # 初回のみ
.venv/bin/python -m pytest                           # -k やファイル指定で絞り込み可
uvx ruff check hph tests && uvx ruff format hph tests  # ruff は venv に入っていない

# 実起動での確認。利用者の設定・状態を書き換えないよう、設定ファイルと状態の置き場を隔離する
HPH_STATE_DIR=<一時ディレクトリ> .venv/bin/python -m hph ./sample-docs --port 8899 --no-browser -c <一時ディレクトリ>/cfg.json
# E2E（Playwright が必要）。上の手順で 8899 に起動してから
node tests/e2e/app.e2e.js
```

## Coding

- 依頼範囲外の変更はしない。既存の設計思想を尊重し、差分を最小限に保つ
- 動作要件は Python 3.10 以上。サーバーの依存は FastAPI と uvicorn だけ。フロントエンドに npm やバンドラを持ち込まない
- 破壊的変更を行わない。実施前に承認を求める
- 外部入力はバリデーションする
- 変更後はリンター・テストを実行し、Fail Fast を徹底する
- 関心を分離する。フォルダ・ファイル・クラス・メソッド・関数は責務で分割する
- コードファイルは 200 行以内を目安とする（責務が 1 つなら超えてよい）
- 未使用コードを放置しない
- 型注釈を付ける。例外を握り潰さない
- docstring は原則 1 行（多くても 2 行）。自明なら書かない
- コメントは、込み入ったロジックか、コードから読めず失うと事故になる理由にだけ書く。作業の経緯や検証番号を書かない
- 値のハードコードは避けて定数に分離する。ただし過剰にはしない
- 内部関数・内部メソッドは `_` を付けて区別する
- JS / CSS は既存の書式（prettier の既定）に揃える

## Scope

- **機能の追加・不具合の修正（増やす）と、リファクタリング・文書の見直し（減らす）を 1 つの作業に混ぜない**
- 作業中に見つけた依頼範囲外の課題は直さず、完了報告と PR 本文に挙げる
- **文書は常に最新に保つ**：コード・設定・CLI 引数・API・画面を変えたら、同じ PR で `README.md`・`docs/`・この CLAUDE.md の該当箇所を更新する。更新が要らない場合も、該当箇所が無いことを grep で確かめる
- テスト件数のように、変わるたびに古くなる値を文書に書かない
- 文書は一方的に追記しない。直すときは周辺の古い記述・重複の削除とセットにする

## Design

- **プレビューは分離する**：`/raw` のコンテンツは `allow-same-origin` を付けない sandbox iframe に読み込む。PDF だけは内蔵ビューアのために sandbox を外している。理由は `docs/architecture.md`
- **ルートの外を読ませない**：ファイルの解決は `paths.resolve_within_root()` を必ず通す
- **LaTeX にシェルを実行させない**：コンパイルは常に `-no-shell-escape` で走らせる
- **待機時間の大小関係を崩さない**：`WATCH_TIMEOUT_SECONDS < SHUTDOWN_TIMEOUT_SECONDS`（`hph/server.py`）。崩すと停止時にトレースバックが出る。関係は `tests/test_instance.py` が固定している
- **ランチャーの文字コードと改行を保つ**：`launcher/windows/install.ps1` は BOM 付き UTF-8・CRLF、`install.cmd` は ASCII・CRLF。
  Windows PowerShell 5.1 は BOM の無いファイルを cp932 として読む。エディタで開き直して保存すると壊れやすい

## 踏みやすい罠

- `config.json`・`local/`・`.venv/` は git 管理外。`local/` の中身はプロジェクト外を指すシンボリックリンクなので、**削除時にリンクをたどらない**
- 8765 は利用者が普段使うポート。検証には別のポート（8899 など）を使い、`-c` と `HPH_STATE_DIR` で利用者の設定・状態から隔離する
- ホームの並び順はファイルの作成時刻で変わる。`git archive` で取り出すと時刻がそろうため、作業ツリーとは並びが変わる。テストで「先頭のカード」に依存しない
- **緑のテストは証拠にならない。**移した・直したコードがテストに守られているかは、実装を壊して落ちることで確かめる（壊す前にコミットする）

## Git

- 作業前にブランチを切り、PR は作業開始時のブランチへ向ける
- コミットメッセージは `fix:` `refactor:` `test:` `docs:` `style:` `feat:` の接頭辞を付け、日本語で書く
- `git add` は変えたパスだけを明示する（`-A` や `commit -a` を使わない）
