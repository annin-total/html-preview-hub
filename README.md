# html-preview-hub

ローカルのあちこちに散らばった **HTML / LaTeX** ファイル（AI が生成した使い捨てのものから、
残しておきたい資料まで）を **1 つの画面で横断・検索・即プレビュー**するためのローカル Web アプリ。

「フォルダを掘って、ファイルを探して、ブラウザで開く（LaTeX ならさらに手でコンパイルする）」という
ポチポチ作業をなくすことが目的です。

![ホーム](docs/screenshots/home.png)

| 検索（インクリメンタル） | HTML プレビュー |
| --- | --- |
| ![検索](docs/screenshots/search.png) | ![プレビュー](docs/screenshots/preview.png) |

| LaTeX プレビュー（自動コンパイル） | コンパイルエラーのログ |
| --- | --- |
| ![TeX プレビュー](docs/screenshots/tex-preview.png) | ![TeX ログ](docs/screenshots/tex-error.png) |

## 特徴

- **フォルダカードのホーム画面** — フォルダ単位でカード表示。件名（HTML の `<title>` / LaTeX の `\title`）、件数、日付が一覧で分かる。
- **インクリメンタルサーチ** — フォルダ名・パス・ファイル名・タイトルを横断。ヒット箇所をハイライトし、一致したファイルをカード内で先頭に出す。
- **インラインプレビュー** — 外部ブラウザを開かず、アプリ内の iframe に表示。`iframe` は既定で `allow-same-origin` なしのサンドボックスなので、プレビュー対象の CSS / JS はアプリ本体に一切干渉できない。
- **LaTeX の自動コンパイル** — `.tex` を選ぶとサーバー側で PDF にして同じ画面に表示する。エンジン（pdflatex / xelatex / lualatex / uplatex / tectonic）はマジックコメントとプリアンブルから自動判定し、結果は内容ハッシュでキャッシュするので 2 回目以降は即表示。失敗したらエラー箇所を含むログをその場で開ける。
- **相対パス・ルート絶対パスの解決** — プレビュー対象と同じ階層の画像 / CSS / JS はそのまま読める。`/assets/app.css` のようなルート絶対パス参照も Referer から解決する。
- **即応する切り替え** — 一度開いたファイルは iframe プールに残るため、行き来しても再読み込みが起きない。サイドバーは仮想スクロールで数千件でも軽い。
- **お気に入り / 非表示フォルダ / 種類フィルタ** — 残したいものに星を付け、ノイズになるフォルダはカード右クリックで隠し、HTML と TeX はチップで切り替える。
- **自動追従** — バックグラウンドで再スキャンし、変更があればロングポーリングで画面に反映（手動リロード不要）。
- **設定は UI からもファイルからも** — 対象フォルダの追加・削除、対象拡張子、除外フォルダ、階層の深さなどを画面上で編集し、JSON 設定ファイルに保存する。

## 動作要件

- Python 3.10 以上（3.11 / 3.13 で確認）
- 依存パッケージは **FastAPI と uvicorn の 2 つだけ**（フロントエンドはビルド不要のバニラ JS + CSS）
- LaTeX の PDF プレビューを使う場合のみ、TeX エンジンを別途インストール（任意）

```bash
# 最小構成（英数字の文書）
sudo apt install texlive-latex-base latexmk        # Debian / Ubuntu
brew install --cask mactex-no-gui                  # macOS

# 日本語文書（ltjsarticle / jsarticle など）も扱う場合
sudo apt install texlive-lang-japanese texlive-luatex texlive-latex-extra
```

エンジンが無い環境でも一覧・検索・HTML プレビューはそのまま動き、`.tex` は「ソースを表示」で中身を確認できます。

## 起動

### 一番簡単な方法

```bash
git clone https://github.com/annin-total/html-preview-hub.git && cd html-preview-hub
./start.sh ~/Documents/html     # 仮想環境作成 → 依存インストール → 起動 → ブラウザが開く
```

引数を省略すると `config.json`（無ければ同梱の `sample-docs/`）を対象に起動します。

### 手動で行う場合

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 対象フォルダを指定して起動（--save で設定ファイルに保存）
python -m hph ~/Documents/html --save

