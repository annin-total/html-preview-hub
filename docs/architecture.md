# アーキテクチャ

html-preview-hub の内部構成と主要な設計判断をまとめた設計書です。実装の詳細を追う前に、
全体像を把握するために読んでください。

## 1. 概要 / 設計方針

- ローカルの HTML / LaTeX ファイルを一覧・検索・プレビューするための、単一プロセスで完結するローカル Web アプリです。
- サーバーは Python 3.10 以上 + **FastAPI と uvicorn の 2 つだけ**に依存します。フロントエンドはビルド不要のバニラ JS + CSS（ES Modules を直接ブラウザへ配信）で構成し、npm やバンドラは使いません。
- 状態はすべてローカルファイルに永続化します（設定は JSON、お気に入り等のユーザー状態は別の JSON）。データベースや外部サービスへの依存はありません。
- 最小構成で「フォルダを掘って探してブラウザで開く」手作業を代替することを目的とし、機能追加よりも単一バイナリ的な手軽さを優先しています。

## 2. ディレクトリ構成

```
html-preview-hub/
├── README.md
├── pyproject.toml            # パッケージ定義 / pytest 設定
├── requirements.txt          # 実行時依存（fastapi, uvicorn）
├── requirements-dev.txt      # 開発時依存（pytest, httpx）
├── config.example.json       # 設定ファイルのひな形
├── start.sh                  # 仮想環境作成〜起動までのワンコマンドスクリプト
├── hph/                      # バックエンド（Python パッケージ）
│   ├── __main__.py           # CLI エントリポイント（python -m hph）
│   ├── config.py             # 設定の読み書き・ルート管理
│   ├── scanner.py            # 再帰スキャンとタイトル抽出（HTML / LaTeX）
│   ├── tex.py                # LaTeX のエンジン判定・コンパイル・キャッシュ
│   ├── texjobs.py            # LaTeX コンパイルのバックグラウンド実行と状態管理
│   ├── index.py              # インデックス保持・再スキャン・変更通知
│   ├── store.py              # お気に入り / 非表示 / 履歴の永続化
│   ├── paths.py              # パス正規化とトラバーサル対策
│   ├── server.py             # FastAPI ルーティングとファイル配信
│   └── static/               # フロントエンド（ビルド不要）
│       ├── index.html        # SPA シェル
│       ├── css/app.css       # デザイントークンとコンポーネント
│       └── js/
│           ├── app.js        # ルーティング・同期・ショートカット
│           ├── api.js        # API クライアント
│           ├── state.js      # 状態管理と検索インデックス
│           ├── util.js       # DOM / 整形ユーティリティ
│           ├── virtual-list.js  # 固定行高の仮想スクロール
│           └── views/        # home / tree / preview / settings
├── sample-docs/              # 動作確認用のサンプル（HTML と LaTeX）
├── docs/                      # ドキュメント（本書・API 仕様・設定・使い方・スクリーンショット）
└── tests/                     # pytest（+ 任意の Playwright E2E）
```

各モジュールの責務は次のとおりです。

| モジュール | 責務 |
| --- | --- |
| `config.py` | 設定ファイルの探索・読み書き・ルートフォルダの追加/削除、既定値の一元管理 |
| `scanner.py` | ルート配下の再帰スキャンと、HTML / LaTeX からのタイトル抽出（`(mtime, size)` キャッシュ付き） |
| `tex.py` | LaTeX エンジンの判定・コンパイル実行・PDF キャッシュの管理 |
| `texjobs.py` | コンパイルをバックグラウンドジョブとして実行し、状態を保持する（ファイル単位で相乗り、異なるファイルは並列） |
| `index.py` | スキャン結果のスナップショット保持、バックグラウンド再スキャン、変更のロングポーリング通知 |
| `store.py` | お気に入り / 非表示フォルダ / 最近開いたファイルの永続化（スレッドセーフな KVS） |
| `paths.py` | URL 由来の相対パスの正規化とディレクトリトラバーサル対策 |
| `server.py` | FastAPI のルーティング定義、`/raw` によるファイル配信、静的アセットの提供 |
| `static/js/*` | SPA のルーティング・状態管理・検索・各画面（home / tree / preview / settings）の描画 |

## 3. 処理フロー

