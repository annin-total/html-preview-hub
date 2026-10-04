# 設定

html-preview-hub の設定ファイル・コマンドライン引数・状態ファイルのリファレンスです。
画面右上の ⚙ から GUI で編集することもできます。操作方法は [usage.md](./usage.md) を参照してください。

## 設定ファイルの場所

起動時に次の順で探索し、最初に見つかったパスを使います。

1. `--config` / `-c` で指定したパス
2. 環境変数 `HPH_CONFIG`
3. カレントディレクトリの `config.json`（存在する場合）
4. `$XDG_CONFIG_HOME/html-preview-hub/config.json`（未設定なら `~/.config/html-preview-hub/config.json`）

ファイルが存在しない場合は既定値で起動します。まずは同梱の `config.example.json` をコピーして
使ってください。

```bash
cp config.example.json config.json
```

環境変数 `HPH_ROOTS`（OS のパス区切り文字で連結した複数パス）を指定すると、設定ファイルの内容に
加えてルートフォルダを追加できます。`python -m hph <roots...> --save` を組み合わせた場合、
このルートも含めて保存されます。

## 設定キー一覧

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `roots` | `[]` | `{ "name": 表示名, "path": フォルダ, "exclude": ルールの配列 }` の配列。`name` と `exclude` は省略できます |
| `include_extensions` | `[".html", ".htm", ".xhtml", ".tex"]` | 一覧に載せる拡張子 |
| `exclude` | `[]` | すべてのルートに適用する除外ルールの配列（[除外ルール](#除外ルール)） |
| `ignore_globs` | `[]` | 除外する相対パスの glob |
| `max_depth` | `16` | 潜る階層の上限 |
| `max_files` | `50000` | 読み込むファイル数の上限 |
| `follow_symlinks` | `false` | シンボリックリンクを辿るか |
| `title_scan_bytes` | `65536` | タイトル抽出のためファイル先頭から読むバイト数 |
| `watch_interval_seconds` | `4.0` | 自動再スキャン間隔（`0` で無効） |
| `host` / `port` | `127.0.0.1` / `8765` | 待ち受け先 |
| `open_browser` | `true` | 起動時にブラウザを開く |

### 除外ルール

`exclude`（全体）と `roots[].exclude`（そのフォルダだけ）は、同じ形のルールの配列です。スキャンは「全体 ＋ そのフォルダの除外」をまとめて判定します。

```json
{ "target": "folder", "match": "contains", "value": "draft" }
```

| 項目 | 値 |
| --- | --- |
| `target` | `folder`（フォルダ名に当てる。一致したフォルダは中身ごと走査しない）／ `file`（拡張子を含むファイル名に当てる） |
| `match` | `equals`（一致）／ `contains`（含む）／ `prefix`（で始まる）／ `suffix`（で終わる） |
| `value` | 名前。前後の空白を除いて 1〜200 文字で、`/` と `\` を含められない |

- 大文字・小文字は区別しません。`folder` はルート配下のどの深さのフォルダにも当たります。
- 1 つの配列に 100 件までです。3 項目とも同じルール（`value` は大文字・小文字を無視して比べる）は 1 件にまとめられます。
- 形が不正なとき、設定ファイルでは起動を中止し（終了コード `2`）、API では `400` を返します。
- 次のフォルダは常に走査せず、設定にも画面にも現れません。`node_modules`・`__pycache__`・`venv`（大文字・小文字は区別しない）と、名前が `.` で始まるフォルダです。
- `ignore_globs` は全体の設定で、画面では編集できません。設定ファイルで指定します。

旧形式の `ignore_dirs` が設定ファイルにある場合は、読み込み時に `exclude` へ移します。

- 旧形式の既定値（`.git`・`.hg`・`.svn`・`node_modules`・`__pycache__`・`.venv`・`venv`・`dist`・`build` など 15 件）とまったく同じ集合なら、何も移しません。
- それ以外は、常に除外される名前と `.` で始まる名前を除いた残りを `{"target": "folder", "match": "equals", "value": 名前}` として `exclude` に合流させます（重複はまとめます）。
- 保存では `exclude` だけを書き、`ignore_dirs` は書きません。

### LaTeX 関連キー

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `tex_enabled` | `true` | LaTeX の PDF プレビューを使うか |
| `tex_engine` | `"auto"` | 使用エンジン。`auto` は自動判定、`pdflatex` などで固定 |
| `tex_use_latexmk` | `true` | latexmk があれば利用する（参照解決の再実行を任せる） |
| `tex_use_sibling_pdf` | `true` | `.tex` と同じ場所に新しい PDF があればそれを表示する |
| `tex_font_fallback` | `true` | この環境に無いフォントを要求して失敗したとき、TeX Live 同梱のフォント（Harano Aji など）へ読み替えて一度だけやり直す（LuaTeX のみ） |
| `tex_max_passes` | `2` | latexmk を使わないときのコンパイル回数 |
| `tex_timeout_seconds` | `180` | 1 回のコンパイルの上限時間 |
| `tex_cache_limit` | `200` | 保持する PDF キャッシュの数 |
| `tex_cache_dir` | 状態ディレクトリ配下の `tex-cache` | PDF キャッシュの置き場所（空文字なら既定値） |

## コマンドライン引数

`python -m hph [roots...] [オプション]` で起動します。

| 引数 | 説明 |
| --- | --- |
| `roots...` | スキャン対象フォルダ（複数指定可）。設定ファイルのルートに追加されます |
| `-c, --config PATH` | 設定ファイルのパス |
| `--save` | ルートフォルダ（引数・`HPH_ROOTS` の分も含む）を設定ファイルへ保存 |
| `--host` / `--port` | バインド先（既定 `127.0.0.1:8765`） |
| `--no-browser` | 起動時にブラウザを開かない |
| `--log-level` | uvicorn のログレベル（既定 `info`） |
| `--pause-on-exit SECONDS` | 終了前に指定秒数待ってから終了する。エラー終了のときは Enter キーを待つ。デスクトップのアイコンから起動したとき、ウインドウが閉じる前にメッセージを読めるようにするためのもの |
| `--version` | バージョンを表示して終了 |

`--host` / `--port` / `--no-browser` は設定ファイルの値より優先されますが、**設定ファイルには保存されません**
（`--save` で保存されるのはルートフォルダのみです）。

### 終了コード

| コード | 意味 |
| --- | --- |
| `0` | 正常に停止した |
| `1` | ポートが別のアプリに使われている、またはサーバーを起動できなかった |
| `2` | 設定ファイルの不備 |
| `3` | 同じホスト・ポートで html-preview-hub が起動済みのため、起動しなかった |

## 状態ファイル

お気に入り・非表示フォルダ・最近開いたファイル（最大 40 件）は設定ファイルとは別に、次のパスへ
JSON で保存されます。

```
~/.local/state/html-preview-hub/state.json
```

環境変数 `HPH_STATE_DIR`（または `XDG_STATE_HOME`）でディレクトリを変更できます。

## 壊れている場合の挙動

- **状態ファイル**（`state.json`）が壊れている場合は無視され、空の状態（お気に入り等なし）で起動します。次に保存されたタイミングで正しい内容に上書きされます。
- **設定ファイル**（`config.json`）が壊れている場合（JSON として不正、オブジェクトでない、キーの値が不正な型など）は既定値へのフォールバックはされず、エラーメッセージを表示して起動を中止します（終了コード `2`、型不正の場合はエラー終了）。設定ファイルの構文には注意してください。

## 関連ドキュメント

- [../README.md](../README.md)
- [./architecture.md](./architecture.md) — 設計書
- [./api.md](./api.md) — API 仕様
- [./usage.md](./usage.md) — 使い方