# 設定ファイルの内容で起動
python -m hph

# ポートやホストを変える / ブラウザを自動で開かない
python -m hph ~/Documents/html --port 9000 --host 127.0.0.1 --no-browser
```

起動すると `http://127.0.0.1:8765/` が開きます。対象フォルダは起動後に画面右上の ⚙ からも追加できます。

### 主なコマンドライン引数

| 引数 | 説明 |
| --- | --- |
| `roots...` | スキャン対象フォルダ（複数指定可） |
| `-c, --config PATH` | 設定ファイルのパス |
| `--save` | 引数で渡したフォルダを設定ファイルへ保存 |
| `--host` / `--port` | バインド先（既定 `127.0.0.1:8765`） |
| `--no-browser` | 起動時にブラウザを開かない |
| `--reload` | 開発用オートリロード |

## 設定

設定ファイルは次の順で解決します。

1. `--config` で指定したパス
2. 環境変数 `HPH_CONFIG`
3. カレントディレクトリの `config.json`
4. `~/.config/html-preview-hub/config.json`

`config.example.json` をコピーして使ってください。

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `roots` | `[]` | `{ "name": 表示名, "path": フォルダ }` の配列 |
| `include_extensions` | `[".html", ".htm", ".xhtml"]` | 一覧に載せる拡張子 |
| `ignore_dirs` | `.git`, `node_modules`, `dist` など | 走査しないフォルダ名 |
| `ignore_globs` | `[]` | 除外する相対パスの glob |
| `max_depth` | `16` | 潜る階層の上限 |
| `max_files` | `50000` | 読み込むファイル数の上限 |
| `follow_symlinks` | `false` | シンボリックリンクを辿るか |
| `watch_interval_seconds` | `4.0` | 自動再スキャン間隔（`0` で無効） |
| `host` / `port` | `127.0.0.1` / `8765` | 待ち受け先 |
| `open_browser` | `true` | 起動時にブラウザを開く |
| `tex_enabled` | `true` | LaTeX の PDF プレビューを使うか |
| `tex_engine` | `"auto"` | 使用エンジン。`auto` は自動判定、`pdflatex` などで固定 |
| `tex_use_latexmk` | `true` | latexmk があれば利用する（参照解決の再実行を任せる） |
| `tex_use_sibling_pdf` | `true` | `.tex` と同じ場所に新しい PDF があればそれを表示する |
| `tex_max_passes` | `2` | latexmk を使わないときのコンパイル回数 |
| `tex_timeout_seconds` | `90` | 1 回のコンパイルの上限時間 |
| `tex_cache_limit` | `200` | 保持する PDF キャッシュの数 |
| `tex_cache_dir` | 状態ディレクトリ配下 | PDF キャッシュの置き場所 |

お気に入り・非表示フォルダ・履歴は設定とは別に `~/.local/state/html-preview-hub/state.json`
（`HPH_STATE_DIR` で変更可）に保存されます。

## キーボードショートカット

| キー | 動作 |
| --- | --- |
| `/` または `Ctrl` / `⌘` + `K` | 検索にフォーカス |
| `↑` / `↓` | ファイルを移動（プレビュー画面） |
| `Enter` | 開く |
| `Esc` | 一覧へ戻る / 検索解除 |
| `r` | プレビューを再読み込み（LaTeX は強制再コンパイル） |
| `u` | ソース表示の切り替え |
| `l` | コンパイルログの切り替え（LaTeX） |
| `f` | お気に入り切り替え |
| `[` | サイドバーの表示切り替え |
| `,` | 設定を開く |
| カード右クリック | フォルダの非表示切り替え |

※ プレビュー（iframe）内をクリックするとキー入力はプレビュー側へ渡ります。ショートカットを使うときは
サイドバーやツールバーを一度クリックしてください。

