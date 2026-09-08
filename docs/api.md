# API

html-preview-hub の HTTP API は、フロントエンド（SPA）が使うためのローカル専用の内部 API です。
既定では `127.0.0.1` にのみバインドされ、外部ネットワークには公開されません。

## エンドポイント一覧

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/api/index` | フォルダ / ファイル / ルート / ユーザー状態をまとめて返す |
| `GET` | `/api/index/watch?revision=N` | 変更があるまで待つロングポーリング |
| `POST` | `/api/rescan` | 手動再スキャン |
| `GET` `PUT` | `/api/config` | 設定の取得・更新 |
| `POST` `PATCH` `DELETE` | `/api/roots[/{root_id}]` | ルートフォルダの追加・改名・削除 |
| `GET` | `/api/browse?path=` | 設定画面のフォルダ選択用ディレクトリ一覧 |
| `POST` | `/api/user/favorites` `/api/user/hidden` `/api/user/recents` | ユーザー状態の更新 |
| `GET` | `/api/source?fileId=` | ソース表示用のテキスト取得 |
| `GET` | `/api/tex/status` | 検出された LaTeX エンジンなどの実行環境 |
| `POST` | `/api/tex/compile` | `.tex` のコンパイルを開始（`force` で強制再実行）。完了は待たない |
| `GET` | `/api/tex/job?fileId=` | バックグラウンドで走っているコンパイルの状態 |
| `GET` | `/api/tex/pdf?fileId=&v=` | コンパイル済み PDF の配信 |
| `POST` | `/api/open` | 既定のブラウザで開く |
| `GET` `HEAD` | `/raw/{rootId}/{path}` | プレビュー本体と相対アセットの配信 |

JSON を返す API のエラーは `{"error": メッセージ}` を該当ステータス（`400` / `403` / `404` / `500` など）で返します。
`/raw` と `/api/tex/pdf` はプレビューの iframe にそのまま表示されるため、エラー時も HTML のエラーページを対応するステータスコードで返します。

## インデックスと監視

- `GET /api/index` — インデックスの全量を返します。主な項目は次のとおりです。
  - `revision` / `scannedAt` / `durationMs` / `truncated` / `errors` — スキャンの状態
  - `roots` — 登録済みルートフォルダ（存在確認・ファイル数を含む）
  - `folders` / `files` — フォルダ / ファイルの一覧
  - `stats` — 件数などの集計
  - `userState` — お気に入り・非表示フォルダ・履歴
- `GET /api/index/watch?revision=N` — クエリで渡した `revision` より新しい変更が起きるか、タイムアウト（約 25 秒）するまで応答を保留するロングポーリングです。`{"revision": N, "changed": bool}` を返します。
- `POST /api/rescan` — バックグラウンドの自動スキャンとは別に、即座に再スキャンして最新のインデックスを返します。

## 設定とルート

- `GET /api/config` — 現在の設定内容と設定ファイルのパスを返します。
- `PUT /api/config` — 拡張子・除外設定・監視間隔・LaTeX 関連設定などを部分更新し、保存後に強制再スキャンします（`roots` はこの API では更新できません）。
- `POST /api/roots` — `path`（必須）と任意の `name` でルートフォルダを追加します。
- `PATCH /api/roots/{root_id}` — ルートフォルダの表示名を変更します。
- `DELETE /api/roots/{root_id}` — ルートフォルダを削除します。
- `GET /api/browse?path=` — 設定画面のフォルダ選択用に、指定パス（省略時はホーム）配下のサブディレクトリ一覧を返します。隠しディレクトリは除外されます。

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