1. **起動**: `python -m hph` が `Config.load()` で設定ファイルを読み込み、CLI 引数を上書きしたうえで `create_app()` に渡し、uvicorn でサーバーを起動します。
2. **初回スキャン**: FastAPI の `lifespan` から `IndexService.start()` が呼ばれ、`scanner.scan()` を別スレッド（`asyncio.to_thread`）で実行してスナップショットを作ります。
3. **インデックス保持と変更検知**: スナップショットは `IndexService` がメモリ上に保持し、内容が変わるとリビジョン番号を進めます。`watch_interval_seconds` が正の値なら、バックグラウンドタスクが一定間隔で再スキャンを実行します。フロントエンドは `GET /api/index/watch?revision=N` へロングポーリングし、リビジョンが進む（またはタイムアウトする）まで応答を待つことで手動リロード無しの自動追従を実現しています。
4. **プレビュー要求**: フロントエンドが `GET /raw/{rootId}/{path}` を叩くと、`paths.resolve_within_root()` でルート配下の実パスに解決したうえで `server.py` がファイルを配信します。相対パス参照はそのまま解決され、ルート絶対パス（例 `/assets/app.css`）は `Referer` ヘッダーから元のルートを推測して救済します。
5. **LaTeX プレビュー**: `.tex` を開くと `POST /api/tex/compile` が呼ばれ、`texjobs.TexJobRegistry` がバックグラウンドジョブを起動します。呼び出しは完了を待たずに返り、フロントエンドは `GET /api/tex/job` で状態をポーリングします。コンパイル本体は `tex.compile_tex()` が別スレッドで実行し、エンジンを判定したうえで生成物をソース内容とエンジン名のハッシュ（fingerprint）でキャッシュします。完了したらフロントエンドは `pdfUrl`（`GET /api/tex/pdf`）を iframe に読み込みます。ジョブはファイル単位で、同じファイルへの要求が重なると 1 本に相乗りします。異なるファイルどうしはセマフォの範囲で並列に走り、待っている間も他のファイルの表示・操作は妨げられません。

## 4. 主要な設計判断

- **スキャン**: `os.scandir` で反復します。タイトルは先頭 64KB のみ読み、`(mtime, size)` をキーにキャッシュするため、再スキャン時に読み直すのは変更されたファイルだけです（5,100 ファイルで初回 134ms / 再スキャン 166ms）。
- **描画**: ホームは 48 件ずつ追記描画（`IntersectionObserver`）、サイドバーは固定行高の仮想スクロール。5,100 ファイルでも DOM 上の行は 40 行程度に保たれます。
- **プレビューの分離**: `sandbox="allow-scripts allow-forms allow-modals allow-popups allow-downloads allow-popups-to-escape-sandbox"`。`allow-same-origin` を付けないので unique origin となり、アプリ本体の DOM・localStorage には触れません。`localStorage` を使うページ向けにツールバーの「分離 / 互換」で切り替えられます（互換モードは分離レベルが下がります）。
- **LaTeX**: マジックコメント（`% !TEX program = ...`）→ プリアンブル（`luatexja` / `xeCJK` / `jsarticle` など）→ 既定順、の優先度でエンジンを選びます。コンパイルは常に `-no-shell-escape` で実行し、`\write18` は使えません。生成物は「ソース内容 + エンジン」のハッシュをキーにキャッシュするため、内容が変わらない限り再コンパイルしません（日本語 lualatex 文書で初回 12 秒 → 2 回目 101ms → キャッシュ 0.4ms）。`\documentclass` の無い断片ファイルはコンパイルせず、その旨とソース表示を案内します。
- **PDF の表示**: PDF はサンドボックス iframe ではブラウザ内蔵ビューアが無効化されるため、PDF のみ `sandbox` を付けずに表示しています。PDF ビューアは親ページの DOM やストレージへアクセスできないため、分離は保たれます。
- **エラー処理**: 壊れた HTML はブラウザがそのまま描画し、読めない・消えたファイルはプレビュー領域にエラーカードを出すだけでアプリは動き続けます。LaTeX のコンパイル失敗はエラー箇所を含むログを画面上で確認できます。状態ファイル（`state.json`）が壊れていても既定値で起動しますが、設定ファイル（`config.json`）が不正な場合はフォールバックせずエラー終了します（詳細は [./configuration.md](./configuration.md)）。

## 5. セキュリティ設計

- **プレビューの分離**: `/raw` 配下のコンテンツは既定で `allow-same-origin` を付けない `sandbox` 属性の iframe に読み込みます。これにより unique origin となり、プレビュー対象の CSS / JS はアプリ本体の DOM・localStorage・Cookie に一切干渉できません。
- **パストラバーサル対策**: `paths.resolve_within_root()` が `..` や絶対パスを拒否し、解決後の実パスがルート配下に収まっているかを検証します。ルート外へのシンボリックリンクも拒否されます（`follow_symlinks` が有効な場合を除く）。
- **シェルエスケープの禁止**: LaTeX のコンパイルは常に `-no-shell-escape` を付けて実行し、`\write18` によるシェルコマンド実行を許しません。
- **バインド先**: 既定のバインド先は `127.0.0.1` です。`--host 0.0.0.0` で公開すると、`/api/browse` を含めローカルのファイル情報が同一ネットワークへ露出するため、信頼できるネットワーク以外では避けてください。

## 関連ドキュメント

- [../README.md](../README.md)
- [./api.md](./api.md) — HTTP API 仕様
- [./configuration.md](./configuration.md) — 設定
- [./usage.md](./usage.md) — 使い方
