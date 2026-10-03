# API

html-preview-hub の HTTP API は、フロントエンド（SPA）が使うためのローカル専用の内部 API です。
既定では `127.0.0.1` にのみバインドされ、外部ネットワークには公開されません。

## エンドポイント一覧

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/api/health` | アプリ名とバージョン。起動済みのインスタンスの判定に使う |
| `GET` | `/api/index` | フォルダ / ファイル / ルート / ユーザー状態をまとめて返す |
| `GET` | `/api/index/watch?revision=N` | 変更があるまで待つロングポーリング |
| `POST` | `/api/rescan` | 手動再スキャン |
| `GET` `PUT` | `/api/config` | 設定の取得・更新 |
| `POST` `PATCH` `DELETE` | `/api/roots[/{root_id}]` | ルートフォルダの追加・改名・除外ルールの更新・削除 |
| `GET` | `/api/browse?path=` | 設定画面のフォルダ選択用ディレクトリ一覧 |
| `POST` | `/api/pick-folder` | OS のフォルダ選択画面を開き、選ばれたフォルダを返す |
| `POST` | `/api/user/favorites` `/api/user/hidden` `/api/user/recents` | ユーザー状態の更新 |
| `GET` | `/api/source?fileId=` | ソース表示用のテキスト取得 |
| `GET` | `/api/tex/status` | 検出された LaTeX エンジンなどの実行環境 |
| `POST` | `/api/tex/compile` | `.tex` のコンパイルを開始（`force` で強制再実行）。完了は待たない |
| `GET` | `/api/tex/job?fileId=` | バックグラウンドで走っているコンパイルの状態 |
| `GET` | `/api/tex/pdf?fileId=&v=` | コンパイル済み PDF の配信 |
| `POST` | `/api/open` | 既定のブラウザで開く |
| `GET` `HEAD` | `/raw/{rootId}/{path}` | プレビュー本体と相対アセットの配信 |

JSON を返す API のエラーは `{"error": メッセージ}` を該当ステータス（`400` / `403` / `404` / `409` / `500` など）で返します。
`/raw` と `/api/tex/pdf` はプレビューの iframe にそのまま表示されるため、エラー時も HTML のエラーページを対応するステータスコードで返します。

## 起動確認

- `GET /api/health` — `{"app": "html-preview-hub", "version": バージョン}` を返します。`python -m hph` は起動前に
  このエンドポイントへ問い合わせ、`app` が一致すれば起動済みとみなして新しく起動しません。

## インデックスと監視

- `GET /api/index` — インデックスの全量を返します。主な項目は次のとおりです。
  - `revision` / `scannedAt` / `durationMs` / `truncated` / `errors` — スキャンの状態
  - `roots` — 登録済みルートフォルダ（存在確認・ファイル数・そのフォルダの `exclude` を含む）
  - `folders` / `files` — フォルダ / ファイルの一覧
  - `stats` — 件数などの集計
  - `userState` — お気に入り・非表示フォルダ・履歴
- `GET /api/index/watch?revision=N` — クエリで渡した `revision` より新しい変更が起きるか、タイムアウト（約 4 秒）するまで応答を保留するロングポーリングです。`{"revision": N, "changed": bool}` を返します。
- `POST /api/rescan` — バックグラウンドの自動スキャンとは別に、即座に再スキャンして最新のインデックスを返します。

## 設定とルート

- `GET /api/config` — 現在の設定内容と設定ファイルのパスを返します。`config.exclude`（全体の除外ルール）と `config.roots[].exclude`（フォルダごとの除外ルール）を含みます。
- `PUT /api/config` — 拡張子・除外設定・監視間隔・LaTeX 関連設定などを部分更新し、保存後に強制再スキャンします。値は設定ファイルを読み込むときと同じ補正（下限値・拡張子の正規化など）を通します（`roots` はこの API では更新できません）。`exclude` は全体の除外ルールを置き換えます。ルールの形と検証は [configuration.md](./configuration.md#除外ルール) のとおりで、不正なら `400` を返します。`ignore_dirs` は受け付けません（ほかの未知のキーと同じく無視されます）。
- `POST /api/roots` — `path`（必須）と任意の `name` でルートフォルダを追加します。応答は `{"root": {...}}` で、`exclude`（追加直後は空）を含みます。
- `PATCH /api/roots/{root_id}` — ルートフォルダの表示名（`name`）と、そのフォルダだけの除外ルール（`exclude`。置き換え）を更新します。どちらか一方だけでも、同時でも構いません。応答は `{"root": {...}}` です。`exclude` が不正なら `400`、`root_id` が無ければ `404` を返します。
- `DELETE /api/roots/{root_id}` — ルートフォルダを削除します。
- `GET /api/browse?path=` — 設定画面のフォルダ選択用に、指定パス（省略時はホーム）配下のサブディレクトリ一覧を返します。隠しディレクトリは除外されます。
- `POST /api/pick-folder` — サーバーを動かしている PC に OS のフォルダ選択画面を開き、閉じられるまで待って結果を返します。ほかの処理は止まりません。応答は次のいずれかです。
  - `{"status": "selected", "path": "/abs/path"}` — フォルダが選ばれた
  - `{"status": "cancelled"}` — キャンセルされた、または待ち時間の上限（600 秒）を超えた
  - `{"status": "unavailable", "message": "..."}` — 開く手段が無い、または起動に失敗した。呼び出し側はアプリ内の一覧（`/api/browse`）に切り替えます
  - 選択画面は macOS が `osascript`、Windows が PowerShell、Linux が `zenity`（無ければ `kdialog`）で開きます。Windows と Linux は実機で未確認です。
  - 画面が利用者の PC に出るため、次の場合は `403` を返します。要求元がループバックアドレスでない、`Host` ヘッダが `localhost` / `127.0.0.1` / `::1` でない、`Origin` ヘッダがあって `Host` と一致しない。
  - 選択画面がすでに開いている間の要求は `409` です（同時に開けるのは 1 つ）。
  - 選ばれたフォルダはこの API では登録しません。続けて `POST /api/roots` を呼びます。

## ユーザー状態

お気に入り・非表示フォルダ・最近開いたファイルは設定ファイルとは別に永続化されるユーザー状態です。

- `POST /api/user/favorites` — `fileId` を渡してお気に入りを ON/OFF 切り替えます。
- `POST /api/user/hidden` — `folderId` を渡して非表示フォルダを ON/OFF 切り替えます。
- `POST /api/user/recents` — `fileId` を渡して最近開いたファイル一覧の先頭に追加します。

いずれも更新後の一覧を含む JSON（例: `{"added": bool, "favorites": [...]}`）を返します。

## ソースと LaTeX

- `GET /api/source?fileId=` — ファイルの中身をテキストとして返します（先頭 2MB まで、`truncated` で切り詰めの有無を通知）。
- `GET /api/tex/status` — 検出済みの LaTeX エンジン一覧、`latexmk` / `dvipdfmx` の有無、設定上のエンジンを返します。
- `POST /api/tex/compile` — `fileId` の `.tex` のコンパイルを**開始**し、その時点の状態を返します（`force: true` でキャッシュを無視して再実行）。コンパイルはバックグラウンドで走るため、呼び出しはすぐ返ります。キャッシュ済みなど短時間で終わるものはそのまま結果まで返し、時間がかかるものは `{"status": "running", "elapsedMs": ...}` を返します。
- `GET /api/tex/job?fileId=` — 走っているコンパイルの状態を返します。`status` が `running` の間は`elapsedMs`（経過時間）を、終わっていれば `/api/tex/compile` と同じ完了結果を返します。記録が無い場合は `404` です。
  - 完了状態は `ok` / `error` / `fragment` / `unavailable` のいずれかで、成功時は `pdfUrl`（`/api/tex/pdf` への参照）を含みます。失敗もクライアントで表示できるようステータス `200` でログ等を返します。
  - 同じファイルへの要求が実行中に重なった場合は 1 本のジョブに相乗りします。異なるファイルどうしは並列に走ります（同時実行数には上限があります）。
- `GET /api/tex/pdf?fileId=&v=` — `v`（コンパイル結果のフィンガープリント）に対応するキャッシュ済み PDF を配信します。未生成の場合は再コンパイルを促すエラーになります。

## ファイル配信

- `POST /api/open` — `fileId` に対応するファイルを OS の既定ブラウザで開きます。
- `GET` `HEAD /raw/{rootId}/{path}` — プレビュー本体（HTML）と、そこから相対参照される画像 / CSS / JS などのアセットを配信します。`rootId` 配下に実際に解決できるパスのみを返し、`..` によるパス上昇・絶対パス・ルート外へのシンボリックリンクは拒否します（実装の詳細は設計書を参照）。ルート絶対パス（例 `/assets/app.css`）による参照は、Referer ヘッダーから元のルートを推定するフォールバックで解決します。

## 関連ドキュメント

- [README](../README.md)
- [設計書](./architecture.md)
- [設定](./configuration.md)
- [使い方](./usage.md)
