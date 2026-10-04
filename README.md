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
- **インラインプレビュー** — 外部ブラウザを開かず、アプリ内の iframe に表示。サンドボックスで隔離するため、プレビュー対象の CSS / JS はアプリ本体に干渉できない。
- **LaTeX の自動コンパイル** — `.tex` を選ぶとサーバー側で PDF にして同じ画面に表示する。エンジンは自動判定し、結果はキャッシュするので 2 回目以降は即表示。失敗したらエラー箇所を含むログをその場で開ける。
- **相対パス・ルート絶対パスの解決** — プレビュー対象と同じ階層の画像 / CSS / JS はそのまま読める。`/assets/app.css` のようなルート絶対パス参照も解決する。
- **即応する切り替え** — 一度開いたファイルは iframe プールに残るため、行き来しても再読み込みが起きない。サイドバーは仮想スクロールで数千件でも軽い。
- **お気に入り / 非表示フォルダ / 種類フィルタ** — 残したいものに星を付け、ノイズになるフォルダはカード右クリックで隠し、HTML と TeX はチップで切り替える。
- **表示名の切り替え** — 一覧に出す名前を、文書のタイトル（既定）とファイル名でヘッダーのボタン（または `t` キー）から切り替えられる。設定はブラウザに保存される。
- **自動追従** — バックグラウンドで再スキャンし、変更があればロングポーリングで画面に反映（手動リロード不要）。
- **設定は UI からもファイルからも** — 対象フォルダを OS の選択画面で追加・削除し、除外する名前（全体共通とフォルダごと）、対象ファイルの種類、階層の深さなどを画面上で編集して、JSON 設定ファイルに保存する。

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
# 引数なしで起動（`config.json`の設定を読み込み）
./start.sh     # 仮想環境作成 → 依存インストール → 起動 → ブラウザが開く

# 対象フォルダを指定して起動
./start.sh ~/Documents/html
```

引数（取り込み対象パス）を省略すると `config.json`（無ければ同梱の `sample-docs/`）を対象に起動します。

### デスクトップのアイコンから起動する

最初に一度だけ導入スクリプトを実行すると、仮想環境の準備とデスクトップへのアイコン配置が行われます。
以降はアイコンをダブルクリックするだけで起動し、ブラウザが自動で開きます。

| OS | 導入スクリプト | デスクトップに置かれるもの |
| --- | --- | --- |
| macOS | `./launcher/macos/install.sh` | エイリアス `html-preview-hub`（Terminal で起動） |
| Windows | `launcher\windows\install.cmd` をダブルクリック | ショートカット `html-preview-hub.lnk`（コンソールで起動） |

- **停止**: 開いたウインドウで `Ctrl+C` を **1 回だけ**押します。停止処理には数秒かかります。
  2 回押すと後始末を省いた強制終了になるため、ウインドウが閉じるまで待ってください。停止するとウインドウは自動で閉じます。
- **起動中にもう一度押した場合**: 新しくは起動せず、「すでに起動しています」と表示して起動中の画面をブラウザで開き、
  ウインドウは数秒で閉じます。
- 依存パッケージを更新したとき、またはリポジトリを移動したときは導入スクリプトを再実行します（既存のアイコンは置き換わります）。
- macOS では初回に「ターミナルが Finder を制御する」許可を求められます。エイリアスの作成に必要です。
- Windows 版は Windows 実機で動作確認していません。

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

起動すると、サーバーが応答し始めた時点で `http://127.0.0.1:8765/` が開きます。
同じホスト・ポートで起動済みの場合は新しく起動せず、起動中の画面を開いて終了します。対象フォルダは起動後に画面右上の ⚙ からも追加できます。
コマンドライン引数と設定ファイルの詳細は [docs/configuration.md](docs/configuration.md) を参照してください。

## キャッシュ削除

LaTeX の PDF キャッシュは次のコマンドで削除できます。次回コンパイル時に作り直されます。

```bash
rm -rf ~/.local/state/html-preview-hub/tex-cache
```

`config.json` で `tex_cache_dir` を指定している場合は、そのフォルダを削除してください。

## ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [docs/usage.md](docs/usage.md) | 画面の使い方とキーボードショートカット |
| [docs/configuration.md](docs/configuration.md) | 設定ファイル・コマンドライン引数・状態ファイル |
| [docs/architecture.md](docs/architecture.md) | 設計書（ディレクトリ構成・処理フロー・設計判断・セキュリティ設計） |
| [docs/api.md](docs/api.md) | HTTP API 仕様 |

## テスト

```bash
pip install -r requirements-dev.txt
python -m pytest

# ブラウザ操作の E2E（任意 / Playwright が必要）
python -m hph ./sample-docs --port 8899 --no-browser &
npm install playwright && npx playwright install chromium
node tests/e2e/app.e2e.js   # LaTeX エンジンが無い環境では PDF の検証だけ自動でスキップ
```