## ディレクトリ構成

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
├── docs/screenshots/         # README 用スクリーンショット
└── tests/                    # pytest（+ 任意の Playwright E2E）
```

## API

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/api/index` | フォルダ / ファイル / ルート / ユーザー状態をまとめて返す |
| `GET` | `/api/index/watch?revision=N` | 変更があるまで待つロングポーリング |
| `POST` | `/api/rescan` | 手動再スキャン |
| `GET` `PUT` | `/api/config` | 設定の取得・更新 |
| `POST` `PATCH` `DELETE` | `/api/roots[/{id}]` | ルートフォルダの追加・改名・削除 |
| `GET` | `/api/browse?path=` | 設定画面のフォルダ選択用ディレクトリ一覧 |
| `POST` | `/api/user/favorites` `/api/user/hidden` `/api/user/recents` | ユーザー状態の更新 |
| `GET` | `/api/source?fileId=` | ソース表示用のテキスト取得 |
| `GET` | `/api/tex/status` | 検出された LaTeX エンジンなどの実行環境 |
| `POST` | `/api/tex/compile` | `.tex` を PDF へコンパイル（`force` で強制再実行） |
| `GET` | `/api/tex/pdf?fileId=&v=` | コンパイル済み PDF の配信 |
| `POST` | `/api/open` | 既定のブラウザで開く |
| `GET` `HEAD` | `/raw/{rootId}/{path}` | プレビュー本体と相対アセットの配信 |

## 設計メモ

- **スキャン**: `os.scandir` で反復。タイトルは先頭 64KB のみ読み、`(mtime, size)` をキーにキャッシュするため、
  再スキャン時に読み直すのは変更されたファイルだけです（5,100 ファイルで初回 134ms / 再スキャン 166ms）。
- **描画**: ホームは 48 件ずつ追記描画（`IntersectionObserver`）、サイドバーは固定行高の仮想スクロール。
  5,100 ファイルでも DOM 上の行は 40 行程度に保たれます。
- **プレビューの分離**: `sandbox="allow-scripts allow-forms allow-modals allow-popups allow-downloads"`。
  `allow-same-origin` を付けないので unique origin となり、アプリ本体の DOM・localStorage には触れません。
  `localStorage` を使うページ向けにツールバーの「分離 / 互換」で切り替えられます（互換モードは分離レベルが下がります）。
- **安全性**: `/raw` は必ずルート配下に解決できたパスだけを返します（`..`・絶対パス・ルート外シンボリックリンクは拒否）。
  既定のバインド先は `127.0.0.1` です。`--host 0.0.0.0` で公開すると、`/api/browse` を含めローカルの
  ファイル情報が同一ネットワークへ露出するため、信頼できるネットワーク以外では避けてください。
- **LaTeX**: マジックコメント（`% !TEX program = ...`）→ プリアンブル（`luatexja` / `xeCJK` / `jsarticle` など）
  → 既定順、の優先度でエンジンを選びます。コンパイルは常に `-no-shell-escape` で実行し、`\write18` は使えません。
  生成物は「ソース内容 + エンジン」のハッシュをキーにキャッシュするため、内容が変わらない限り再コンパイルしません
  （日本語 lualatex 文書で初回 12 秒 → 2 回目 101ms → キャッシュ 0.4ms）。`\documentclass` の無い断片ファイルは
  コンパイルせず、その旨とソース表示を案内します。
- **PDF の表示**: PDF はサンドボックス iframe ではブラウザ内蔵ビューアが無効化されるため、PDF のみ `sandbox` を
  付けずに表示しています。PDF ビューアは親ページの DOM やストレージへアクセスできないため、分離は保たれます。
- **エラー処理**: 壊れた HTML はブラウザがそのまま描画し、読めない・消えたファイルはプレビュー領域に
  エラーカードを出すだけでアプリは動き続けます。LaTeX のコンパイル失敗はエラー箇所を含むログを画面上で確認できます。
  設定ファイルや状態ファイルが壊れていても既定値で起動します。

## テスト

```bash
pip install -r requirements-dev.txt
python -m pytest            # 71 tests

# ブラウザ操作の E2E（任意 / Playwright が必要）
python -m hph ./sample-docs --port 8899 --no-browser &
npm install playwright && npx playwright install chromium
node tests/e2e/app.e2e.js   # LaTeX エンジンが無い環境では PDF の検証だけ自動でスキップ
```
